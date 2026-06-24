from __future__ import annotations

from typing import Any
import requests

from config.settings import USERS_API_BASE


def _extract_token(payload: Any) -> str | None:
    if isinstance(payload, str) and payload.strip():
        return payload.strip()

    if isinstance(payload, dict):
        for key in ("token", "access_token", "accessToken", "jwt"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("data", "result", "user", "payload"):
            inner = payload.get(key)
            token = _extract_token(inner)
            if token:
                return token

    if isinstance(payload, list):
        for item in payload:
            token = _extract_token(item)
            if token:
                return token

    return None


def _extract_company_id(payload: Any) -> int | None:
    """
    Best-effort extraction for company id from login payloads.
    Supports common shapes like:
      {"companyId": 15}
      {"company": {"id": 15}}
      {"data": {"user": {"companyId": 15}}}
    """
    if payload is None:
        return None

    if isinstance(payload, dict):
        for key in ("companyId", "company_id", "companyID", "companyid"):
            v = payload.get(key)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass

        company = payload.get("company")
        if isinstance(company, dict):
            for key in ("id", "companyId", "company_id", "Id"):
                v = company.get(key)
                if v is not None:
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        pass

        for key in ("data", "result", "user", "payload"):
            inner = payload.get(key)
            cid = _extract_company_id(inner)
            if cid is not None:
                return cid

    if isinstance(payload, list):
        for item in payload:
            cid = _extract_company_id(item)
            if cid is not None:
                return cid

    return None


def login_user(email: str, password: str) -> tuple[str | None, int | None, str | None]:
    email = (email or "").strip()
    password = (password or "").strip()

    if not email:
        return None, None, "empty_email"
    if not password:
        return None, None, "empty_password"

    try:
        response = requests.post(
            f"{USERS_API_BASE}/users/login",
            json={"email": email, "password": password},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=45,
        )
    except requests.RequestException as exc:
        return None, None, f"network_error:{exc}"

    if response.status_code >= 400:
        return None, None, f"http_{response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        return None, None, "invalid_json"

    token = _extract_token(payload)
    if not token:
        return None, None, "missing_token"

    company_id = _extract_company_id(payload)
    if company_id is None:
        return None, None, "missing_company"

    return f"Bearer {token}", company_id, None
