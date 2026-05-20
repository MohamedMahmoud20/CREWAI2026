"""Run the Telegram bot: `python telegram_bot.py` from the project root (myproject/)."""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def _project_venv_python(root: Path) -> Path | None:
    win = root / ".venv" / "Scripts" / "python.exe"
    if win.is_file():
        return win
    for name in ("python3", "python"):
        p = root / ".venv" / "bin" / name
        if p.is_file():
            return p
    return None


# If the user runs `python telegram_bot.py` with a global interpreter, re-exec using
# `.venv` so dependencies (requests, crewai, etc.) from pyproject.toml are available.
_venv = _project_venv_python(_ROOT)
if _venv is not None:
    try:
        if Path(sys.executable).resolve() != _venv.resolve():
            os.execv(str(_venv), [str(_venv), str(__file__), *sys.argv[1:]])
    except OSError:
        pass

_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from myproject.telegram_bot_app import main  # noqa: E402

if __name__ == "__main__":
    main()
