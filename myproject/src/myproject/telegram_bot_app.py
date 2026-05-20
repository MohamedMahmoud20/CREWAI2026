"""
Telegram bot: onboarding (company per user) + CrewAI via run_crewai(user_text, company_id).

Requires BOT_TOKEN in the environment (e.g. .env in the project root).
Run: python -m myproject.telegram_bot_app
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import socket
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import requests
from telegram import Update
from telegram.error import Conflict as TelegramConflict
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Project root = parent of src/
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

load_dotenv(ROOT_DIR / ".env")

from myproject.bot_lock import BotLockManager, BotLockConflictError  # noqa: E402
from myproject.crew_runner import kickoff_crew  # noqa: E402
from myproject.telegram_user_store import (  # noqa: E402
    clear_company_id,
    clear_fiscal_year_id,
    clear_login_session,
    get_auth_header,
    get_company_id,
    get_fiscal_year_id,
    get_login_email,
    has_company_id,
    has_fiscal_year_id,
    has_login_session,
    is_awaiting_login_email,
    is_awaiting_login_password,
    is_awaiting_fiscal_year,
    save_login_email,
    save_login_session,
    save_company_id,
    save_fiscal_year_id,
    set_awaiting_login_email,
    set_awaiting_login_password,
    set_awaiting_fiscal_year,
)
from myproject.user_login import login_user  # noqa: E402
from myproject.tools.tools import create_accounts_pdf_report  # noqa: E402

TELEGRAM_MAX_MESSAGE_LENGTH = 4096

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Telegram bot tokens look like: 123456789:AAH... (digits, colon, secret)
_BOT_TOKEN_PATTERN = re.compile(r"\b(\d{5,}:[A-Za-z0-9_-]{25,})\b")
_VALID_BOT_TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{25,}$")

MSG_ASK_EMAIL = "من فضلك ادخل البريد الالكتروني"
MSG_ASK_PASSWORD = "من فضلك ادخل كلمة المرور"
MSG_LOGIN_SUCCESS = "تم تسجيل الدخول بنجاح. يمكنك كتابة طلبك الآن."
MSG_PICK_FISCAL_YEAR = "اختر السنة المالية (اكتب رقم الاختيار)."
MSG_FISCAL_YEAR_SAVED = "تم اختيار السنة المالية بنجاح. يمكنك كتابة طلبك الآن."
MSG_LOGIN_FAILED = "فشل تسجيل الدخول. تأكد من البريد الالكتروني وكلمة المرور وحاول مرة أخرى."
MSG_WELCOME_BACK = "مرحباً. يمكنك كتابة طلبك الآن."
MSG_PRESS_START = "اضغط /start للبدء."
MSG_EMPTY_EMAIL = "الرجاء إدخال بريد إلكتروني صالح."
MSG_EMPTY_PASSWORD = "الرجاء إدخال كلمة مرور صالحة."
MSG_SERVER_ERROR = "تعذر الاتصال بالخادم أو حدث خطأ. حاول لاحقاً."
MSG_HTTP_ERROR = "الخادم رفض الطلب. حاول لاحقاً."
MSG_CONFIRM_YES_NO = "من فضلك رد بـ نعم أو لا."
MSG_PROCESSING = "جاري تنفيذ طلبك..." 

# Keywords for resetting user data
RESET_KEYWORDS = {
    # Company change keywords
    "غير الشركة", "غير الشركه", "تغيير الشركة", "تغيير الشركه", "شركة جديدة", "شركه جديده",
    "change company", "new company", "switch company",
    # Fiscal year change keywords  
    "غير السنة المالية", "غير السنه الماليه", "تغيير السنة المالية", "تغيير السنه الماليه",
    "سنة مالية جديدة", "سنه ماليه جديده", "change fiscal year", "new fiscal year", "switch fiscal year",
    # General reset keywords
    "مسح البيانات", "مسح البيانات", "إعادة تعيين", "اعاده تعيين", "reset", "clear data", "مسح كل شيء"
}

YES_WORDS = {"نعم", "ايوه", "أيوه", "اه", "أه", "yes", "y"}
NO_WORDS = {"لا", "لأ", "لاا", "no", "n"}

FISCAL_API_BASE = os.getenv("FISCAL_API_BASE", "http://104.248.246.2/api").rstrip("/")


def normalize_bot_token(raw: str | None) -> str | None:
    """
    Parse BOT_TOKEN from .env even if the line was pasted wrong, e.g.:
      YOUR_NEW_TOKEN_HERE = 123456789:AAH...
    Only the `digits:secret` part is valid for Telegram.
    """
    if not raw:
        return None
    s = raw.strip().strip('"').strip("'")
    m = _BOT_TOKEN_PATTERN.search(s)
    if m:
        return m.group(1)
    return s if s else None


def chunk_text_for_telegram(text: str, max_len: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]


def _result_to_text(result: object) -> str:
    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


def _is_reset_request(text: str) -> bool:
    """Check if user wants to reset/clear their data."""
    normalized = _normalize_reply(text)
    return any(keyword.lower() in normalized for keyword in RESET_KEYWORDS)


def _reset_user_data(uid: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all saved user data and reset to initial state."""
    clear_login_session(uid)
    clear_company_id(uid)
    clear_fiscal_year_id(uid)
    # Clear any pending confirmations or context data
    context.user_data.clear()
    logger.info(f"User {uid} data reset completed")


def _normalize_reply(text: str) -> str:
    return (text or "").strip().lower()


def _extract_accounts_data(result: object) -> list[dict] | None:
    """Extract accounts data from various result formats."""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        # Direct data
        if "data" in result and isinstance(result["data"], list):
            return result["data"]
        # Nested in response keys
        for key, value in result.items():
            if isinstance(value, dict) and "data" in value and isinstance(value["data"], list):
                return value["data"]
    return None


def _is_report_request(text: str) -> bool:
    """Check if user is requesting a report or PDF."""
    normalized = _normalize_reply(text)
    report_keywords = {
        "تقرير", "report", "pdf", "طباعة", "print", "export", "تصدير"
    }
    return any(keyword in normalized for keyword in report_keywords)


def _is_yes(text: str) -> bool:
    return _normalize_reply(text) in YES_WORDS


def _is_no(text: str) -> bool:
    return _normalize_reply(text) in NO_WORDS


def _build_suggested_request(original_request: str, original_name: str, suggested_name: str) -> str:
    return original_request.replace(original_name, suggested_name, 1)


def _to_int_or_none(value: str | None) -> int | None:
    s = (value or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _fetch_fiscal_years(company_id: int, auth_header: str | None) -> list[dict]:
    headers = {"Accept": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    resp = requests.get(
        f"{FISCAL_API_BASE}/fiscalYear",
        params={"companyId": company_id},
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 404 or resp.status_code >= 400:
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _filter_telegram_accounts_fields(record: dict) -> dict | None:
    """Extract required fields: accounts_name, companyId, accounts_mobile, accounts_code, accounts_ismain, accounts_issandouk"""
    if not isinstance(record, dict):
        return None
    
    out: dict[str, object] = {}
    
    name = record.get("accounts_name") or record.get("name")
    if name is not None:
        out["accounts_name"] = name
    
    comp_id = record.get("companyId") or record.get("company_id")
    if comp_id is not None:
        out["companyId"] = comp_id
    
    mobile = record.get("accounts_mobile") or record.get("accounts_clientmobile2") or record.get("accounts_clientmobile3") or record.get("mobile")
    if mobile is not None:
        out["accounts_mobile"] = mobile
    
    code = record.get("accounts_code") or record.get("code")
    if code is not None:
        out["accounts_code"] = code
    
    ismain = record.get("accounts_ismain")
    if ismain is not None:
        out["accounts_ismain"] = ismain
    issandouk = record.get("accounts_issandouk")
    if issandouk is not None:
        out["accounts_issandouk"] = issandouk
    
    return out if out else None


def _filter_telegram_accounts_list(data: object) -> list[dict]:
    """Process API response and extract required fields from all accounts"""
    records: list[dict] = []
    
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        for key in ("data", "items", "results", "accounts", "records"):
            if key in data and isinstance(data[key], list):
                records = data[key]
                break
    
    result = []
    for record in records:
        if isinstance(record, dict):
            filtered = _filter_telegram_accounts_fields(record)
            if filtered:
                result.append(filtered)
    
    return result


def _fetch_all_accounts_tree(company_id: int, auth_header: str | None) -> dict | list:
    headers = {"Accept": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    resp = requests.get(
        f"{FISCAL_API_BASE}/accounts/getAll/getAllTree",
        params={"companyId": company_id},
        headers=headers,
        timeout=30,
    )
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}"}
    try:
        data = resp.json()
        filtered = _filter_telegram_accounts_list(data)
        return filtered
    except Exception:
        return {"error": "Invalid JSON response"}


def _fetch_sub_accounts(company_id: int, auth_header: str | None) -> list[dict]:
    headers = {"Accept": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    resp = requests.get(
        f"{FISCAL_API_BASE}/accounts/getAll/subAccounts",
        params={"companyId": company_id},
        headers=headers,
        timeout=30,
    )
    if resp.status_code >= 400:
        return []
    try:
        data = resp.json()
        filtered = _filter_telegram_accounts_list(data)
        return filtered if isinstance(filtered, list) else []
    except Exception:
        return []


def _fetch_sandouk_accounts(company_id: int, auth_header: str | None) -> list[dict]:
    headers = {"Accept": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    resp = requests.get(
        f"{FISCAL_API_BASE}/accounts/getAll/sandoukAccounts",
        params={"companyId": company_id},
        headers=headers,
        timeout=30,
    )
    if resp.status_code >= 400:
        return []
    try:
        data = resp.json()
        filtered = _filter_telegram_accounts_list(data)
        return filtered if isinstance(filtered, list) else []
    except Exception:
        return []


def _fiscal_year_label(item: dict) -> str:
    name = item.get("nameAr") or item.get("nameEn") or item.get("name") or ""
    return str(name).strip() or f"FY {item.get('id')}"


def _fiscal_year_sort_key(item: dict) -> tuple[int, str]:
    label = _fiscal_year_label(item)
    year = _to_int_or_none(label)
    return (year or -1, label)


async def _prompt_fiscal_year_choice(message, years: list[dict], suggested_id: int | None) -> None:
    if not years:
        await message.reply_text(MSG_LOGIN_SUCCESS)
        return

    lines: list[str] = []
    if suggested_id is not None:
        suggested = next((y for y in years if y.get("id") == suggested_id), None)
        if isinstance(suggested, dict):
            lines.append(f"آخر سنة مالية (افتراضي): {_fiscal_year_label(suggested)}")
    lines.append(MSG_PICK_FISCAL_YEAR)
    for idx, y in enumerate(years, start=1):
        mark = " (افتراضي)" if suggested_id is not None and y.get("id") == suggested_id else ""
        lines.append(f"{idx}) {_fiscal_year_label(y)}{mark}")
    await message.reply_text("\n".join(lines))


async def _send_result_chunks(message, result: object) -> None:
    if isinstance(result, dict) and result.get("status") == "needs_confirmation":
        suggested_name = str(result.get("suggested_accounts_name", "")).strip()
        if suggested_name:
            await message.reply_text(f"هل تقصد {suggested_name}؟\nرد بـ نعم أو لا.")
            return
    for chunk in chunk_text_for_telegram(_result_to_text(result)):
        await message.reply_text(chunk)


def _login_error_message(err: str | None) -> str:
    if not err:
        return MSG_LOGIN_FAILED
    if err == "empty_email":
        return MSG_EMPTY_EMAIL
    if err == "empty_password":
        return MSG_EMPTY_PASSWORD
    if err == "missing_token":
        return MSG_LOGIN_FAILED
    if err == "invalid_json":
        return MSG_SERVER_ERROR
    if err == "missing_company":
        return MSG_SERVER_ERROR
    if err.startswith("http_"):
        try:
            code = int(err.split("_", 1)[1])
            if code in (401, 403):
                return MSG_LOGIN_FAILED
            if code >= 500:
                return MSG_SERVER_ERROR
        except (IndexError, ValueError):
            pass
        return MSG_HTTP_ERROR
    if err.startswith("network_error:"):
        return MSG_SERVER_ERROR
    return MSG_LOGIN_FAILED


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    uid = update.effective_user.id

    if has_login_session(uid) and has_company_id(uid) and has_fiscal_year_id(uid):
        await update.message.reply_text(MSG_WELCOME_BACK)
        return

    if has_login_session(uid) and not has_company_id(uid):
        # Backward-compat: previously company_id was collected separately.
        # Force re-login so we can fetch company_id from login payload.
        clear_login_session(uid)
        clear_company_id(uid)
        clear_fiscal_year_id(uid)

    set_awaiting_login_email(uid, True)
    set_awaiting_login_password(uid, False)
    await update.message.reply_text(MSG_ASK_EMAIL)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text or not update.effective_user:
        return
    uid = update.effective_user.id
    user_text = update.message.text.strip()
    if not user_text:
        return

    # ─── Check for reset request (change company/fiscal year) ───
    if _is_reset_request(user_text):
        _reset_user_data(uid, context)
        await update.message.reply_text("تم مسح جميع البيانات المحفوظة. يمكنك البدء من جديد.")
        await update.message.reply_text(MSG_ASK_EMAIL)
        set_awaiting_login_email(uid, True)
        set_awaiting_login_password(uid, False)
        return

    if is_awaiting_login_email(uid):
        if "@" not in user_text or "." not in user_text:
            await update.message.reply_text(MSG_EMPTY_EMAIL)
            return
        try:
            save_login_email(uid, user_text)
        except OSError as exc:
            logger.exception("Failed to save telegram login email: %s", exc)
            await update.message.reply_text(MSG_SERVER_ERROR)
            return
        await update.message.reply_text(MSG_ASK_PASSWORD)
        return

    if is_awaiting_login_password(uid):
        email = get_login_email(uid)
        if not email:
            set_awaiting_login_password(uid, False)
            set_awaiting_login_email(uid, True)
            await update.message.reply_text(MSG_ASK_EMAIL)
            return

        await update.message.chat.send_action(action="typing")
        try:
            auth_header, company_id, err = await asyncio.to_thread(login_user, email, user_text)
        except Exception:
            logger.exception("Login request failed")
            await update.message.reply_text(MSG_SERVER_ERROR)
            return

        if not auth_header:
            set_awaiting_login_password(uid, False)
            set_awaiting_login_email(uid, True)
            await update.message.reply_text(_login_error_message(err))
            await update.message.reply_text(MSG_ASK_EMAIL)
            return

        try:
            clear_company_id(uid)
            clear_fiscal_year_id(uid)
            save_login_session(uid, email, auth_header)
            if company_id is not None:
                save_company_id(uid, company_id)
        except OSError as exc:
            logger.exception("Failed to save telegram login session: %s", exc)
            await update.message.reply_text(MSG_SERVER_ERROR)
            return

        if not has_company_id(uid):
            # We don't ask the user for company. If backend didn't return it, we can't proceed safely.
            clear_login_session(uid)
            await update.message.reply_text(MSG_SERVER_ERROR)
            await update.message.reply_text(MSG_ASK_EMAIL)
            return
        # After successful login: load fiscal years and ask user to pick (default = latest).
        years = await asyncio.to_thread(_fetch_fiscal_years, company_id, auth_header)
        years_sorted = sorted([y for y in years if isinstance(y, dict)], key=_fiscal_year_sort_key, reverse=True)
        suggested_id = years_sorted[0].get("id") if years_sorted else None
        if isinstance(suggested_id, int) and suggested_id > 0:
            save_fiscal_year_id(uid, suggested_id)
        set_awaiting_fiscal_year(uid, True)
        context.user_data["fiscal_year_options"] = years_sorted
        await _prompt_fiscal_year_choice(
            update.message,
            years_sorted,
            suggested_id if isinstance(suggested_id, int) else None,
        )
        return

    # ─── No company yet and not in onboarding (should use /start) ───
    if not has_login_session(uid):
        set_awaiting_login_email(uid, True)
        set_awaiting_login_password(uid, False)
        await update.message.reply_text(MSG_ASK_EMAIL)
        return

    if not has_company_id(uid):
        # We don't ask the user for company; require re-login to receive it from backend.
        clear_login_session(uid)
        clear_company_id(uid)
        clear_fiscal_year_id(uid)
        set_awaiting_login_email(uid, True)
        set_awaiting_login_password(uid, False)
        await update.message.reply_text(MSG_ASK_EMAIL)
        return

    company_id = get_company_id(uid)
    if company_id is None:
        await update.message.reply_text(MSG_PRESS_START)
        return
    auth_header = get_auth_header(uid)

    # ─── Fiscal year selection (required after login) ───
    if is_awaiting_fiscal_year(uid) or (has_login_session(uid) and has_company_id(uid) and not has_fiscal_year_id(uid)):
        options = context.user_data.get("fiscal_year_options")
        if not isinstance(options, list) or not options:
            options = await asyncio.to_thread(_fetch_fiscal_years, company_id, auth_header)
            options = sorted([y for y in options if isinstance(y, dict)], key=_fiscal_year_sort_key, reverse=True)
            context.user_data["fiscal_year_options"] = options

        chosen_id: int | None = None
        if isinstance(options, list) and options:
            idx = _to_int_or_none(user_text)
            if idx is not None and 1 <= idx <= len(options):
                item = options[idx - 1]
                if isinstance(item, dict) and isinstance(item.get("id"), int):
                    chosen_id = int(item["id"])
            else:
                norm = user_text.strip()
                for item in options:
                    if not isinstance(item, dict):
                        continue
                    if _fiscal_year_label(item) == norm:
                        if isinstance(item.get("id"), int):
                            chosen_id = int(item["id"])
                            break

        if chosen_id is None:
            await _prompt_fiscal_year_choice(update.message, options if isinstance(options, list) else [], get_fiscal_year_id(uid))
            return

        save_fiscal_year_id(uid, chosen_id)
        set_awaiting_fiscal_year(uid, False)
        await update.message.reply_text(MSG_FISCAL_YEAR_SAVED)
        return

    # ─── Check for report request ───
    if _is_report_request(user_text):
        await update.message.reply_text(MSG_PROCESSING)
        await update.message.chat.send_action(action="typing")
        try:
            # Try to use last returned data first
            last_data = context.user_data.get("last_accounts_data")
            if not last_data:
                # If no cached data, fetch fresh data
                all_accounts = await asyncio.to_thread(_fetch_all_accounts_tree, company_id, auth_header)
                if isinstance(all_accounts, list):
                    last_data = all_accounts
                else:
                    await update.message.reply_text("تعذر الحصول على بيانات الحسابات.")
                    return
            
            # Ensure last_data is a list
            if not isinstance(last_data, list):
                await update.message.reply_text("البيانات المحفوظة غير صالحة لإنشاء التقرير.")
                return
            
            # Create PDF report from the data
            pdf_path = await asyncio.to_thread(create_accounts_pdf_report, last_data, "تقرير الحسابات")
            # Send PDF file
            with open(pdf_path, 'rb') as pdf_file:
                await update.message.reply_document(pdf_file, filename=os.path.basename(pdf_path))
            await update.message.reply_text("تم إنشاء ملف PDF بنجاح، يمكنك تحميله من الملف المرفق.")
        except Exception as exc:
            logger.exception("PDF report generation failed")
            await update.message.reply_text(f"حدث خطأ في إنشاء التقرير: {exc}")
        return

    pending = context.user_data.get("pending_name_confirmation")
    if isinstance(pending, dict):
        if _is_yes(user_text):
            context.user_data.pop("pending_name_confirmation", None)
            final_request = str(pending.get("suggested_request", "")).strip()
        elif _is_no(user_text):
            context.user_data.pop("pending_name_confirmation", None)
            final_request = str(pending.get("original_request", "")).strip()
        else:
            await update.message.reply_text(MSG_CONFIRM_YES_NO)
            return

        await update.message.reply_text(MSG_PROCESSING)
        await update.message.chat.send_action(action="typing")
        try:
            result = await asyncio.to_thread(
                kickoff_crew,
                final_request,
                company_id,
                True,
                auth_header,
            )
            # Save data for PDF reports
            accounts_data = _extract_accounts_data(result)
            if accounts_data:
                context.user_data["last_accounts_data"] = accounts_data
            await _send_result_chunks(update.message, result)
        except Exception as exc:
            logger.exception("CrewAI run after confirmation failed")
            err_msg = f"Something went wrong: {exc}"
            for part in chunk_text_for_telegram(err_msg):
                await update.message.reply_text(part)
        return

    await update.message.reply_text(MSG_PROCESSING)
    await update.message.chat.send_action(action="typing")
    try:
        result = await asyncio.to_thread(kickoff_crew, user_text, company_id, False, auth_header)
        # Save data for PDF reports
        accounts_data = _extract_accounts_data(result)
        if accounts_data:
            context.user_data["last_accounts_data"] = accounts_data
        if (
            isinstance(result, dict)
            and result.get("status") == "needs_confirmation"
            and result.get("original_accounts_name")
            and result.get("suggested_accounts_name")
        ):
            original_name = str(result["original_accounts_name"]).strip()
            suggested_name = str(result["suggested_accounts_name"]).strip()
            context.user_data["pending_name_confirmation"] = {
                "original_request": user_text,
                "suggested_request": _build_suggested_request(user_text, original_name, suggested_name),
                "original_name": original_name,
                "suggested_name": suggested_name,
            }
            await update.message.reply_text(f"هل تقصد {suggested_name}؟\nرد بـ نعم أو لا.")
            return

        await _send_result_chunks(update.message, result)
    except Exception as exc:
        logger.exception("CrewAI run failed")
        err_msg = f"Something went wrong: {exc}"
        for part in chunk_text_for_telegram(err_msg):
            await update.message.reply_text(part)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, TelegramConflict):
        logger.critical(
            "Telegram polling conflict: another process/server is already using this BOT_TOKEN. "
            "Stop the other bot instance or revoke the token in BotFather."
        )
        context.application.stop_running()
        return
    logger.error("Unhandled error in handler", exc_info=context.error)


async def cmd_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    uid = update.effective_user.id

    if not has_login_session(uid) or not has_company_id(uid):
        await update.message.reply_text("يجب تسجيل الدخول أولاً. اضغط /start")
        return

    company_id = get_company_id(uid)
    auth_header = get_auth_header(uid)

    await update.message.chat.send_action(action="typing")

    try:
        # Fetch all accounts tree
        all_tree = await asyncio.to_thread(_fetch_all_accounts_tree, company_id, auth_header)
        await update.message.reply_text("شجرة الحسابات الكاملة:")
        for chunk in chunk_text_for_telegram(_result_to_text(all_tree)):
            await update.message.reply_text(chunk)

        # Fetch sub accounts
        sub_accounts = await asyncio.to_thread(_fetch_sub_accounts, company_id, auth_header)
        await update.message.reply_text("الحسابات الفرعية:")
        for chunk in chunk_text_for_telegram(_result_to_text(sub_accounts)):
            await update.message.reply_text(chunk)

        # Fetch sandouk accounts
        sandouk_accounts = await asyncio.to_thread(_fetch_sandouk_accounts, company_id, auth_header)
        await update.message.reply_text("حسابات الصندوق:")
        for chunk in chunk_text_for_telegram(_result_to_text(sandouk_accounts)):
            await update.message.reply_text(chunk)

    except Exception as exc:
        logger.exception("Failed to fetch accounts")
        await update.message.reply_text(f"حدث خطأ أثناء جلب الحسابات: {exc}")


def main() -> None:
    # ===================== Token Validation =====================
    token = normalize_bot_token(os.environ.get("BOT_TOKEN"))
    if not token:
        raise SystemExit(
            "BOT_TOKEN is not set. In .env use exactly one line, no spaces around '=':\n"
            "  BOT_TOKEN=123456789:AAH_your_token_from_BotFather"
        )
    if not _VALID_BOT_TOKEN.match(token):
        raise SystemExit(
            "BOT_TOKEN does not look like a Telegram bot token (expected 123456789:AAH...).\n"
            "Fix .env: remove placeholder text like YOUR_NEW_TOKEN_HERE, and use only the token."
        )
    
    # ===================== Acquire Lock =====================
    lock_manager = BotLockManager(ROOT_DIR / ".bot.lock")
    try:
        lock_manager.acquire()
    except BotLockConflictError as e:
        raise SystemExit(f"Cannot start bot: {e}")
    
    # ===================== Log Startup Diagnostics =====================
    logger.info(
        f"Bot starting: PID={os.getpid()}, hostname={socket.gethostname()}, "
        f"cwd={os.getcwd()}, polling_mode=long_polling"
    )
    
    # ===================== Setup Application =====================
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("accounts", cmd_accounts))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)
    
    # ===================== Signal Handlers for Graceful Shutdown =====================
    def signal_handler(sig: int, frame):
        """Gracefully stop the bot on SIGINT or SIGTERM."""
        logger.info(f"Received signal {sig}, shutting down gracefully...")
        lock_manager.release()
        application.stop_running()
    
    # Register signal handlers (available on all platforms)
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal
    
    # ===================== Run with Conflict Retry Logic =====================
    max_retries = 3
    retry_count = 0
    
    try:
        while retry_count < max_retries:
            try:
                application.run_polling(allowed_updates=Update.ALL_TYPES)
                break  # Clean exit
            except TelegramConflict as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(
                        f"Telegram conflict after {max_retries} retries. "
                        "Another bot instance may be running on another server/terminal with the same token."
                    )
                    raise
                
                backoff_seconds = min(2 ** (retry_count - 1), 4)  # 1s, 2s, 4s
                logger.warning(
                    f"Conflict error (attempt {retry_count}/{max_retries}): {e}. "
                    f"Retrying in {backoff_seconds}s..."
                )
                time.sleep(backoff_seconds)
                # Create new application for clean retry
                application = Application.builder().token(token).build()
                application.add_handler(CommandHandler("start", cmd_start))
                application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
                application.add_error_handler(on_error)
                # Re-register signal handlers
                signal.signal(signal.SIGINT, signal_handler)
                signal.signal(signal.SIGTERM, signal_handler)
    finally:
        lock_manager.release()


if __name__ == "__main__":
    main()
