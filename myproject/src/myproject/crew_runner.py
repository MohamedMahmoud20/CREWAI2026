"""
Single entry for running the client crew from CLI, HTTP API, or Telegram.
"""
from __future__ import annotations

import ast
import json
import re
import warnings
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

from myproject.config.crew_setup import client_crew  # noqa: E402
from myproject.runtime_context import (  # noqa: E402
    auth_header_scope,
    company_id_scope,
    fiscal_year_id_scope,
    skip_name_confirmation_scope,
)
from myproject.tools.tools import (  # noqa: E402
    fetch_account_by_id_payload,
    fetch_invoice_books_payload,
    fetch_item_desc_payload,
    fetch_items_payload,
    fetch_supplier_cards_payload,
    fetch_units_payload,
)

_ITEMS_KEYWORDS = (
    "اصناف",
    "الأصناف",
    "الصنف",
    "منتجات",
    "المنتجات",
    "مخزون",
    "المخزون",
    "items",
    "products",
    "categories",
    "inventory",
)


def _looks_like_items_request(user_text: str) -> bool:
    text = (user_text or "").strip().casefold()
    return any(keyword.casefold() in text for keyword in _ITEMS_KEYWORDS)


def _strip_markdown_json_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```") and s.endswith("```"):
        lines = s.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return s


def _json_loads_if_possible(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return None
    if not isinstance(value, str):
        return value

    text = _strip_markdown_json_fence(value)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return value


def _normalize_agent_payload(value: Any) -> Any:
    data = _json_loads_if_possible(value)

    if isinstance(data, dict):
        if "get_client_response" in data and len(data) == 1:
            return _normalize_agent_payload(data["get_client_response"])
        if "create_client_response" in data and len(data) == 1:
            return _normalize_agent_payload(data["create_client_response"])

        normalized = {}
        for k, v in data.items():
            normalized[k] = _normalize_agent_payload(v)
        return normalized

    if isinstance(data, list):
        return [_normalize_agent_payload(item) for item in data]

    return data


def _extract_result_payload(result: Any) -> Any:
    raw = getattr(result, "raw", result)
    normalized = _normalize_agent_payload(raw)
    if normalized in (None, ""):
        return ""
    return normalized


def _kickoff_inputs(user_text: str, company_id: int | None) -> dict[str, Any]:
    return {
        "user_request": user_text,
        "company_id": str(company_id) if company_id is not None else "",
    }


def _looks_like_items_request(user_text: str) -> bool:
    text = (user_text or "").strip().casefold()
    keywords = (
        "\u0627\u0635\u0646\u0627\u0641",
        "\u0623\u0635\u0646\u0627\u0641",
        "\u0627\u0644\u0627\u0635\u0646\u0627\u0641",
        "\u0627\u0644\u0623\u0635\u0646\u0627\u0641",
        "\u0627\u0644\u0635\u0646\u0641",
        "\u0635\u0646\u0641",
        "\u0645\u0646\u062a\u062c\u0627\u062a",
        "\u0627\u0644\u0645\u0646\u062a\u062c\u0627\u062a",
        "\u0645\u062e\u0632\u0648\u0646",
        "\u0627\u0644\u0645\u062e\u0632\u0648\u0646",
        "items",
        "products",
        "categories",
        "inventory",
    )
    return any(keyword.casefold() in text for keyword in keywords)


def _looks_like_main_items_request(user_text: str) -> bool:
    text = (user_text or "").strip().casefold()
    keywords = (
        "\u0631\u0626\u064a\u0633\u064a",
        "\u0631\u0626\u064a\u0633\u064a\u0629",
        "\u0627\u0644\u0631\u0626\u064a\u0633\u064a\u0629",
        "main",
        "father",
        "fathers",
    )
    return _looks_like_items_request(text) and any(keyword.casefold() in text for keyword in keywords)


def _looks_like_sub_items_request(user_text: str) -> bool:
    text = (user_text or "").strip().casefold()
    keywords = (
        "\u0641\u0631\u0639\u064a",
        "\u0641\u0631\u0639\u064a\u0629",
        "\u0627\u0644\u0641\u0631\u0639\u064a\u0629",
        "sub",
        "child",
        "children",
    )
    return _looks_like_items_request(text) and any(keyword.casefold() in text for keyword in keywords)


def _looks_like_units_request(user_text: str) -> bool:
    text = (user_text or "").strip().casefold()
    keywords = (
        "\u0648\u062d\u062f\u0627\u062a",
        "\u0627\u0644\u0648\u062d\u062f\u0627\u062a",
        "\u0648\u062d\u062f\u0629",
        "\u0627\u0644\u0648\u062d\u062f\u0629",
        "units",
        "unit",
        "item units",
    )
    return any(keyword.casefold() in text for keyword in keywords)


def _looks_like_item_desc_request(user_text: str) -> bool:
    text = (user_text or "").strip().casefold()
    keywords = (
        "\u0648\u0635\u0641\u0627\u062a \u0627\u0644\u0645\u0648\u0627\u062f",
        "\u0648\u0635\u0641\u0627\u062a",
        "\u0648\u0635\u0641\u0629",
        "recipes",
        "recipe",
        "material recipes",
        "item descriptions",
        "item desc",
    )
    return any(keyword.casefold() in text for keyword in keywords)


def _looks_like_supplier_cards_request(user_text: str) -> bool:
    text = (user_text or "").strip().casefold()
    keywords = (
        "\u0628\u0637\u0627\u0642\u0629 \u0627\u0644\u0645\u0648\u0631\u062f\u0648\u0646",
        "\u0628\u0637\u0627\u0642\u0629 \u0627\u0644\u0645\u0648\u0631\u062f\u064a\u0646",
        "\u0628\u0637\u0627\u0642\u0627\u062a \u0627\u0644\u0645\u0648\u0631\u062f\u064a\u0646",
        "\u0627\u0644\u0645\u0648\u0631\u062f\u0648\u0646",
        "\u0627\u0644\u0645\u0648\u0631\u062f\u064a\u0646",
        "\u0645\u0648\u0631\u062f\u0648\u0646",
        "\u0645\u0648\u0631\u062f\u064a\u0646",
        "supplier cards",
        "supplier card",
        "suppliers",
    )
    return any(keyword.casefold() in text for keyword in keywords)


def _invoice_books_type(user_text: str) -> str | None:
    text = (user_text or "").strip().casefold()
    if not text:
        return None

    has_books_word = any(
        word in text
        for word in (
            "\u062f\u0641\u0627\u062a\u0631",
            "\u0627\u0644\u062f\u0641\u0627\u062a\u0631",
            "book",
            "books",
            "invoice type",
            "invtype",
        )
    )
    if not has_books_word:
        return None

    if any(word in text for word in ("\u0645\u0628\u064a\u0639\u0627\u062a", "\u0627\u0644\u0645\u0628\u064a\u0639\u0627\u062a", "sales", "sale")):
        return "sales"
    if any(word in text for word in ("\u0645\u0634\u062a\u0631\u064a\u0627\u062a", "\u0627\u0644\u0645\u0634\u062a\u0631\u064a\u0627\u062a", "purchases", "purchase", "buy")):
        return "purchases"

    return "all"


def _extract_account_id_request(user_text: str) -> int | None:
    text = (user_text or "").strip().casefold()
    if not text:
        return None

    has_account_word = any(
        word in text
        for word in (
            "\u0639\u0645\u064a\u0644",
            "\u0627\u0644\u0639\u0645\u064a\u0644",
            "\u062d\u0633\u0627\u0628",
            "\u0627\u0644\u062d\u0633\u0627\u0628",
            "account",
            "client",
            "customer",
        )
    )
    if not has_account_word:
        return None

    patterns = (
        r"\bid\s*(?:بتاعه|بتاعها|=|:)?\s*(\d+)\b",
        r"\b(?:account|client|customer)\s*(?:id|#|number|no\.?)?\s*(\d+)\b",
        r"(?:رقم|كود)\s*(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None

    return None


def kickoff_crew(
    user_text: str,
    company_id: int | None = None,
    skip_name_confirmation: bool = False,
    auth_header: str | None = None,
    fiscal_year_id: int | None = None,
) -> Any:
    """Run the crew with the user's text; returns normalized payload (same as API `data`)."""
    account_id = _extract_account_id_request(user_text)
    if account_id is not None:
        return fetch_account_by_id_payload(account_id=account_id, auth_header=auth_header)

    invoice_books_type = _invoice_books_type(user_text)
    if invoice_books_type is not None:
        return fetch_invoice_books_payload(
            company_id=company_id,
            book_type=invoice_books_type,
            auth_header=auth_header,
        )

    if _looks_like_item_desc_request(user_text):
        return fetch_item_desc_payload(company_id=company_id, auth_header=auth_header)

    if _looks_like_supplier_cards_request(user_text):
        return fetch_supplier_cards_payload(company_id=company_id, auth_header=auth_header)

    if _looks_like_units_request(user_text):
        return fetch_units_payload(company_id=company_id, auth_header=auth_header)

    if _looks_like_items_request(user_text):
        return fetch_items_payload(
            company_id=company_id,
            auth_header=auth_header,
            main_fathers=_looks_like_main_items_request(user_text),
            is_main=False if _looks_like_sub_items_request(user_text) else None,
        )

    with (
        company_id_scope(company_id),
        skip_name_confirmation_scope(skip_name_confirmation),
        auth_header_scope(auth_header),
        fiscal_year_id_scope(fiscal_year_id),
    ):
        result = client_crew.kickoff(inputs=_kickoff_inputs(user_text, company_id))
    return _extract_result_payload(result)


def run_crewai(
    user_text: str,
    company_id: int | None = None,
    skip_name_confirmation: bool = False,
    auth_header: str | None = None,
    fiscal_year_id: int | None = None,
) -> str:
    """
    Run the crew and return a human-readable string for clients (Telegram, logs).
    When company_id is set (e.g. Telegram), tools receive it via runtime context.
    """
    data = kickoff_crew(
        user_text,
        company_id=company_id,
        skip_name_confirmation=skip_name_confirmation,
        auth_header=auth_header,
        fiscal_year_id=fiscal_year_id,
    )
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False, indent=2)
    return str(data)


def kickoff_crew_with_trigger(trigger_payload: dict[str, Any], company_id: int | None = None) -> Any:
    """Run the crew with CrewAI trigger payload (same inputs as legacy CLI)."""
    user_request = trigger_payload.get("user_request", "")
    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "user_request": user_request,
        "company_id": str(company_id) if company_id is not None else "",
    }
    with company_id_scope(company_id):
        result = client_crew.kickoff(inputs=inputs)
    return _extract_result_payload(result)


def run_crewai_with_trigger(trigger_payload: dict[str, Any], company_id: int | None = None) -> str:
    data = kickoff_crew_with_trigger(trigger_payload, company_id=company_id)
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False, indent=2)
    return str(data)
