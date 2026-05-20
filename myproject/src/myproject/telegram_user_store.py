"""
Local JSON persistence: Telegram user id -> company_id and onboarding flags.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()

# Default: project_root/data/telegram_users.json (project_root = parent of src/)
_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "telegram_users.json"


def _path() -> Path:
    return _DEFAULT_PATH


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_raw() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(data: dict[str, Any]) -> None:
    path = _path()
    _ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def get_record(telegram_user_id: int) -> dict[str, Any]:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = raw.get(key)
        if isinstance(rec, dict):
            return dict(rec)
        return {}


def has_company_id(telegram_user_id: int) -> bool:
    rec = get_record(telegram_user_id)
    cid = rec.get("company_id")
    return isinstance(cid, int) and cid > 0


def get_company_id(telegram_user_id: int) -> int | None:
    rec = get_record(telegram_user_id)
    cid = rec.get("company_id")
    if isinstance(cid, int) and cid > 0:
        return cid
    return None


def has_fiscal_year_id(telegram_user_id: int) -> bool:
    rec = get_record(telegram_user_id)
    fid = rec.get("fiscal_year_id")
    return isinstance(fid, int) and fid > 0


def get_fiscal_year_id(telegram_user_id: int) -> int | None:
    rec = get_record(telegram_user_id)
    fid = rec.get("fiscal_year_id")
    if isinstance(fid, int) and fid > 0:
        return fid
    return None


def has_login_session(telegram_user_id: int) -> bool:
    rec = get_record(telegram_user_id)
    auth_header = rec.get("auth_header")
    return isinstance(auth_header, str) and bool(auth_header.strip())


def get_auth_header(telegram_user_id: int) -> str | None:
    rec = get_record(telegram_user_id)
    auth_header = rec.get("auth_header")
    if isinstance(auth_header, str) and auth_header.strip():
        return auth_header.strip()
    return None


def is_awaiting_login_email(telegram_user_id: int) -> bool:
    rec = get_record(telegram_user_id)
    return bool(rec.get("awaiting_login_email"))


def set_awaiting_login_email(telegram_user_id: int, waiting: bool) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        if waiting:
            rec["awaiting_login_email"] = True
        else:
            rec.pop("awaiting_login_email", None)
        raw[key] = rec
        _save_raw(raw)


def is_awaiting_login_password(telegram_user_id: int) -> bool:
    rec = get_record(telegram_user_id)
    return bool(rec.get("awaiting_login_password"))


def set_awaiting_login_password(telegram_user_id: int, waiting: bool) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        if waiting:
            rec["awaiting_login_password"] = True
        else:
            rec.pop("awaiting_login_password", None)
        raw[key] = rec
        _save_raw(raw)


def is_awaiting_fiscal_year(telegram_user_id: int) -> bool:
    rec = get_record(telegram_user_id)
    return bool(rec.get("awaiting_fiscal_year"))


def set_awaiting_fiscal_year(telegram_user_id: int, waiting: bool) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        if waiting:
            rec["awaiting_fiscal_year"] = True
        else:
            rec.pop("awaiting_fiscal_year", None)
        raw[key] = rec
        _save_raw(raw)


def save_login_email(telegram_user_id: int, email: str) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        rec["login_email"] = email.strip()
        rec.pop("awaiting_login_email", None)
        rec["awaiting_login_password"] = True
        raw[key] = rec
        _save_raw(raw)


def get_login_email(telegram_user_id: int) -> str | None:
    rec = get_record(telegram_user_id)
    email = rec.get("login_email")
    if isinstance(email, str) and email.strip():
        return email.strip()
    return None


def save_login_session(telegram_user_id: int, email: str, auth_header: str) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        rec["login_email"] = email.strip()
        rec["auth_header"] = auth_header.strip()
        rec.pop("awaiting_login_email", None)
        rec.pop("awaiting_login_password", None)
        raw[key] = rec
        _save_raw(raw)


def clear_login_session(telegram_user_id: int) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        rec.pop("auth_header", None)
        rec.pop("login_email", None)
        rec.pop("awaiting_login_email", None)
        rec.pop("awaiting_login_password", None)
        raw[key] = rec
        _save_raw(raw)


def clear_company_id(telegram_user_id: int) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        rec.pop("company_id", None)
        rec.pop("awaiting_company_name", None)
        raw[key] = rec
        _save_raw(raw)


def clear_fiscal_year_id(telegram_user_id: int) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        rec.pop("fiscal_year_id", None)
        rec.pop("awaiting_fiscal_year", None)
        raw[key] = rec
        _save_raw(raw)


def is_awaiting_company_name(telegram_user_id: int) -> bool:
    rec = get_record(telegram_user_id)
    return bool(rec.get("awaiting_company_name"))


def set_awaiting_company_name(telegram_user_id: int, waiting: bool) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        if waiting:
            rec["awaiting_company_name"] = True
        else:
            rec.pop("awaiting_company_name", None)
        raw[key] = rec
        _save_raw(raw)


def save_company_id(telegram_user_id: int, company_id: int) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        rec["company_id"] = int(company_id)
        rec.pop("awaiting_company_name", None)
        raw[key] = rec
        _save_raw(raw)


def save_fiscal_year_id(telegram_user_id: int, fiscal_year_id: int) -> None:
    key = str(telegram_user_id)
    with _lock:
        raw = _load_raw()
        rec = dict(raw.get(key) or {})
        rec["fiscal_year_id"] = int(fiscal_year_id)
        rec.pop("awaiting_fiscal_year", None)
        raw[key] = rec
        _save_raw(raw)
