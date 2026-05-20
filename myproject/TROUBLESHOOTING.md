# Troubleshooting Guide: Telegram Bot Lock & Conflict Errors

## Error: "Conflict: terminated by other getUpdates request"

This error occurs when multiple bot instances attempt to poll for Telegram updates simultaneously with the same bot token.

### Root Cause

Telegram's bot API only allows **one active polling connection per bot token** at a time. If a second instance tries to connect, the server terminates the older connection (or rejects the new one).

### Quick Fix

1. **Stop the bot** (if it's still running):
   ```powershell
   # In the terminal where the bot is running
   Ctrl+C
   ```

2. **Wait 3-5 seconds** for the Telegram connection to close cleanly.

3. **Restart the bot**:
   ```powershell
   cd c:\Users\MohamedMahmoud\Desktop\CREWAI\myproject
   python -m myproject.telegram_bot_app
   ```

4. **Check for success**:
   - You should see a log message: `Bot starting: PID=XXXXX, hostname=..., ...`
   - If you see "Cannot start bot: Another bot instance is already running", go to **Scenario 1** below.

---

## Scenario 1: Local Duplicate Process (Same Machine)

### Symptoms

- Error message: `Cannot start bot: Another bot instance is already running on [hostname] (PID: XXXXX, started: ...)`
- You didn't intentionally start the bot twice
- You see the `.bot.lock` file in the project root

### Diagnosis

**Check if process still exists:**
```powershell
# Windows: List all Python processes
Get-Process python

# Or more detailed:
Get-Process python | Select-Object Name, Id, Path
```

**Check for the bot process specifically:**
```powershell
# Show Python process with details
wmic process where name="python.exe" get ProcessId,CommandLine
```

### Solution A: Kill Stale Process (If PID is Dead)

If the PID in the error message **no longer exists** in the process list:

1. **Remove the stale lock file**:
   ```powershell
   cd c:\Users\MohamedMahmoud\Desktop\CREWAI\myproject
   Remove-Item .bot.lock -Force
   ```

2. **Restart the bot**:
   ```powershell
   python -m myproject.telegram_bot_app
   ```

### Solution B: Kill Running Instance (If Process is Alive)

If the PID in the error **is still running** and you want to replace it:

1. **Terminate the old instance** (replace XXXXX with the PID from error message):
   ```powershell
   # Graceful termination (preferred)
   Stop-Process -Id XXXXX -Confirm

   # Or force kill if graceful doesn't work
   Stop-Process -Id XXXXX -Force
   ```

2. **Wait 2-3 seconds** for cleanup.

3. **Start the bot**:
   ```powershell
   python -m myproject.telegram_bot_app
   ```

### Solution C: Multiple Terminals Running Bot

If you have the bot running in **multiple PowerShell/Terminal windows**:

1. Close all but one PowerShell window running the bot
2. Or, in each window except the one you want to keep:
   - Press `Ctrl+C` to gracefully stop
3. Verify only one remains:
   ```powershell
   Get-Process python | Where-Object {$_.CommandLine -like "*telegram_bot*"}
   ```

---

## Scenario 2: Remote Conflict (Different Machine/Server)

### Symptoms

- Error message: `Telegram conflict after 3 retries. Another bot instance may be running on another server/terminal with the same token.`
- You see retry messages like: `Conflict error (attempt 1/3): ... Retrying in 1s...`
- You're running the bot locally and it should be the only instance
- The lock file does NOT show a conflicting PID locally

### Root Cause

Another bot is already running **on a different machine or cloud server** with the **same `BOT_TOKEN`**.

Telegram routes updates to only the most recently connected instance. The older instance gets a "conflict" error.

### Solution

**Option 1: Check if you have the bot running elsewhere**

1. Check all your machines, servers, containers, or cloud deployments
2. Stop the other instance (SSH into server, stop container, etc.)
3. Restart this local instance

**Option 2: Isolate with a new bot token**

If you need multiple bot instances (e.g., dev + prod):

1. Create a **new bot** in Telegram's BotFather:
   ```
   /newbot
   Give it a name like "MyBot-Dev" or "MyBot-Prod"
   BotFather will give you a NEW token
   ```

2. Update your local `.env`:
   ```
   BOT_TOKEN=<new_token_from_botfather>
   ```

3. Restart the bot

**Option 3: Verify token ownership**

Check `.env` against BotFather:
```powershell
# View your current token (first 10 chars + last 10 chars for security)
$token = (Get-Content .env | Select-String "^BOT_TOKEN=").ToString().Substring(10)
$displayToken = $token.Substring(0,10) + "..." + $token.Substring($token.Length - 10)
Write-Host "Current token: $displayToken"
```

Then in Telegram, chat with BotFather:
```
/mybots
→ Select your bot
→ Edit Token
```

Verify the token matches.

---

## Scenario 3: Lock File Corruption

### Symptoms

- You see an error about the lock file but it doesn't match any running process
- The `.bot.lock` file exists but seems wrong
- Restarting Python/clearing processes doesn't help

### Diagnosis

Inspect the lock file:
```powershell
cd c:\Users\MohamedMahmoud\Desktop\CREWAI\myproject
Get-Content .bot.lock
```

You should see JSON like:
```json
{
  "pid": 12345,
  "hostname": "MY-COMPUTER",
  "start_time": "2026-04-21T12:34:56.789123"
}
```

### Solution

**Delete the corrupted lock file:**
```powershell
Remove-Item .bot.lock -Force
```

**Restart the bot:**
```powershell
python -m myproject.telegram_bot_app
```

---

## Scenario 4: How to Stop the Bot Cleanly

### Normal Shutdown

```powershell
# In the terminal running the bot
Ctrl+C
```

You should see:
```
Received signal 2, shutting down gracefully...
```

Wait a few seconds for full cleanup.

### If Ctrl+C Doesn't Work

```powershell
# Kill by PID (from the startup log or Get-Process)
Stop-Process -Id XXXXX -Confirm
```

### If Everything Fails

```powershell
# Nuclear option: kill all Python processes (WARNING: use carefully!)
Stop-Process -Name python -Force -Confirm
# Then restart your terminal
```

---

## Platform-Specific Notes

### Windows (Your Setup)

- Lock file: `.bot.lock` stored in project root as plain text JSON
- Process detection: Uses Windows API via Python's `os.kill(pid, 0)`
- Task Manager: Press `Ctrl+Shift+Esc` → Find `python.exe` → Note the PID
- PowerShell: `Get-Process python` lists all Python processes

### Lock File Cleanup

**Automatic**: Removed when bot exits via `Ctrl+C` or clean shutdown.

**Manual** (if bot crashed):
```powershell
Remove-Item c:\Users\MohamedMahmoud\Desktop\CREWAI\myproject\.bot.lock -Force
```

### Signal Handling on Windows

- `Ctrl+C` → `SIGINT` (caught by signal handler, triggers graceful shutdown)
- Close terminal window → `SIGTERM` (caught by signal handler)
- `Stop-Process` → Process killed (lock released via `finally` block)

---

## Monitoring & Debugging

### View Bot Logs in Real-Time

```powershell
cd c:\Users\MohamedMahmoud\Desktop\CREWAI\myproject
python -m myproject.telegram_bot_app

# Watch for these startup lines:
# INFO - Bot starting: PID=XXXXX, hostname=MY-COMPUTER, cwd=..., polling_mode=long_polling
# 
# If you see a conflict retry:
# WARNING - Conflict error (attempt 1/3): ... Retrying in 1s...
```

### Check for Zombie Processes

```powershell
# Show all Python processes
Get-Process python -IncludeUserName

# Show Python processes matching telegram pattern
Get-Process python | Where-Object {$_.CommandLine -like "*telegram*"}
```

### Enable Debug Logging (Optional)

Edit `telegram_bot_app.py` and change:
```python
logging.basicConfig(level=logging.DEBUG)  # Instead of logging.INFO
```

This will show much more detail, but will also be verbose.

---

## When to Contact Support

If after trying these steps you still see the error:

1. **Collect diagnostic info:**
   ```powershell
   # Get all Python processes
   Get-Process python | Select-Object Name, Id, @{Name="Memory";Expression={$_.WorkingSet/1MB}}
   
   # Show the lock file
   Get-Content .bot.lock
   
   # Show the last 50 log lines
   python -m myproject.telegram_bot_app 2>&1 | Tee-Object bot_debug.log
   ```

2. **Check the .env file** (without sharing the actual token):
   ```
   BOT_TOKEN=123456789:AAH... (first 20 chars visible, rest hidden)
   ```

3. **Describe:**
   - When did the error first occur?
   - Is the bot running in Docker, Systemd, or just Python terminal?
   - Are there any other bot instances you know of?
   - Does restarting your machine help?

---

## Summary

| Error | Cause | Quick Fix |
|-------|-------|-----------|
| `Cannot start bot: Another bot instance is already running` | Duplicate process on this machine | `Remove-Item .bot.lock -Force` or `Stop-Process -Id XXX` |
| `Telegram conflict after 3 retries` | Another bot on different machine with same token | Stop that bot, or get a new token |
| `.bot.lock` corruption | Bot crashed without cleanup | `Remove-Item .bot.lock -Force` |
| No error, but bot seems stuck | Network issue, not lock issue | Restart: `Ctrl+C`, wait 3s, restart |
