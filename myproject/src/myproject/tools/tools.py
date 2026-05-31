# tools.py
import json
import os
import re
import requests
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from arabic_reshaper import reshape
from bidi.algorithm import get_display
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from myproject.runtime_context import (
    get_active_auth_header,
    get_active_company_id,
    get_skip_name_confirmation,
)


def _process_arabic_text(text: str) -> str:
    """Process Arabic text for proper display in PDF."""
    if not text:
        return text
    reshaped = reshape(text)
    bidi_text = get_display(reshaped)
    return bidi_text


class GetClientInput(BaseModel):
    # Backward-compat: older prompts/tools used accounts_name only.
    # New behavior: `query` can match name, mobile, or code on the backend.
    query: str | None = Field(
        None,
        description="Real search text only: client/account name, mobile number, or account code.",
    )
    accounts_name: str | None = Field(
        None,
        description="Deprecated fallback for an account/client name. Prefer `query`.",
    )
    father_id: int | None = Field(None, description="Father account ID (optional)")
    company_id: int | None = Field(None, description="Company ID (optional)")
    is_main: bool | None = Field(None, description="isMain flag (optional)")


class GetClientTool(BaseTool):
    name: str = "get_client"
    description: str = (
        "Search existing accounts/clients only. Do not use for creating clients. "
        "Do not use for items/products/categories/inventory (Arabic: اصناف، منتجات، مخزون). "
        "Action Input must contain real values, never a schema/properties object.\n\n"
        "Use this tool to search for accounts/clients in the system. "
        "The search supports account name, phone number, or account code.\n\n"
        
        "Inputs:\n"
        "- query: string (required) → can be name, mobile number, or account code\n"
        "- company_id: integer (required)\n"
        "- is_main: optional boolean → filter main accounts only\n\n"
        
        "Behavior:\n"
        "- Performs partial matching (LIKE search)\n"
        "- Returns a list of matching accounts\n"
        "- If no matches are found, returns an empty list\n\n"
        
        "Examples:\n"
        "- query='cash' → search by account name\n"
        "- query='010' → search by phone number\n"
        "- query='101' → search by account code\n"
    )
    args_schema: type[BaseModel] = GetClientInput

    def _run(
        self,
        query: str | None = None,
        accounts_name: str | None = None,
        father_id: int | None = None,
        company_id: int | None = None,
        is_main: bool | None = None,
    ) -> str:
        effective_query = _to_str_or_none(query) or _to_str_or_none(accounts_name)
        if not effective_query:
            return json.dumps(
                {
                    "status": "error",
                    "http_status": 400,
                    "error": "Missing search query. Provide `query` (or legacy `accounts_name`).",
                    "data": [],
                },
                ensure_ascii=False,
            )

        # Keep the old Arabic name confirmation behavior, but only when the query looks like a name.
        if not get_skip_name_confirmation() and _ARABIC_NAME_RE.fullmatch(effective_query.strip()):
            spelling_suggestion = _suggest_arabic_name_correction(effective_query)
            if spelling_suggestion and spelling_suggestion != effective_query.strip():
                return json.dumps(
                    {
                        "status": "needs_confirmation",
                        "message": f"هل تقصد '{spelling_suggestion}'؟",
                        "original_accounts_name": effective_query,
                        "suggested_accounts_name": spelling_suggestion,
                    },
                    ensure_ascii=False,
                )

        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid

        try:
            result, api = search_accounts_with_api(
                query=effective_query,
                company_id=effective_company_id,
                tree=False,
                father_id=father_id,
                is_main=is_main,
            )
            # Apply field filtering to the result before returning
            if isinstance(result, list):
                filtered_result = [_filter_accounts_fields(r) for r in result if _filter_accounts_fields(r)]
                # Update the API response data with filtered results
                if isinstance(api, dict) and "data" in api:
                    api["data"] = filtered_result
                return json.dumps(api, ensure_ascii=False)
            else:
                return json.dumps(api, ensure_ascii=False)
        except AccountsSearchError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "http_status": exc.http_status,
                    "error": exc.message,
                    "data": [],
                },
                ensure_ascii=False,
            )


class GetAccountByIdInput(BaseModel):
    account_id: int = Field(..., description="Account ID to fetch, e.g. 153")


class GetAccountByIdTool(BaseTool):
    name: str = "get_account_by_id"
    description: str = (
        "Fetch one existing account/client by exact id from GET /api/accounts/{account_id}. "
        "Use this when the user provides an account id, for example 'account id 153' "
        "or Arabic requests like 'هات الحساب رقم 153'."
    )
    args_schema: type[BaseModel] = GetAccountByIdInput

    def _run(self, account_id: int) -> str:
        return json.dumps(fetch_account_by_id_payload(account_id), ensure_ascii=False)


# Base URL for accounts API
# Can be overridden via env var: ACCOUNTS_API_BASE
ACCOUNTS_API_BASE = os.getenv("ACCOUNTS_API_BASE", "http://104.248.246.2/api").rstrip("/")

_ARABIC_NAME_RE = re.compile(r"^[\u0621-\u064A\s]+$")
_COMMON_ARABIC_SUBSTITUTIONS: dict[str, tuple[str, ...]] = {
    "خ": ("ح",),
    "ح": ("خ",),
    "ض": ("ظ",),
    "ظ": ("ض",),
    "ذ": ("ز", "د"),
    "ز": ("ذ",),
    "د": ("ذ",),
    "ة": ("ه", "ت"),
    "ه": ("ة",),
    "ى": ("ي",),
    "ي": ("ى",),
    "أ": ("ا", "إ"),
    "إ": ("ا", "أ"),
    "آ": ("ا",),
}


def _normalize_arabic_name(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return (
        text.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ؤ", "و")
        .replace("ئ", "ي")
    )


def _suggest_arabic_name_correction(value: str) -> str | None:
    """
    Conservative typo helper for Arabic names.
    Returns a likely correction when the input looks like a common Arabic typo,
    including multi-word names such as: اخمد مجدي -> احمد مجدي.
    """
    raw = (value or "").strip()
    if not raw or not _ARABIC_NAME_RE.fullmatch(raw):
        return None

    normalized = _normalize_arabic_name(raw)
    parts = normalized.split()
    if not parts:
        return None

    corrected_parts: list[str] = []
    changed = False

    for word in parts:
        corrected = _suggest_single_arabic_word(word)
        if corrected and corrected != word:
            corrected_parts.append(corrected)
            changed = True
        else:
            corrected_parts.append(word)

    if changed:
        return " ".join(corrected_parts)
    return None


def _suggest_single_arabic_word(word: str) -> str | None:
    if not word:
        return None

    priority_candidates: list[str] = []
    candidates: set[str] = set()

    if word.startswith("اخم"):
        priority_candidates.append("ا" + word[1:].replace("خ", "ح", 1))

    for idx, char in enumerate(word):
        for replacement in _COMMON_ARABIC_SUBSTITUTIONS.get(char, ()):
            candidate = word[:idx] + replacement + word[idx + 1 :]
            if candidate != word:
                candidates.add(candidate)

    for candidate in priority_candidates:
        if candidate and candidate != word:
            return candidate

    candidates.discard(word)
    if len(candidates) == 1:
        return next(iter(candidates))
    return None

def _accounts_api_headers() -> dict[str, str]:
    """
    Optional auth support to match Postman behavior.
    Set one of these env vars (e.g. in .env):
      - ACCOUNTS_API_BEARER_TOKEN=...   -> Authorization: Bearer <token>
      - ACCOUNTS_API_AUTH_HEADER=...    -> Authorization: <value>
    """
    headers: dict[str, str] = {"Accept": "application/json"}
    runtime_auth = get_active_auth_header()
    if runtime_auth:
        headers["Authorization"] = runtime_auth
        return headers
    bearer = os.getenv("ACCOUNTS_API_BEARER_TOKEN")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
        return headers
    auth = os.getenv("ACCOUNTS_API_AUTH_HEADER")
    if auth:
        headers["Authorization"] = auth
    return headers


def _api_headers(auth_header: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


def _build_get_url(endpoint: str, params: dict[str, object]) -> str:
    return requests.Request("GET", endpoint, params=params).prepare().url or endpoint


def _filter_item_fields(record: dict) -> dict | None:
    if not isinstance(record, dict):
        return None

    out: dict[str, object] = {}
    field_map = {
        "Items_id": "Items_id",
        "Items_is_main": "Items_is_main",
        "Items_name_ar": "Items_name_ar",
        "Items_name_en": "Items_name_en",
        "Items_Discount": "Items_Discount",
        "Items_MinimumQty": "Items_MinimumQty",
        "Items_sell_price": "Items_sell_price",
    }
    for source, target in field_map.items():
        if source in record:
            out[target] = record[source]
    return out if out else None


def _filter_items_list(data: object) -> list[dict]:
    records: list[dict] = []
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        for key in ("data", "items", "results", "records"):
            if isinstance(data.get(key), list):
                records = data[key]
                break

    result = []
    for record in records:
        filtered = _filter_item_fields(record)
        if filtered:
            result.append(filtered)
    return result


def _filter_unit_fields(record: dict) -> dict | None:
    if not isinstance(record, dict):
        return None

    out: dict[str, object] = {}
    field_map = {
        "Stock_Units_id": "Stock_Units_id",
        "Stock_Units_desc": "Stock_Units_desc",
        "status": "status",
        "companyId": "companyId",
    }
    for source, target in field_map.items():
        if source in record:
            out[target] = record[source]
    return out if out else None


def _filter_units_list(data: object) -> list[dict]:
    records: list[dict] = []
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        for key in ("data", "units", "items", "results", "records"):
            if isinstance(data.get(key), list):
                records = data[key]
                break
        if not records and "Stock_Units_id" in data:
            records = [data]

    result = []
    for record in records:
        filtered = _filter_unit_fields(record)
        if filtered:
            result.append(filtered)
    return result


def fetch_units_payload(
    company_id: int | None,
    query: str | None = None,
    auth_header: str | None = None,
) -> dict[str, object]:
    if company_id is None:
        return {"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}

    try:
        response = requests.get(
            f"{ACCOUNTS_API_BASE}/units",
            params={"companyId": company_id},
            headers=_api_headers(auth_header) if auth_header else _accounts_api_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "http_status": None,
            "error": f"Units API request failed: {exc}",
            "data": [],
        }

    try:
        raw_data = response.json()
    except Exception:
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "Invalid JSON response",
            "data": [],
        }

    if not (200 <= response.status_code < 300):
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "API request failed",
            "data": raw_data,
        }

    units = _filter_units_list(raw_data)
    q = _to_str_or_none(query)
    if q:
        needle = q.casefold()
        units = [
            unit
            for unit in units
            if needle in str(unit.get("Stock_Units_desc", "")).casefold()
            or needle in str(unit.get("Stock_Units_id", "")).casefold()
        ]

    return {"status": "success", "http_status": response.status_code, "data": units}


def _filter_item_desc_fields(record: dict) -> dict | None:
    if not isinstance(record, dict):
        return None

    out: dict[str, object] = {}
    field_map = {
        "Stock_ItemDesc_id": "Stock_ItemDesc_id",
        "Stock_ItemDesc_title": "Stock_ItemDesc_title",
        "status": "status",
        "companyId": "companyId",
    }
    for source, target in field_map.items():
        if source in record:
            out[target] = record[source]
    return out if out else None


def _filter_item_desc_list(data: object) -> list[dict]:
    records: list[dict] = []
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        for key in ("data", "items", "results", "records"):
            if isinstance(data.get(key), list):
                records = data[key]
                break
        if not records and "Stock_ItemDesc_id" in data:
            records = [data]

    result = []
    for record in records:
        filtered = _filter_item_desc_fields(record)
        if filtered:
            result.append(filtered)
    return result


def fetch_item_desc_payload(
    company_id: int | None,
    query: str | None = None,
    auth_header: str | None = None,
) -> dict[str, object]:
    if company_id is None:
        return {"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}

    try:
        response = requests.get(
            f"{ACCOUNTS_API_BASE}/Stock_ItemDesc",
            params={"companyId": company_id},
            headers=_api_headers(auth_header) if auth_header else _accounts_api_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "http_status": None,
            "error": f"Item descriptions API request failed: {exc}",
            "data": [],
        }

    try:
        raw_data = response.json()
    except Exception:
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "Invalid JSON response",
            "data": [],
        }

    if not (200 <= response.status_code < 300):
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "API request failed",
            "data": raw_data,
        }

    item_desc = _filter_item_desc_list(raw_data)
    q = _to_str_or_none(query)
    if q:
        needle = q.casefold()
        item_desc = [
            item
            for item in item_desc
            if needle in str(item.get("Stock_ItemDesc_title", "")).casefold()
            or needle in str(item.get("Stock_ItemDesc_id", "")).casefold()
        ]

    return {"status": "success", "http_status": response.status_code, "data": item_desc}


def fetch_supplier_cards_payload(
    company_id: int | None,
    auth_header: str | None = None,
) -> dict[str, object]:
    if company_id is None:
        return {"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}

    try:
        response = requests.get(
            f"{ACCOUNTS_API_BASE}/accounts/father/1",
            params={"isMain": "false", "campanyId": company_id},
            headers=_api_headers(auth_header) if auth_header else _accounts_api_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "http_status": None,
            "error": f"Supplier cards API request failed: {exc}",
            "data": [],
        }

    try:
        raw_data = response.json()
    except Exception:
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "Invalid JSON response",
            "data": [],
        }

    if not (200 <= response.status_code < 300):
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "API request failed",
            "data": raw_data,
        }

    return {"status": "success", "http_status": response.status_code, "data": _filter_accounts_list(raw_data)}


def fetch_account_by_id_payload(
    account_id: int | str,
    auth_header: str | None = None,
) -> dict[str, object]:
    account_id_int = _to_int_or_none(account_id)
    if account_id_int is None:
        return {"status": "error", "http_status": 400, "error": "Invalid account_id", "data": None}

    try:
        response = requests.get(
            f"{ACCOUNTS_API_BASE}/accounts/{account_id_int}",
            headers=_api_headers(auth_header) if auth_header else _accounts_api_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "http_status": None,
            "error": f"Account API request failed: {exc}",
            "data": None,
        }

    try:
        raw_data = response.json()
    except Exception:
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "Invalid JSON response",
            "data": None,
        }

    if not (200 <= response.status_code < 300):
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "API request failed",
            "data": raw_data,
        }

    records = _extract_account_list(raw_data)
    if records:
        filtered = _filter_accounts_fields(records[0])
        data: object = filtered if filtered else records[0]
        if isinstance(data, dict) and data.get("id") is None:
            data = {"id": str(account_id_int), **data}
    else:
        data = raw_data

    return {"status": "success", "http_status": response.status_code, "data": data}


def _extract_list_payload(payload: object, keys: tuple[str, ...] = ("data", "items", "results", "records")) -> object:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            nested = payload.get(key)
            if isinstance(nested, list):
                return nested
    return payload


def fetch_invoice_books_payload(
    company_id: int | None,
    book_type: str = "all",
    auth_header: str | None = None,
) -> dict[str, object]:
    if company_id is None:
        return {"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}

    normalized_type = (book_type or "").strip().casefold()
    if normalized_type in {"", "all", "any", "كل", "الكل", "دفاتر", "كل الدفاتر"}:
        inv_type = None
    elif normalized_type in {"sales", "sale", "مبيعات", "دفاتر المبيعات"}:
        inv_type = "-"
    elif normalized_type in {"purchases", "purchase", "buy", "مشتريات", "دفاتر المشتريات"}:
        inv_type = "true"
    else:
        return {
            "status": "error",
            "http_status": 400,
            "error": "Invalid book_type. Use 'all', 'sales', or 'purchases'.",
            "data": [],
        }

    try:
        params: dict[str, object] = {"companyId": company_id}
        if inv_type is not None:
            params["InvType_Type"] = inv_type

        response = requests.get(
            f"{ACCOUNTS_API_BASE}/InvType",
            params=params,
            headers=_api_headers(auth_header) if auth_header else _accounts_api_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "http_status": None,
            "error": f"Invoice books API request failed: {exc}",
            "data": [],
        }

    try:
        raw_data = response.json()
    except Exception:
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "Invalid JSON response",
            "data": [],
        }

    if not (200 <= response.status_code < 300):
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "API request failed",
            "data": raw_data,
        }

    return {
        "status": "success",
        "http_status": response.status_code,
        "book_type": "all" if inv_type is None else "sales" if inv_type == "-" else "purchases",
        "data": _extract_list_payload(raw_data),
    }


def _pick_account_search_record(query: str, company_id: int | None, auth_header: str | None = None) -> dict | None:
    name_payload = fetch_account_by_name_payload(company_id=company_id, account_name=query, auth_header=auth_header)
    name_records = _extract_account_list(name_payload.get("data") if isinstance(name_payload, dict) else name_payload)
    if name_records:
        return name_records[0]

    result, api = search_accounts_with_api(query=query, company_id=company_id, tree=False)
    raw_records = _extract_account_list(api)
    filtered_raw = _locally_filter_accounts(raw_records, query)
    if filtered_raw:
        return filtered_raw[0]
    if raw_records:
        return raw_records[0]
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    return None


def fetch_account_by_name_payload(
    company_id: int | None,
    account_name: str,
    auth_header: str | None = None,
) -> dict[str, object]:
    if company_id is None:
        return {"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}

    name = _to_str_or_none(account_name)
    if not name:
        return {"status": "error", "http_status": 400, "error": "Missing account_name", "data": []}

    try:
        response = requests.get(
            f"{ACCOUNTS_API_BASE}/accounts",
            params={"accounts_name": name, "companyId": company_id},
            headers=_api_headers(auth_header) if auth_header else _accounts_api_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "http_status": None,
            "error": f"Account name search API request failed: {exc}",
            "data": [],
        }

    try:
        raw_data = response.json()
    except Exception:
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "Invalid JSON response",
            "data": [],
        }

    if not (200 <= response.status_code < 300):
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "API request failed",
            "data": raw_data,
        }

    records = _extract_account_list(raw_data)
    records = _locally_filter_accounts(records, name) if records else []
    filtered = [_filter_accounts_fields(record) for record in records]
    return {
        "status": "success",
        "http_status": response.status_code,
        "data": [record for record in filtered if record],
    }


def _filter_account_sheet_account(record: dict) -> dict:
    if not isinstance(record, dict):
        return {}

    fields = (
        "id",
        "accounts_id",
        "accounts_name",
        "accounts_code",
        "accounts_ismain",
    )
    return {field: record[field] for field in fields if field in record}


def _filter_account_sheet_detail_row(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None

    row_type = row.get("rowType")
    if row_type == "opening":
        fields = ("rowType", "openingBalance", "Accounts_Id", "fromDate")
    elif row_type == "summary":
        fields = ("rowType", "M", "D", "Sum", "showOpeningBalance")
    else:
        fields = (
            "serial_number",
            "Account_Sheet_id",
            "Account_Sheet_Details_M",
            "Account_Sheet_Details_D",
            "Accounts_Id",
            "Account_Sheet_Details_date",
            "Account_Sheet_Details_id",
            "Bransh_id",
            "Account_Sheet_IsTrans",
            "last_balance",
            "createdAt",
            "updatedAt",
        )

    filtered = {field: row[field] for field in fields if field in row}
    return filtered if filtered else None


def _filter_account_sheet_details_payload(payload: object) -> object:
    rows = _extract_list_payload(payload)
    if isinstance(rows, list):
        return [
            filtered
            for row in rows
            if isinstance(row, dict)
            for filtered in (_filter_account_sheet_detail_row(row),)
            if filtered
        ]
    if isinstance(rows, dict):
        return _filter_account_sheet_detail_row(rows) or rows
    return rows


def _to_float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _amount_equals(left, right) -> bool:
    left_num = _to_float_or_none(left)
    right_num = _to_float_or_none(right)
    if left_num is None or right_num is None:
        return False
    return abs(left_num - right_num) < 0.000001


def _filter_account_sheet_amounts(
    rows: object,
    debit_amount: float | int | str | None = None,
    credit_amount: float | int | str | None = None,
) -> object:
    debit_filter = _to_float_or_none(debit_amount)
    credit_filter = _to_float_or_none(credit_amount)
    if debit_filter is None and credit_filter is None:
        return rows
    if not isinstance(rows, list):
        return rows

    filtered_rows = []
    for row in rows:
        if not isinstance(row, dict) or row.get("rowType") in {"opening", "summary"}:
            continue
        if debit_filter is not None and not _amount_equals(row.get("Account_Sheet_Details_M"), debit_filter):
            continue
        if credit_filter is not None and not _amount_equals(row.get("Account_Sheet_Details_D"), credit_filter):
            continue
        filtered_rows.append(row)
    return filtered_rows


def fetch_account_sheet_details_payload(
    company_id: int | None,
    account_name: str,
    auth_header: str | None = None,
    order_by_date: bool = True,
    show_unposted_entries: bool = False,
    show_opening_balance: bool = True,
    not_show_zero_transiation: bool = True,
    debit_amount: float | int | str | None = None,
    credit_amount: float | int | str | None = None,
) -> dict[str, object]:
    if company_id is None:
        return {"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}

    query = _to_str_or_none(account_name)
    if not query:
        return {"status": "error", "http_status": 400, "error": "Missing account_name", "data": []}

    try:
        account = _pick_account_search_record(query=query, company_id=company_id, auth_header=auth_header)
    except AccountsSearchError as exc:
        return {"status": "error", "http_status": exc.http_status, "error": exc.message, "data": []}

    if not account:
        return {
            "status": "error",
            "http_status": 404,
            "error": "Account not found",
            "account_name": query,
            "data": [],
        }

    accounts_id = _first_key(account, "accounts_id", "account_id", "id")
    if accounts_id is None:
        return {
            "status": "error",
            "http_status": 400,
            "error": "Matched account has no accounts_id",
            "account": account,
            "data": [],
        }

    params: dict[str, object] = {
        "companyId": company_id,
        "orderByDate": "true" if order_by_date else "false",
        "showUnpostedEntries": "true" if show_unposted_entries else "false",
        "showOpeningBalance": "true" if show_opening_balance else "false",
        "notShowZeroTransiation": "true" if not_show_zero_transiation else "false",
        "Accounts_Id": accounts_id,
    }
    endpoint = f"{ACCOUNTS_API_BASE}/accountsSheetDetails"
    endpoint_url = _build_get_url(endpoint, params)
    account_lookup_endpoint = _build_get_url(
        f"{ACCOUNTS_API_BASE}/accounts",
        {"accounts_name": query, "companyId": company_id},
    )

    try:
        response = requests.get(
            endpoint,
            params=params,
            headers=_api_headers(auth_header) if auth_header else _accounts_api_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "http_status": None,
            "error": f"Account sheet details API request failed: {exc}",
            "account_lookup_endpoint": account_lookup_endpoint,
            "endpoint": endpoint_url,
            "account": _filter_accounts_fields(account) or account,
            "data": [],
        }

    try:
        raw_data = response.json()
    except Exception:
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "Invalid JSON response",
            "account_lookup_endpoint": account_lookup_endpoint,
            "endpoint": endpoint_url,
            "account": _filter_accounts_fields(account) or account,
            "data": [],
        }

    if not (200 <= response.status_code < 300):
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "API request failed",
            "account_lookup_endpoint": account_lookup_endpoint,
            "endpoint": response.url or endpoint_url,
            "account": _filter_accounts_fields(account) or account,
            "data": raw_data,
        }

    filtered_data = _filter_account_sheet_details_payload(raw_data)
    filtered_data = _filter_account_sheet_amounts(
        filtered_data,
        debit_amount=debit_amount,
        credit_amount=credit_amount,
    )
    amount_filters: dict[str, object] = {}
    if _to_float_or_none(debit_amount) is not None:
        amount_filters["Account_Sheet_Details_M"] = _to_float_or_none(debit_amount)
    if _to_float_or_none(credit_amount) is not None:
        amount_filters["Account_Sheet_Details_D"] = _to_float_or_none(credit_amount)

    result = {
        "status": "success",
        "http_status": response.status_code,
        "account_lookup_endpoint": account_lookup_endpoint,
        "endpoint": response.url or endpoint_url,
        "account": _filter_account_sheet_account(_filter_accounts_fields(account) or account),
        "data": filtered_data,
    }
    if amount_filters:
        result["filters"] = amount_filters
    return result


def fetch_items_payload(
    company_id: int | None,
    query: str | None = None,
    is_main: bool | None = None,
    auth_header: str | None = None,
    main_fathers: bool = False,
) -> dict[str, object]:
    if company_id is None:
        return {"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}

    endpoint = f"{ACCOUNTS_API_BASE}/items/getMain/fathers" if main_fathers else f"{ACCOUNTS_API_BASE}/items"

    try:
        params: dict[str, object] = {"companyId": company_id}
        if is_main is not None and not main_fathers:
            params["Items_is_main"] = "true" if is_main else "false"

        response = requests.get(
            endpoint,
            params=params,
            headers=_api_headers(auth_header) if auth_header else _accounts_api_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "http_status": None,
            "error": f"Items API request failed: {exc}",
            "data": [],
        }
    try:
        raw_data = response.json()
    except Exception:
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "Invalid JSON response",
            "data": [],
        }

    if not (200 <= response.status_code < 300):
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": "API request failed",
            "data": raw_data,
        }

    items = _filter_items_list(raw_data)
    if is_main is not None:
        items = [item for item in items if item.get("Items_is_main") is is_main]

    q = _to_str_or_none(query)
    if q:
        needle = q.casefold()
        search_fields = ("Items_code", "Items_name_ar", "Items_name_en", "Items_desc")
        items = [
            item
            for item in items
            if any(needle in str(item.get(field, "")).casefold() for field in search_fields)
        ]

    return {"status": "success", "http_status": response.status_code, "data": items}


def _to_int_or_none(value) -> int | None:
    """Convert to int for bigint API fields; use None instead of \"\" to avoid invalid input syntax."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _to_str_or_none(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _safe_json(value: str):
    try:
        return json.loads(value)
    except Exception:
        return value


def _first_key(record: dict, *keys: str):
    for k in keys:
        if k not in record:
            continue
        v = record[k]
        if v is None or v == "":
            continue
        return v
    return None


def _pick_get_client_fields(record: dict) -> dict:
    """
    For get_client responses: extract only the required fields.
    - accounts_id
    - accounts_name
    - companyId
    - accounts_mobile
    - accounts_code
    - accounts_ismain
    - accounts_issandouk
    """
    account_id = _first_key(record, "accounts_id", "id", "account_id")
    name = _first_key(record, "accounts_name", "name", "client_name")
    comp = _first_key(record, "companyId", "company_id", "companyid")
    mobile = _first_key(record, "accounts_mobile", "accounts_clientmobile2", "accounts_clientmobile3", "mobile")
    code = _first_key(record, "accounts_code", "code", "account_code")
    ismain = _first_key(record, "accounts_ismain", "is_main", "ismain")
    issandouk = _first_key(record, "accounts_issandouk", "is_sandouk", "issandouk")

    out: dict[str, object] = {}
    if account_id is not None:
        out["accounts_id"] = account_id
    if name is not None:
        out["accounts_name"] = name
    if comp is not None:
        out["companyId"] = comp
    if mobile is not None:
        out["accounts_mobile"] = mobile
    if code is not None:
        out["accounts_code"] = code
    if ismain is not None:
        out["accounts_ismain"] = ismain
    if issandouk is not None:
        out["accounts_issandouk"] = issandouk

    return out


def _filter_get_client_payload(parsed: object) -> object:
    """Reduce API JSON to slim client records only (no extra pagination/metadata fields)."""
    if isinstance(parsed, list):
        return [_pick_get_client_fields(x) for x in parsed if isinstance(x, dict)]
    if isinstance(parsed, dict):
        for nest in ("data", "items", "results", "accounts", "records"):
            if nest in parsed and isinstance(parsed[nest], list):
                return [_pick_get_client_fields(x) for x in parsed[nest] if isinstance(x, dict)]
        return _pick_get_client_fields(parsed)
    return parsed


class CreateClientInput(BaseModel):
    accounts_name: str = Field(..., description="Required real name of the new client/account to create.")
    accounts_code: str | None = Field(None, description="Account code (auto if omitted)")
    accounts_mobile: str | None = Field(None, description="Client mobile number")
    accounts_fatherid: str | None = Field(None, description="Parent account ID (auto if omitted)")
    main_account_name: str | None = Field(
        None,
        description=(
            "Main account name to resolve accounts_fatherid from "
            "/api/accounts?isMain=true&companyId=...&accounts_name=..."
        ),
    )
    accounts_ismain: bool = Field(False, description="Is main account")
    accounts_issandouk: bool = Field(False, description="Is sandouk account")
    accounts_isfinalacount: bool = Field(False, description="Is final account")
    accounts_isdistributor: bool = Field(False, description="Is distributor")
    accounts_iscloseinaccount: str | None = Field(
        None, description="Close-in account id/flag (API returns string or null)"
    )
    company_id: int = Field(15, description="Company ID (default 15)")


class CreateClientTool(BaseTool):
    name: str = "create_client"
    description: str = (
        "Create/register a new client/account at POST /api/accounts.\n\n"
        "Use only when the user explicitly asks to create, add, register, or save a new "
        "client/account and provides the new client/account name. Arabic trigger examples: "
        "'سجل عميل', 'ضيف عميل', 'انشاء حساب'.\n\n"
        "Do not use for search requests. Do not use for items/products/categories/inventory "
        "(Arabic: اصناف، منتجات، مخزون). A request like 'عايز الاصناف' is unsupported by "
        "this client/account toolset.\n\n"
        "Action Input must contain real values such as accounts_name, accounts_mobile, "
        "main_account_name or accounts_fatherid, and company_id. Never pass the tool schema, "
        "properties, title, type, additionalProperties, or required list as input."
    )
    args_schema: type[BaseModel] = CreateClientInput

    def _run(
        self,
        accounts_name: str,
        accounts_code: str | None = None,
        accounts_mobile: str | None = None,
        accounts_fatherid: str | None = None,
        main_account_name: str | None = None,
        accounts_ismain: bool = False,
        accounts_issandouk: bool = False,
        accounts_isfinalacount: bool = False,
        accounts_isdistributor: bool = False,
        accounts_iscloseinaccount: str | None = None,
        company_id: int = 15,
    ) -> str:
        ctx_cid = get_active_company_id()
        if ctx_cid is not None:
            company_id = ctx_cid
        summary: dict[str, object] = {
            "status": "error",
            "error": None,
            "registration_payload": None,
            "api": {},
        }
        # ─── الخطوة 1: جلب الحساب الرئيسي (إجباري) واستخراج accounts_fatherid ───
        resolved_father_id: str | None = None
        if _to_str_or_none(accounts_fatherid):
            resolved_father_id = str(accounts_fatherid).strip()
        elif _to_str_or_none(main_account_name):
            endpoint = f"{ACCOUNTS_API_BASE}/accounts"
            params = {
                "isMain": "true",
                "companyId": company_id,
                "accounts_name": main_account_name.strip(),
            }
            resp = requests.get(
                f"{ACCOUNTS_API_BASE}/accounts",
                params=params,
                headers=_accounts_api_headers(),
            )
            try:
                data = resp.json()
            except Exception:
                summary["error"] = "فشل قراءة رد Endpoint الحساب الرئيسي."
                summary["api"] = {"main_account_lookup": {"endpoint": endpoint, "params": params, "response": resp.text}}
                return json.dumps(summary, ensure_ascii=False)
            summary["api"] = {"main_account_lookup": {"endpoint": endpoint, "params": params, "response": data}}
            if isinstance(data, list) and data and isinstance(data[0], dict):
                first = data[0]
                aid = first.get("accounts_id") or first.get("id")
                if aid is not None:
                    resolved_father_id = str(aid).strip()

        if not resolved_father_id:
            summary["error"] = (
                "اسم الحساب الرئيسي مطلوب. أرسل main_account_name (مثل: المصروفات العمومية) "
                "لجلب الحساب الرئيسي واستخدامه في التسجيل، أو أرسل accounts_fatherid مباشرة."
            )
            return json.dumps(summary, ensure_ascii=False)

        # ─── الخطوة 2: جلب كود جديد للحساب (accounts_code) ───
        resolved_code: str | None = _to_str_or_none(accounts_code)
        if not resolved_code:
            # API source of truth:
            # GET /api/accounts/get_code/{fatherId}?companyId=...
            endpoint = f"{ACCOUNTS_API_BASE}/accounts/get_code/{resolved_father_id}"
            params = {"companyId": company_id}
            resp = requests.get(endpoint, params=params, headers=_accounts_api_headers())
            try:
                data = resp.json()
            except Exception:
                summary["error"] = "فشل قراءة رد Endpoint كود الحساب."
                summary["api"] = {
                    **(summary.get("api") or {}),
                    "code_lookup": {"endpoint": endpoint, "params": params, "response": resp.text},
                }
                return json.dumps(summary, ensure_ascii=False)
            summary["api"] = {
                **(summary.get("api") or {}),
                "code_lookup": {"endpoint": endpoint, "params": params, "response": data},
            }
            if isinstance(data, dict) and data.get("newCode") is not None:
                resolved_code = str(data.get("newCode", "")).strip() or None

        if not resolved_code:
            summary["error"] = "تعذر الحصول على كود حساب جديد من الـ API."
            return json.dumps(summary, ensure_ascii=False)

        # ─── الخطوة 3: بناء بيانات الإضافة وإرسال POST ───
        payload = {
            "accounts_ismain": accounts_ismain,
            "accounts_code": resolved_code,
            "accounts_name": accounts_name.strip(),
            "accounts_mobile": (accounts_mobile or "").strip() if accounts_mobile else "",
            "accounts_fatherid": resolved_father_id,
            "accounts_issandouk": accounts_issandouk,
            "accounts_isfinalacount": accounts_isfinalacount,
            "accounts_isdistributor": accounts_isdistributor,
            "companyId": company_id,
            "accounts_iscloseinaccount": _to_str_or_none(accounts_iscloseinaccount),
        }
        create_endpoint = f"{ACCOUNTS_API_BASE}/accounts"
        response = requests.post(create_endpoint, json=payload, headers=_accounts_api_headers())
        summary["registration_payload"] = payload
        summary["api"] = {
            **(summary.get("api") or {}),
            "create_account": {
                "endpoint": create_endpoint,
                "method": "POST",
                "response": _safe_json(response.text),
                "http_status": response.status_code,
            },
        }
        if 200 <= response.status_code < 300:
            # On success: return full client data from create API response
            return json.dumps(
                {
                    "status": "success",
                    "http_status": response.status_code,
                    "data": _safe_json(response.text),
                },
                ensure_ascii=False,
            )
        else:
            # Return ONLY the create_account block on POST failure (as requested).
            return json.dumps(
                {"payload": payload, "create_account": summary["api"]["create_account"]},
                ensure_ascii=False,
            )
        return json.dumps({"payload": payload}, ensure_ascii=False)


class SearchMainAccountInput(BaseModel):
    company_id: int = Field(..., description="Company ID (e.g. 15)")
    accounts_name: str = Field(..., description="Main account name to search for")


class SearchMainAccountTool(BaseTool):
    name: str = "search_main_account"
    description: str = (
        "Search main accounts by name (requires accounts_name). "
        "GET /api/accounts?isMain=true&companyId=...&accounts_name=..."
    )
    args_schema: type[BaseModel] = SearchMainAccountInput

    def _run(self, company_id: int, accounts_name: str) -> str:
        name = _to_str_or_none(accounts_name)
        if not name:
            return json.dumps({"status": "error", "http_status": 400, "error": "accounts_name is required", "data": []}, ensure_ascii=False)
        params: dict[str, object] = {"isMain": "true", "companyId": company_id, "accounts_name": name}
        response = requests.get(
            f"{ACCOUNTS_API_BASE}/accounts",
            params=params,
            headers=_accounts_api_headers(),
        )
        return response.text


class SearchAccountsUnderFatherInput(BaseModel):
    father_id: int = Field(..., description="accounts_fatherid / parent account id (e.g. 883)")
    company_id: int = Field(..., description="Company ID (e.g. 15)")
    query: str | None = Field(
        None,
        description="Search query under this father: can match accounts_name, accounts_mobile, or accounts_code",
    )
    accounts_name: str | None = Field(
        None,
        description="(Deprecated) Account name to search for under this father. Use `query` instead.",
    )


class SearchAccountsUnderFatherTool(BaseTool):
    name: str = "search_accounts_under_father"
    description: str = (
        "Search accounts under a father id by query (name OR mobile OR code). "
        "GET /api/accounts/father/{father}?isMain=false&companyId=...&query=..."
    )
    args_schema: type[BaseModel] = SearchAccountsUnderFatherInput

    def _run(
        self,
        father_id: int,
        company_id: int,
        query: str | None = None,
        accounts_name: str | None = None,
    ) -> str:
        effective_query = _to_str_or_none(query) or _to_str_or_none(accounts_name)
        try:
            result = search_accounts(
                query=effective_query,
                company_id=company_id,
                tree=False,
                father_id=father_id,
                is_main=False,
            )
            return json.dumps(result, ensure_ascii=False)
        except AccountsSearchError as exc:
            return json.dumps({"status": "error", "http_status": exc.http_status, "error": exc.message, "data": []}, ensure_ascii=False)


class AccountsSearchError(Exception):
    def __init__(self, message: str, http_status: int = 400):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


def _normalize_account_record(record: dict) -> dict[str, object]:
    """
    Normalize account records returned by the backend to a stable, pythonic shape.
    Keeps only the fields the assistant needs.
    """
    out: dict[str, object] = {}
    _id = _first_key(record, "accounts_id", "id", "account_id")
    if _id is not None:
        out["id"] = _id

    name = _first_key(record, "accounts_name", "name")
    if name is not None:
        out["name"] = name

    code = _first_key(record, "accounts_code", "code")
    if code is not None:
        out["code"] = code

    mobile = _first_key(record, "accounts_mobile", "mobile")
    if mobile is not None:
        out["mobile"] = mobile

    father_id = _first_key(record, "accounts_fatherid", "father_id", "fatherId")
    if father_id is not None:
        out["father_id"] = father_id

    is_main = _first_key(record, "accounts_ismain", "is_main", "isMain")
    if is_main is not None:
        out["is_main"] = is_main

    has_child = _first_key(record, "has_child", "hasChild")
    if has_child is not None:
        out["has_child"] = has_child

    return out


def _extract_account_list(payload: object) -> list[dict]:
    """Accepts list or common {data:[...]} shapes and returns list[dict]."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for nest in ("data", "items", "results", "accounts", "records"):
            nested = payload.get(nest)
            if isinstance(nested, list):
                return [x for x in nested if isinstance(x, dict)]
        # single record case
        return [payload]
    return []


def _locally_filter_accounts(records: list[dict[str, object]], q: str) -> list[dict[str, object]]:
    """
    Safety net: some backend deployments ignore search params and return a full listing.
    To avoid returning "all names", we filter locally by substring match on name/mobile/code.
    More strict filtering: only return records where at least one field actually matches.
    """
    needle = (q or "").strip()
    if not needle:
        return []
    needle_cf = needle.casefold()

    def _matches(rec: dict[str, object]) -> bool:
        # Check all possible field name variations
        mobile_fields = ("accounts_mobile", "accounts_clientmobile2", "accounts_clientmobile3", "mobile")
        code_fields = ("accounts_code", "code")
        name_fields = ("accounts_name", "name", "accounts_contactperson_name")
        
        # Search in mobile fields first (prioritize mobile if query looks like a phone number)
        if any(c.isdigit() for c in needle) and len(needle) >= 7:
            # Query looks like a phone number
            for key in mobile_fields:
                v = rec.get(key)
                if v is None:
                    continue
                s = str(v).strip()
                if s and needle_cf in s.casefold():
                    return True
            # If no mobile match found and query is numeric, check code field
            if needle.isdigit():
                for key in code_fields:
                    v = rec.get(key)
                    if v is None:
                        continue
                    s = str(v).strip()
                    if s and needle_cf == s.casefold():  # Exact match for code
                        return True
            return False
        else:
            # Query is not numeric, search in name field
            for key in name_fields:
                v = rec.get(key)
                if v is None:
                    continue
                s = str(v).strip()
                if s and needle_cf in s.casefold():
                    return True
            return False

    return [r for r in records if isinstance(r, dict) and _matches(r)]


def _maybe_retry_without_query_param(resp_status: int, resp_text: str) -> bool:
    """
    If the backend doesn't support `query`, it may return 400 with a validation message.
    In that case we retry with legacy `accounts_name` to preserve backward compatibility.
    """
    if resp_status != 400:
        return False
    msg = (resp_text or "").lower()
    return ("query" in msg and ("unknown" in msg or "not allowed" in msg or "invalid" in msg))


def search_accounts(
    query: str | None,
    company_id: int | None,
    tree: bool = False,
    father_id: int | None = None,
    is_main: bool | None = None,
) -> list[dict[str, object]]:
    """
    Shared account search helper used by tools and flows.
    - Requires company_id.
    - Accepts a generic query (name/mobile/code) and forwards it to the backend.
    - Returns [] when there are no results (no exceptions for empty results).
    """
    q = _to_str_or_none(query)
    if company_id is None:
        raise AccountsSearchError("Missing company_id", http_status=400)
    if not q:
        # Treat empty/blank as "no query": preserve old behavior by returning [] here
        # (tools that want full listing can call backend directly with no query).
        return []

    endpoint = f"{ACCOUNTS_API_BASE}/accounts"

    base_params: dict[str, object] = {"companyId": company_id}
    if father_id is not None:
        base_params["accounts_fatherid"] = father_id
    if is_main is not None:
        base_params["isMain"] = "true" if is_main else "false"

    def _fetch(params: dict[str, object]) -> tuple[int, object, str]:
        resp = requests.get(endpoint, params=params, headers=_accounts_api_headers())
        return resp.status_code, _safe_json(resp.text), resp.text

    # Prefer the flexible backend search param `query` first.
    # Some deployments ignore `accounts_name` and return a full list → leads to "all names" being returned.
    status_q, raw_q, raw_q_text = _fetch({**base_params, "query": q})
    if status_q == 404:
        return []
    if 200 <= status_q < 300:
        records_q = _extract_account_list(raw_q)
        normalized_q = [_normalize_account_record(r) for r in records_q]
        out_q = [x for x in normalized_q if x]
        out_q = _locally_filter_accounts(out_q, q)
        if out_q:
            return out_q
        # If query-search returns an empty list, fall back to legacy param as a second chance.
    else:
        # If backend rejects `query`, retry with legacy `accounts_name`.
        if not _maybe_retry_without_query_param(status_q, raw_q_text):
            raise AccountsSearchError(f"Backend search failed (HTTP {status_q})", http_status=status_q)

    # Legacy backend behavior: search by `accounts_name`.
    status_n, raw_n, _raw_n_text = _fetch({**base_params, "accounts_name": q})
    if status_n == 404:
        return []
    if not (200 <= status_n < 300):
        raise AccountsSearchError(f"Backend search failed (HTTP {status_n})", http_status=status_n)

    records_n = _extract_account_list(raw_n)
    normalized_n = [_normalize_account_record(r) for r in records_n]
    out_n = [x for x in normalized_n if x]
    return _locally_filter_accounts(out_n, q)


def search_accounts_with_api(
    query: str | None,
    company_id: int | None,
    tree: bool = False,
    father_id: int | None = None,
    is_main: bool | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """
    Search accounts and return both processed data and raw API response.
    Returns (processed_records, raw_api_response)
    """
    q = _to_str_or_none(query)
    if company_id is None:
        raise AccountsSearchError("Missing company_id", http_status=400)
    if not q:
        return [], {"status": "success", "http_status": 200, "data": []}

    endpoint = f"{ACCOUNTS_API_BASE}/accounts"

    base_params: dict[str, object] = {"companyId": company_id}
    if father_id is not None:
        base_params["accounts_fatherid"] = father_id
    if is_main is not None:
        base_params["isMain"] = "true" if is_main else "false"

    def _fetch(params: dict[str, object]) -> tuple[int, object, str]:
        resp = requests.get(endpoint, params=params, headers=_accounts_api_headers())
        return resp.status_code, _safe_json(resp.text), resp.text

    # Prefer the flexible backend search param `query` first.
    status_q, raw_q, raw_q_text = _fetch({**base_params, "query": q})
    if status_q == 404:
        return [], {"status": "success", "http_status": 404, "data": []}
    if 200 <= status_q < 300:
        records_q = _extract_account_list(raw_q)
        normalized_q = [_normalize_account_record(r) for r in records_q]
        out_q = [x for x in normalized_q if x]
        out_q = _locally_filter_accounts(out_q, q)
        if out_q:
            return out_q, raw_q if isinstance(raw_q, dict) else {"status": "success", "http_status": status_q, "data": records_q}
        # If query-search returns an empty list, fall back to legacy param as a second chance.
    else:
        # If backend rejects `query`, retry with legacy `accounts_name`.
        if not _maybe_retry_without_query_param(status_q, raw_q_text):
            raise AccountsSearchError(f"Backend search failed (HTTP {status_q})", http_status=status_q)

    # Legacy backend behavior: search by `accounts_name`.
    status_n, raw_n, _raw_n_text = _fetch({**base_params, "accounts_name": q})
    if status_n == 404:
        return [], {"status": "success", "http_status": 404, "data": []}
    if not (200 <= status_n < 300):
        raise AccountsSearchError(f"Backend search failed (HTTP {status_n})", http_status=status_n)

    records_n = _extract_account_list(raw_n)
    normalized_n = [_normalize_account_record(r) for r in records_n]
    out_n = [x for x in normalized_n if x]
    return _locally_filter_accounts(out_n, q), raw_n if isinstance(raw_n, dict) else {"status": "success", "http_status": status_n, "data": records_n}


def _filter_accounts_fields(record: dict) -> dict | None:
    """
    Extract only the required fields from an account record:
    - accounts_name
    - companyId
    - accounts_mobile
    - accounts_code
    - accounts_ismain
    - accounts_issandouk
    """
    if not isinstance(record, dict):
        return None
    
    out: dict[str, object] = {}

    record_id = record.get("id")
    if record_id is not None:
        out["id"] = record_id

    account_id = record.get("accounts_id") or record.get("account_id")
    if account_id is not None:
        out["accounts_id"] = account_id
    
    # Extract name
    name = record.get("accounts_name") or record.get("name")
    if name is not None:
        out["accounts_name"] = name
    
    # Extract companyId
    comp_id = record.get("companyId") or record.get("company_id")
    if comp_id is not None:
        out["companyId"] = comp_id
    
    # Extract mobile
    mobile = record.get("accounts_mobile") or record.get("accounts_clientmobile2") or record.get("accounts_clientmobile3") or record.get("mobile")
    if mobile is not None:
        out["accounts_mobile"] = mobile
    
    # Extract code
    code = record.get("accounts_code") or record.get("code")
    if code is not None:
        out["accounts_code"] = code
    
    # Extract flags
    ismain = record.get("accounts_ismain")
    if ismain is not None:
        out["accounts_ismain"] = ismain
    issandouk = record.get("accounts_issandouk")
    if issandouk is not None:
        out["accounts_issandouk"] = issandouk
    
    return out if out else None


def _filter_accounts_list(data: object) -> list[dict]:
    """
    Process API response and extract required fields from all accounts.
    Handles both list and nested structures.
    """
    records: list[dict] = []
    
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        # Try common nested structures
        for key in ("data", "items", "results", "accounts", "records"):
            if key in data and isinstance(data[key], list):
                records = data[key]
                break
    
    # Filter and extract fields
    result = []
    for record in records:
        if isinstance(record, dict):
            filtered = _filter_accounts_fields(record)
            if filtered:
                result.append(filtered)
    
    return result


class GetNewAccountCodeInput(BaseModel):
    company_id: int = Field(..., description="Company ID (e.g. 15)")
    father_id: int = Field(..., description="Main/father account id used to generate code (e.g. 883)")


class GetNewAccountCodeTool(BaseTool):
    name: str = "get_new_account_code"
    description: str = (
        "Get new accounts code from GET /api/accounts/get_code/{fatherId}?companyId=..."
    )
    args_schema: type[BaseModel] = GetNewAccountCodeInput

    def _run(self, company_id: int, father_id: int) -> str:
        response = requests.get(
            f"{ACCOUNTS_API_BASE}/accounts/get_code/{father_id}",
            params={"companyId": company_id},
            headers=_accounts_api_headers(),
        )
        try:
            data = response.json()
        except Exception:
            return response.text

        if isinstance(data, dict) and data.get("newCode") is not None:
            return str(data.get("newCode"))

        return response.text


class GetItemsInput(BaseModel):
    company_id: int | None = Field(None, description="Company ID (optional, uses session context if omitted)")
    query: str | None = Field(
        None,
        description="Optional item search text: item Arabic name, English name, code, or description.",
    )
    is_main: bool | None = Field(
        None,
        description="Optional filter: true for main items, false for sub/child items.",
    )
    main_fathers: bool = Field(
        False,
        description="Use true for main/father items from /api/items/getMain/fathers.",
    )


class GetItemsTool(BaseTool):
    name: str = "get_items"
    description: str = (
        "Get items/products/categories from GET /api/items?companyId=... . "
        "Use this tool when the user asks for اصناف, الاصناف, صنف, منتجات, المنتجات, "
        "مخزون, items, products, categories, or inventory. "
        "When the user asks for الاصناف الرئيسية, main items, or father items, set main_fathers=true "
        "to call /api/items/getMain/fathers?companyId=... . "
        "When the user asks for الاصناف الفرعية or sub items, set is_main=false "
        "to call /api/items?companyId=...&Items_is_main=false . "
        "Do not use create_client or account tools for these requests. "
        "Action Input must contain real values only, for example company_id=3 or query='main item'."
    )
    args_schema: type[BaseModel] = GetItemsInput

    def _run(
        self,
        company_id: int | None = None,
        query: str | None = None,
        is_main: bool | None = None,
        main_fathers: bool = False,
    ) -> str:
        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid
        return json.dumps(
            fetch_items_payload(
                company_id=effective_company_id,
                query=query,
                is_main=is_main,
                main_fathers=main_fathers,
            ),
            ensure_ascii=False,
        )


class GetUnitsInput(BaseModel):
    company_id: int | None = Field(None, description="Company ID (optional, uses session context if omitted)")
    query: str | None = Field(None, description="Optional unit search text or unit id.")


class GetUnitsTool(BaseTool):
    name: str = "get_units"
    description: str = (
        "Get stock units from GET /api/units?companyId=... . "
        "Use this tool when the user asks for وحدات, الوحدات, وحدة, units, or item units. "
        "Do not use item/client/account tools for unit requests. "
        "Action Input must contain real values only, for example company_id=3."
    )
    args_schema: type[BaseModel] = GetUnitsInput

    def _run(
        self,
        company_id: int | None = None,
        query: str | None = None,
    ) -> str:
        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid
        return json.dumps(
            fetch_units_payload(
                company_id=effective_company_id,
                query=query,
            ),
            ensure_ascii=False,
        )


class GetInvoiceBooksInput(BaseModel):
    company_id: int | None = Field(None, description="Company ID (optional, uses session context if omitted)")
    book_type: str = Field("all", description="Use 'all' for all books, 'sales' for sales books, or 'purchases' for purchase books.")


class GetInvoiceBooksTool(BaseTool):
    name: str = "get_invoice_books"
    description: str = (
        "Get invoice books/دفاتر from GET /api/InvType?companyId=...&InvType_Type=... . "
        "Use book_type='all' for all دفاتر with no InvType_Type filter. "
        "Use book_type='sales' for دفاتر المبيعات (InvType_Type=-). "
        "Use book_type='purchases' for دفاتر المشتريات (InvType_Type=true)."
    )
    args_schema: type[BaseModel] = GetInvoiceBooksInput

    def _run(
        self,
        book_type: str,
        company_id: int | None = None,
    ) -> str:
        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid
        return json.dumps(
            fetch_invoice_books_payload(
                company_id=effective_company_id,
                book_type=book_type,
            ),
            ensure_ascii=False,
        )


class GetAccountSheetDetailsInput(BaseModel):
    company_id: int | None = Field(None, description="Company ID (optional, uses session context if omitted)")
    account_name: str = Field(..., description="Account name to search before fetching sheet details.")
    order_by_date: bool = Field(True, description="orderByDate: filter/order by date")
    show_unposted_entries: bool = Field(False, description="showUnpostedEntries: show unposted entries")
    show_opening_balance: bool = Field(True, description="showOpeningBalance: show opening balance")
    not_show_zero_transiation: bool = Field(True, description="notShowZeroTransiation: hide zero transactions")
    debit_amount: float | None = Field(None, description="Filter transactions by Account_Sheet_Details_M (debit)")
    credit_amount: float | None = Field(None, description="Filter transactions by Account_Sheet_Details_D (credit)")


class GetAccountSheetDetailsTool(BaseTool):
    name: str = "get_account_sheet_details"
    description: str = (
        "Get detailed account statement / كشف الحساب التفصيلي for one account by name. "
        "First searches accounts by account_name, then uses the matched accounts_id in "
        "GET /api/accountsSheetDetails?companyId=...&Accounts_Id=..."
    )
    args_schema: type[BaseModel] = GetAccountSheetDetailsInput

    def _run(
        self,
        account_name: str,
        company_id: int | None = None,
        order_by_date: bool = True,
        show_unposted_entries: bool = False,
        show_opening_balance: bool = True,
        not_show_zero_transiation: bool = True,
        debit_amount: float | None = None,
        credit_amount: float | None = None,
    ) -> str:
        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid
        return json.dumps(
            fetch_account_sheet_details_payload(
                company_id=effective_company_id,
                account_name=account_name,
                order_by_date=order_by_date,
                show_unposted_entries=show_unposted_entries,
                show_opening_balance=show_opening_balance,
                not_show_zero_transiation=not_show_zero_transiation,
                debit_amount=debit_amount,
                credit_amount=credit_amount,
            ),
            ensure_ascii=False,
        )


class GetItemDescriptionsInput(BaseModel):
    company_id: int | None = Field(None, description="Company ID (optional, uses session context if omitted)")
    query: str | None = Field(None, description="Optional recipe/description title search text or id.")


class GetItemDescriptionsTool(BaseTool):
    name: str = "get_item_descriptions"
    description: str = (
        "Get item material descriptions/recipes from GET /api/Stock_ItemDesc?companyId=... . "
        "Use this tool when the user asks for وصفات المواد, وصفات, item descriptions, "
        "material recipes, or recipes. "
        "Action Input must contain real values only, for example company_id=3."
    )
    args_schema: type[BaseModel] = GetItemDescriptionsInput

    def _run(
        self,
        company_id: int | None = None,
        query: str | None = None,
    ) -> str:
        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid
        return json.dumps(
            fetch_item_desc_payload(
                company_id=effective_company_id,
                query=query,
            ),
            ensure_ascii=False,
        )


class GetSupplierCardsInput(BaseModel):
    company_id: int | None = Field(None, description="Company ID (optional, uses session context if omitted)")


class GetSupplierCardsTool(BaseTool):
    name: str = "get_supplier_cards"
    description: str = (
        "Get supplier account cards from GET /api/accounts/father/1?isMain=false&campanyId=... . "
        "Use this tool when the user asks for بطاقة الموردون, بطاقات الموردين, الموردون, "
        "supplier cards, or suppliers. The response uses the same filtered account fields."
    )
    args_schema: type[BaseModel] = GetSupplierCardsInput

    def _run(self, company_id: int | None = None) -> str:
        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid
        return json.dumps(
            fetch_supplier_cards_payload(company_id=effective_company_id),
            ensure_ascii=False,
        )


class GetAllAccountsTreeInput(BaseModel):
    company_id: int | None = Field(None, description="Company ID (optional, uses context if not provided)")


class GetAllAccountsTreeTool(BaseTool):
    name: str = "get_all_accounts_tree"
    description: str = (
        "Use only for account/client list requests. Do not use for items/products/categories/"
        "inventory such as اصناف or منتجات. "
        "Get all accounts in tree structure from GET /api/accounts/getAll/getAllTree. "
        "No search query required - returns the complete accounts tree."
    )
    args_schema: type[BaseModel] = GetAllAccountsTreeInput

    def _run(self, company_id: int | None = None) -> str:
        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid
        if effective_company_id is None:
            return json.dumps({"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}, ensure_ascii=False)

        response = requests.get(
            f"{ACCOUNTS_API_BASE}/accounts/getAll/getAllTree",
            params={"companyId": effective_company_id},
            headers=_accounts_api_headers(),
        )
        try:
            data = response.json()
        except Exception:
            return json.dumps({"status": "error", "http_status": response.status_code, "error": "Invalid JSON response", "data": []}, ensure_ascii=False)

        if 200 <= response.status_code < 300:
            filtered_data = _filter_accounts_list(data)
            return json.dumps({"status": "success", "http_status": response.status_code, "data": filtered_data}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "http_status": response.status_code, "error": "API request failed", "data": []}, ensure_ascii=False)


class GetSubAccountsInput(BaseModel):
    company_id: int | None = Field(None, description="Company ID (optional, uses context if not provided)")


class GetSubAccountsTool(BaseTool):
    name: str = "get_sub_accounts"
    description: str = (
        "Use only for account/client sub-account requests. Do not use for items/products/"
        "categories/inventory such as اصناف or منتجات. "
        "Get all sub accounts from GET /api/accounts/getAll/subAccounts. "
        "No search query required - returns all sub accounts."
    )
    args_schema: type[BaseModel] = GetSubAccountsInput

    def _run(self, company_id: int | None = None) -> str:
        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid
        if effective_company_id is None:
            return json.dumps({"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}, ensure_ascii=False)

        response = requests.get(
            f"{ACCOUNTS_API_BASE}/accounts/getAll/subAccounts",
            params={"companyId": effective_company_id},
            headers=_accounts_api_headers(),
        )
        try:
            data = response.json()
        except Exception:
            return json.dumps({"status": "error", "http_status": response.status_code, "error": "Invalid JSON response", "data": []}, ensure_ascii=False)

        if 200 <= response.status_code < 300:
            filtered_data = _filter_accounts_list(data)
            return json.dumps({"status": "success", "http_status": response.status_code, "data": filtered_data}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "http_status": response.status_code, "error": "API request failed", "data": []}, ensure_ascii=False)


class GetSandoukAccountsInput(BaseModel):
    company_id: int | None = Field(None, description="Company ID (optional, uses context if not provided)")


class GetSandoukAccountsTool(BaseTool):
    name: str = "get_sandouk_accounts"
    description: str = (
        "Use only for account/client sandouk/cashbox requests. Do not use for items/products/"
        "categories/inventory such as اصناف or منتجات. "
        "Get all sandouk accounts from GET /api/accounts/getAll/sandoukAccounts. "
        "No search query required - returns all sandouk accounts."
    )
    args_schema: type[BaseModel] = GetSandoukAccountsInput

    def _run(self, company_id: int | None = None) -> str:
        ctx_cid = get_active_company_id()
        effective_company_id = company_id if company_id is not None else ctx_cid
        if effective_company_id is None:
            return json.dumps({"status": "error", "http_status": 400, "error": "Missing company_id", "data": []}, ensure_ascii=False)

        response = requests.get(
            f"{ACCOUNTS_API_BASE}/accounts/getAll/sandoukAccounts",
            params={"companyId": effective_company_id},
            headers=_accounts_api_headers(),
        )
        try:
            data = response.json()
        except Exception:
            return json.dumps({"status": "error", "http_status": response.status_code, "error": "Invalid JSON response", "data": []}, ensure_ascii=False)

        if 200 <= response.status_code < 300:
            filtered_data = _filter_accounts_list(data)
            return json.dumps({"status": "success", "http_status": response.status_code, "data": filtered_data}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "http_status": response.status_code, "error": "API request failed", "data": []}, ensure_ascii=False)


def create_accounts_pdf_report(data: list[dict], report_title: str = "تقرير الحسابات") -> str:
    """
    Create a PDF report from accounts data using ReportLab.
    Returns the file path of the generated PDF.
    """
    # Register Arabic font
    try:
        # Try to register Arial Unicode MS (available on Windows)
        pdfmetrics.registerFont(TTFont('Arabic', 'C:\\Windows\\Fonts\\arial.ttf'))
        arabic_font = 'Arabic'
    except:
        try:
            # Fallback to Tahoma
            pdfmetrics.registerFont(TTFont('Arabic', 'C:\\Windows\\Fonts\\tahoma.ttf'))
            arabic_font = 'Arabic'
        except:
            # If no Arabic font available, use default but with RTL settings
            arabic_font = 'Helvetica'
    
    # Create reports directory
    reports_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    filename = f"accounts_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = os.path.join(reports_dir, filename)
    
    # Create PDF document
    doc = SimpleDocTemplate(filepath, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    styles = getSampleStyleSheet()
    
    # Create Arabic-compatible style
    arabic_style = ParagraphStyle(
        'Arabic',
        parent=styles['Normal'],
        fontSize=12,
        leading=14,
        alignment=2,  # Right alignment for Arabic
        wordWrap='RTL',  # Right-to-left word wrapping
        fontName=arabic_font
    )
    
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Title'],
        fontSize=16,
        alignment=1,  # Center alignment
        spaceAfter=30,
        fontName=arabic_font
    )
    story.append(Paragraph(_process_arabic_text(report_title), title_style))
    
    # Date
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_text = f"تاريخ الإنشاء: {current_date}"
    story.append(Paragraph(_process_arabic_text(date_text), arabic_style))
    story.append(Spacer(1, 12))
    
    if not data:
        # No data message
        story.append(Paragraph(_process_arabic_text("لا توجد بيانات متاحة"), arabic_style))
    else:
        # Prepare table data
        table_data = [[_process_arabic_text("الرقم"), _process_arabic_text("اسم الحساب"), _process_arabic_text("الكود"), _process_arabic_text("الهاتف"), _process_arabic_text("النوع")]]
        
        for idx, account in enumerate(data, 1):
            name = _process_arabic_text(str(account.get('accounts_name', '')))
            code = str(account.get('accounts_code', ''))
            mobile = str(account.get('accounts_mobile', ''))
            is_main = _process_arabic_text("رئيسي") if account.get('accounts_ismain') else _process_arabic_text("فرعي")
            is_sandouk = _process_arabic_text("صندوق") if account.get('accounts_issandouk') else ""
            account_type = f"{is_main} {is_sandouk}".strip()
            
            table_data.append([
                str(idx),
                name[:30],  # Truncate long names
                code,
                mobile,
                account_type
            ])
        
        # Create table
        table = Table(table_data, colWidths=[0.5*inch, 2*inch, 1*inch, 1.5*inch, 1*inch])
        
        # Style the table
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), arabic_font),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),  # Right align Arabic text
            ('FONTNAME', (1, 1), (-1, -1), arabic_font),
        ])
        table.setStyle(table_style)
        
        story.append(table)
    
    # Build PDF
    doc.build(story)
    
    return filepath
