"""
Single-instance bot lock manager to prevent multiple bot instances from running concurrently.

Stores lock state in .bot.lock file with PID, hostname, and timestamp.
On startup, checks if a previous instance is still alive before acquiring the lock.
"""

import json
import os
import socket
from pathlib import Path
from datetime import datetime
from typing import Optional


class BotLockManager:
    """
    Manages a process lock file to ensure only one bot instance runs at a time.
    
    Lock file (.bot.lock) contains:
    - pid: Process ID of the bot instance
    - hostname: Hostname where the bot is running
    - start_time: ISO format timestamp when the lock was acquired
    
    Behavior:
    - On acquire(): If lock exists and PID is alive, raises ConflictError with details
    - If lock exists but PID is dead, treats as stale and replaces it
    - On release(): Removes the lock file (if it still belongs to this process)
    """
    
    def __init__(self, lock_file: Path | str = ".bot.lock"):
        """
        Initialize the lock manager.
        
        Args:
            lock_file: Path to lock file (relative to current working directory, 
                      or absolute path)
        """
        self.lock_file = Path(lock_file).resolve()
        self.current_pid = os.getpid()
        self.current_hostname = socket.gethostname()
        self.lock_acquired = False
    
    def acquire(self) -> None:
        """
        Acquire the bot lock.
        
        Raises:
            BotLockConflictError: If another bot instance (with live PID) is already running
        
        Silently replaces stale locks (dead PIDs).
        """
        lock_data = {
            "pid": self.current_pid,
            "hostname": self.current_hostname,
            "start_time": datetime.now().isoformat(),
        }

        while True:
            try:
                # Atomic create prevents two bot startups from acquiring the lock
                # at the same time.
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    json.dump(lock_data, f, indent=2)
                self.lock_acquired = True
                return
            except FileExistsError:
                try:
                    with open(self.lock_file, "r") as f:
                        existing_lock = json.load(f)

                    existing_pid = existing_lock.get("pid")
                    existing_hostname = existing_lock.get("hostname")
                    existing_start_time = existing_lock.get("start_time")

                    if existing_pid and self._is_process_alive(existing_pid):
                        raise BotLockConflictError(
                            f"Another bot instance is already running on {existing_hostname} "
                            f"(PID: {existing_pid}, started: {existing_start_time}). "
                            f"Kill it or wait for it to finish."
                        )
                except json.JSONDecodeError:
                    pass

                # Stale or corrupted lock: remove it and retry atomic creation.
                try:
                    self.lock_file.unlink()
                except FileNotFoundError:
                    pass
    
    def release(self) -> None:
        """
        Release the bot lock by removing the lock file.
        
        Only removes the lock file if it belongs to this process (safety check).
        """
        if not self.lock_acquired:
            return
        
        try:
            if self.lock_file.exists():
                with open(self.lock_file, "r") as f:
                    lock_data = json.load(f)
                
                if lock_data.get("pid") == self.current_pid:
                    self.lock_file.unlink()
                    self.lock_acquired = False
        except Exception as e:
            # Log but don't raise—cleanup is best-effort
            print(f"Warning: Failed to release lock: {e}")
    
    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        """
        Check if a process with the given PID is still running.
        
        Cross-platform implementation:
        - Windows: Uses os.kill() with signal 0 (test signal, no harm)
        - Unix-like: Uses os.kill() with signal 0 (test signal, no harm)
        
        Returns True if process exists, False otherwise.
        """
        try:
            # Signal 0: check if process exists without sending a signal
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            # ProcessLookupError: Process doesn't exist (most common, means dead)
            # PermissionError: Process exists but we can't signal it (rare, means alive)
            # OSError: Other issues, assume alive to be safe
            return False
        except Exception:
            # Unknown error, assume process is alive to be safe
            return True


class BotLockConflictError(Exception):
    """Raised when another bot instance is already running."""
    pass
