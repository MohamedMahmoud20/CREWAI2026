"""
Lookup company id by name via GET /api/companies?name=...
"""
from __future__ import annotations

import os
from typing import Any

import requests

COMPANIES_API_BASE = os.getenv("COMPANIES_API_BASE", "http://104.248.246.2/api").rstrip("/")


def _extract_company_id(payload: Any) -> int | None:
    if payload is None:
        return None
    if isinstance(payload, list):
        if not payload or not isinstance(payload[0], dict):
            return None
        row = payload[0]
        for k in ("id", "company_id", "companyId", "Id"):
            v = row.get(k)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    continue
        return None
    if isinstance(payload, dict):
        for k in ("id", "company_id", "companyId"):
            v = payload.get(k)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    continue
        inner = payload.get("data")
        if inner is not None:
            cid = _extract_company_id(inner)
            if cid is not None:
                return cid
    return None


def fetch_company_id_by_name(company_name: str) -> tuple[int | None, str | None]:
    """
    Returns (company_id, error_key_or_message).
    error is None on success; otherwise a short machine-readable tag or message.
    """
    name = (company_name or "").strip()
    if not name:
        return None, "empty_name"

    url = f"{COMPANIES_API_BASE}/companies"
    try:
        resp = requests.get(
            url,
            params={"name": name},
            headers={"Accept": "application/json"},
            timeout=45,
        )
    except requests.RequestException as exc:
        return None, f"network_error:{exc}"

    if resp.status_code >= 400:
        return None, f"http_{resp.status_code}"

    try:
        payload = resp.json()
    except ValueError:
        return None, "invalid_json"

    cid = _extract_company_id(payload)
    if cid is None:
        return None, "company_not_found"
    return cid, None
