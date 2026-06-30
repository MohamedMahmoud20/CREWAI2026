import json
import logging
import re
from typing import Any

from crewai import Crew, Process

from agents.accounts_agent import create_accounts_agent
from llm.ollama_client import local_llm
from tasks.accounts_tasks import create_accounts_task
from tools.accounts_tools import (
    count_accounts,
    execute_confirmed_account_update,
    execute_readonly_sql,
    get_account_by_code,
    get_account_by_id,
    get_account_statistics,
    get_account_tree,
    get_accounts,
    get_accounts_by_company,
    get_cash_accounts,
    get_child_accounts,
    get_customer_accounts,
    get_distributor_accounts,
    get_employee_accounts,
    get_inactive_accounts,
    get_main_accounts,
    get_parent_account,
    search_accounts_by_name,
)


logger = logging.getLogger(__name__)


TOOL_MAP = {
    "count_accounts": count_accounts,
    "get_account_statistics": get_account_statistics,
    "get_accounts": get_accounts,
    "get_account_by_id": get_account_by_id,
    "get_account_by_code": get_account_by_code,
    "search_accounts_by_name": search_accounts_by_name,
    "get_main_accounts": get_main_accounts,
    "get_customer_accounts": get_customer_accounts,
    "get_employee_accounts": get_employee_accounts,
    "get_distributor_accounts": get_distributor_accounts,
    "get_cash_accounts": get_cash_accounts,
    "get_inactive_accounts": get_inactive_accounts,
    "get_accounts_by_company": get_accounts_by_company,
    "get_child_accounts": get_child_accounts,
    "get_parent_account": get_parent_account,
    "get_account_tree": get_account_tree,
    "execute_readonly_sql": execute_readonly_sql,
    "execute_confirmed_account_update": execute_confirmed_account_update,
}

WRITE_REQUEST_TOKENS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "replace",
    "merge",
    "grant",
    "revoke",
    "اضف",
    "أضف",
    "ضيف",
    "عدل",
    "تعديل",
    "احذف",
    "حذف",
    "امسح",
    "مسح",
    "انشئ",
    "أنشئ",
)

FORBIDDEN_WRITE_TOKENS = (
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "replace",
    "merge",
    "grant",
    "revoke",
    "احذف",
    "حذف",
    "امسح",
    "مسح",
    "انشئ",
    "أنشئ",
)


def _chat_response(message: str) -> str:
    prompt = f"""
أنت مساعد محاسبي عربي متخصص في شجرة الحسابات.
رد بالعربية فقط وباختصار. لا تذكر قاعدة البيانات إلا إذا كان السؤال يطلب بيانات حسابات.

رسالة المستخدم:
{message}

الرد:
""".strip()
    return local_llm.generate(prompt, timeout=45).strip()


def _normalize_digits(text: str) -> str:
    arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return text.translate(arabic_digits)


def _first_number(text: str) -> int | None:
    match = re.search(r"\d+", _normalize_digits(text))
    return int(match.group(0)) if match else None


def _extract_explicit_account_id(text: str) -> int | None:
    normalized = _normalize_digits(text)
    patterns = (
        r"(?:id|ID)\s*[:#]?\s*(\d+)",
        r"(?:رقم الحساب|حساب رقم|الحساب رقم|رقم)\s*[:#]?\s*(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _sql_quote(value: str) -> str:
    return value.replace("'", "''")


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model response: {text}")
    return json.loads(match.group(0))


def _extract_account_code(text: str) -> str | None:
    match = re.search(r"(?:كود|code)\s*[:#]?\s*([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _extract_search_name(text: str) -> str | None:
    patterns = (
        r"(?:حساب اسمه|اسم الحساب|اسمه|اسم|باسم)\s+(.+)$",
        r"(?:ابحث عن حساب|دور على حساب|هات حساب)\s+(.+)$",
        r"(?:account named|account name|named|search for|search|find)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text.strip(), flags=re.IGNORECASE)
        if match:
            name = match.group(1).strip(" .،؟?!")
            name = re.sub(r"^(?:اللي|الى|اللي اسمه|اسمه)\s+", "", name).strip(" .،؟?!")
            if name and not re.fullmatch(r"\d+", _normalize_digits(name)):
                return name
    return None


def _extract_word_filter(text: str) -> str | None:
    patterns = (
        r"(?:فيها كلمة|فيها كلمه|فيهم كلمة|فيهم كلمه|تحتوي على|بتحتوي على|contains)\s+(.+)$",
        r"(?:كلمة|كلمه)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text.strip(), flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .،؟?!")
            value = re.sub(r"^(?:كلمة|كلمه)\s+", "", value).strip(" .،؟?!")
            if value:
                return value
    return None


def _extract_sql(text: str) -> str:
    text = text.strip()
    try:
        data = _extract_json(text)
        sql = data.get("sql") or data.get("query")
        if isinstance(sql, str) and sql.strip():
            return sql.strip()
    except Exception:
        pass

    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    match = re.search(r"\bselect\b.*", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()

    raise ValueError(f"No SELECT SQL found in model response: {text}")


def _is_safe_select_sql(sql: str) -> bool:
    normalized = sql.strip().lower()
    forbidden = (
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "truncate",
        "create",
        "replace",
        "merge",
        "grant",
        "revoke",
    )
    return (
        normalized.startswith("select")
        and "accounts" in normalized
        and not re.search(r"\busers\b", normalized)
        and not any(re.search(rf"\b{re.escape(token)}\b", normalized) for token in forbidden)
    )


def _fallback_sql_for_question(question: str) -> str:
    normalized = _normalize_digits(question).lower()
    number = _first_number(question)
    wants_count = any(token in normalized for token in ("عدد", "كام", "how many", "count"))
    word_filter = _extract_word_filter(question)

    if word_filter:
        escaped = word_filter.replace("'", "''")
        if wants_count:
            return f"SELECT COUNT(*) AS count FROM accounts WHERE accounts_name ILIKE '%{escaped}%';"
        return f"SELECT * FROM accounts WHERE accounts_name ILIKE '%{escaped}%' LIMIT 50;"

    if any(token in normalized for token in ("موبايلها فاضي", "موبايل فاضي", "بدون موبايل", "mobile empty", "empty mobile")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_mobile IS NULL OR accounts_mobile = '';"
        return "SELECT * FROM accounts WHERE accounts_mobile IS NULL OR accounts_mobile = '' LIMIT 50;"

    if number is not None and any(token in normalized for token in ("ابناء", "أبناء", "children", "child")):
        return f"SELECT * FROM accounts WHERE accounts_fatherid = {number} LIMIT 50;"

    if number is not None and ("id" in normalized or "رقم" in normalized):
        return f"SELECT * FROM accounts WHERE id = {number} LIMIT 1;"

    if any(token in normalized for token in ("رئيسية", "الرئيسية", "رئيسيه", "الرئيسيه", "main")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_ismain = true;"
        return "SELECT * FROM accounts WHERE accounts_ismain = true LIMIT 50;"

    if any(token in normalized for token in ("فرعية", "الفرعية", "فرعيه", "الفرعيه", "sub")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE COALESCE(accounts_ismain, false) = false;"
        return "SELECT * FROM accounts WHERE COALESCE(accounts_ismain, false) = false LIMIT 50;"

    if any(token in normalized for token in ("عملاء", "عميل", "customers", "clients")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_isclient = true;"
        return "SELECT * FROM accounts WHERE accounts_isclient = true LIMIT 50;"

    if any(token in normalized for token in ("موظفين", "موظف", "employees")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_isemp = true;"
        return "SELECT * FROM accounts WHERE accounts_isemp = true LIMIT 50;"

    if any(token in normalized for token in ("موزعين", "موزع", "distributors")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_isdistributor = true;"
        return "SELECT * FROM accounts WHERE accounts_isdistributor = true LIMIT 50;"

    if any(token in normalized for token in ("خزن", "خزنة", "خزينه", "صندوق", "cash", "treasury")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_issandouk = true;"
        return "SELECT * FROM accounts WHERE accounts_issandouk = true LIMIT 50;"

    if any(token in normalized for token in ("غير نشط", "غير نشطة", "غير النشطة", "معطل", "inactive")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_isnotactive = true;"
        return "SELECT * FROM accounts WHERE accounts_isnotactive = true LIMIT 50;"

    if wants_count:
        return "SELECT COUNT(*) AS count FROM accounts;"

    return "SELECT * FROM accounts LIMIT 50;"


def _direct_sql_for_question(question: str) -> str | None:
    normalized = _normalize_digits(question).lower()
    number = _first_number(question)
    limit = number or 50
    wants_count = any(token in normalized for token in ("عدد", "كام", "how many", "count"))
    word_filter = _extract_word_filter(question)

    if word_filter:
        escaped = word_filter.replace("'", "''")
        if wants_count:
            return f"SELECT COUNT(*) AS count FROM accounts WHERE accounts_name ILIKE '%{escaped}%';"
        return f"SELECT * FROM accounts WHERE accounts_name ILIKE '%{escaped}%' LIMIT 50;"

    if any(token in normalized for token in ("موبايلها فاضي", "موبايل فاضي", "بدون موبايل", "mobile empty", "empty mobile")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_mobile IS NULL OR accounts_mobile = '';"
        return "SELECT * FROM accounts WHERE accounts_mobile IS NULL OR accounts_mobile = '' LIMIT 50;"

    if any(token in normalized for token in ("فرعية", "الفرعية", "فرعيه", "الفرعيه", "فرعي", "sub")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE COALESCE(accounts_ismain, false) = false;"
        return (
            "SELECT * FROM accounts "
            "WHERE COALESCE(accounts_ismain, false) = false "
            f"ORDER BY id ASC LIMIT {limit};"
        )

    if any(token in normalized for token in ("رئيسية", "الرئيسية", "رئيسيه", "الرئيسيه", "رئيسي", "main")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_ismain = true;"
        return f"SELECT * FROM accounts WHERE accounts_ismain = true ORDER BY id ASC LIMIT {limit};"

    if any(token in normalized for token in ("عملاء", "عميل", "customers", "clients")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_isclient = true;"
        return f"SELECT * FROM accounts WHERE accounts_isclient = true ORDER BY id ASC LIMIT {limit};"

    if any(token in normalized for token in ("موظفين", "موظف", "employees")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_isemp = true;"
        return f"SELECT * FROM accounts WHERE accounts_isemp = true ORDER BY id ASC LIMIT {limit};"

    if any(token in normalized for token in ("موزعين", "موزع", "distributors")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_isdistributor = true;"
        return f"SELECT * FROM accounts WHERE accounts_isdistributor = true ORDER BY id ASC LIMIT {limit};"

    if any(token in normalized for token in ("خزن", "خزنة", "خزينه", "صندوق", "cash", "treasury")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_issandouk = true;"
        return f"SELECT * FROM accounts WHERE accounts_issandouk = true ORDER BY id ASC LIMIT {limit};"

    if any(token in normalized for token in ("غير نشط", "غير نشطة", "غير النشطة", "معطل", "inactive")):
        if wants_count:
            return "SELECT COUNT(*) AS count FROM accounts WHERE accounts_isnotactive = true;"
        return f"SELECT * FROM accounts WHERE accounts_isnotactive = true ORDER BY id ASC LIMIT {limit};"

    return None


def _generate_sql_for_question(question: str) -> str:
    direct_sql = _direct_sql_for_question(question)
    if direct_sql:
        return direct_sql

    prompt = f"""
أنت محول أسئلة عربية إلى PostgreSQL SELECT فقط.
ارجع JSON فقط بالشكل: {{"sql": "..."}}

الجدول الوحيد المسموح:
accounts

مهم جدا:
- لا تستخدم users أبدا.
- لا ترجع أي كلام غير JSON.
- لا تستخدم إلا SELECT.
- ممنوع INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE/REPLACE/MERGE/GRANT/REVOKE.
- لو الاستعلام يرجع قائمة، ضع LIMIT 50 إلا لو المستخدم طلب رقم مختلف.
- لو السؤال عن عدد، استخدم SELECT COUNT(*) AS count.
- البحث النصي يكون بـ ILIKE.
- كلمة/كلمه/فيها/فيهم معناها غالبا بحث في accounts_name.

معاني الأعمدة:
- accounts_ismain = حساب رئيسي
- accounts_fatherid = الحساب الأب / أبناء الحساب
- accounts_isclient = حساب عميل
- accounts_isemp = حساب موظف
- accounts_isdistributor = حساب موزع
- accounts_issandouk = حساب صندوق أو خزنة
- accounts_isnotactive = حساب غير نشط
- accounts_mobile = موبايل
- accounts_address = عنوان
- accounts_notes = ملاحظات
- "companyId" = الشركة
- "createdAt" = تاريخ الإنشاء
- "updatedAt" = تاريخ التحديث

أمثلة:
السؤال: عدد الحسابات اللي فيها كلمه مباني
{{"sql": "SELECT COUNT(*) AS count FROM accounts WHERE accounts_name ILIKE '%مباني%';"}}

السؤال: هات الحسابات اللي فيها كلمة الامل
{{"sql": "SELECT * FROM accounts WHERE accounts_name ILIKE '%الامل%' LIMIT 50;"}}

السؤال: هات الحسابات اللي موبايلها فاضي
{{"sql": "SELECT * FROM accounts WHERE accounts_mobile IS NULL OR accounts_mobile = '' LIMIT 50;"}}

السؤال: عدد الحسابات الرئيسيه
{{"sql": "SELECT COUNT(*) AS count FROM accounts WHERE accounts_ismain = true;"}}

السؤال: هات أبناء الحساب رقم 10
{{"sql": "SELECT * FROM accounts WHERE accounts_fatherid = 10 LIMIT 50;"}}

السؤال:
{question}
""".strip()

    try:
        sql = _extract_sql(local_llm.generate(prompt, timeout=45))
        if _is_safe_select_sql(sql):
            return sql
        logger.warning("Rejected generated SQL, using fallback: %s", sql)
    except Exception:
        logger.exception("Failed to generate dynamic SQL, using fallback")

    return _fallback_sql_for_question(question)


def _is_write_request(question: str) -> bool:
    normalized = question.lower()
    return any(re.search(rf"\b{re.escape(token)}\b", normalized) for token in WRITE_REQUEST_TOKENS[:11]) or any(
        token in normalized for token in WRITE_REQUEST_TOKENS[11:]
    )


def is_forbidden_account_write_request(question: str) -> bool:
    normalized = question.lower()
    return any(re.search(rf"\b{re.escape(token)}\b", normalized) for token in FORBIDDEN_WRITE_TOKENS[:9]) or any(
        token in normalized for token in FORBIDDEN_WRITE_TOKENS[9:]
    )


def is_account_update_request(question: str) -> bool:
    normalized = _normalize_digits(question).lower()
    update_tokens = (
        "update",
        "غير",
        "غيّر",
        "عدل",
        "تعديل",
        "بدل",
        "حط",
        "خلي",
        "deactivate",
        "عطل",
        "عطّل",
        "تعطيل",
        "وقف",
        "اوقف",
        "أوقف",
    )
    account_tokens = ("حساب", "الحساب", "accounts", "account")
    return any(token in normalized for token in update_tokens) and any(token in normalized for token in account_tokens)


def _extract_update_value(question: str) -> str | None:
    parts = re.split(r"\s+(?:إلى|الى|الي|إلي|لـ|to)\s+", question.strip(), flags=re.IGNORECASE)
    if len(parts) > 1:
        value = parts[-1].strip(" .،؟?!")
        if value:
            return value
    return None


def create_account_update_proposal(question: str) -> dict[str, Any]:
    normalized = _normalize_digits(question).lower()
    account_id = _extract_explicit_account_id(question)
    if account_id is None:
        return {
            "success": False,
            "message": (
                "من فضلك اكتب رقم الحساب ID المطلوب تحديثه حتى لا يتم تعديل حساب بالخطأ.\n"
                "مثال: غير اسم الحساب رقم 15 إلى رأس المال3"
            ),
            "data": None,
        }

    column: str | None = None
    value: Any = None
    description: str | None = None

    if any(token in normalized for token in ("عطل", "عطّل", "تعطيل", "وقف", "اوقف", "أوقف", "deactivate", "غير نشط")):
        column = "accounts_isnotactive"
        value = True
        description = "سيتم تعطيل الحساب وجعله غير نشط."
    elif any(token in normalized for token in ("موبايل", "هاتف", "mobile", "phone")):
        column = "accounts_mobile"
        value = _extract_update_value(question)
        description = f"سيتم تغيير رقم موبايل الحساب إلى: {value}"
    elif any(token in normalized for token in ("عنوان", "address")):
        column = "accounts_address"
        value = _extract_update_value(question)
        description = f"سيتم تغيير عنوان الحساب إلى: {value}"
    elif any(token in normalized for token in ("اسم", "name")):
        column = "accounts_name"
        value = _extract_update_value(question)
        description = f"سيتم تغيير اسم الحساب إلى: {value}"

    if not column:
        return {
            "success": False,
            "message": "نوع التحديث غير واضح. المتاح حاليا: الاسم، الموبايل، العنوان، أو تعطيل الحساب.",
            "data": None,
        }
    if value is None or value == "":
        return {
            "success": False,
            "message": "القيمة الجديدة غير واضحة. اكتبها بعد كلمة إلى، مثال: غير موبايل الحساب رقم 10 إلى 01000000000",
            "data": None,
        }

    if isinstance(value, bool):
        sql_value = "true" if value else "false"
    else:
        sql_value = f"'{_sql_quote(str(value))}'"

    sql = f"UPDATE accounts\nSET {column} = {sql_value}\nWHERE id = {account_id};"
    return {
        "success": True,
        "message": (
            "التغيير التالي يحتاج تأكيد قبل التنفيذ:\n\n"
            f"{description}\n"
            f"Account ID: {account_id}\n\n"
            "SQL:\n"
            f"{sql}\n\n"
            "للتنفيذ اكتب: تأكيد\n"
            "للإلغاء اكتب: إلغاء"
        ),
        "data": {"sql": sql, "account_id": account_id, "description": description},
    }


def execute_confirmed_account_update_sql(sql: str) -> str:
    result = execute_confirmed_account_update.run(sql=sql)
    if not result.get("success"):
        return "لم يتم تنفيذ التحديث. العملية مرفوضة أو حدث خطأ أثناء التنفيذ."
    data = result.get("data") or {}
    return f"تم تنفيذ التحديث بنجاح. عدد السجلات التي تم تعديلها: {data.get('affected_rows', 0)}"


def _looks_like_accounts_request(question: str) -> bool:
    normalized = _normalize_digits(question).lower()
    return any(
        token in normalized
        for token in (
            "account",
            "accounts",
            "حساب",
            "الحساب",
            "الحسابات",
            "شجرة",
            "هيكل",
            "رئيسية",
            "رئيسي",
            "فرعية",
            "فرعي",
            "عميل",
            "عملاء",
            "موظف",
            "موظفين",
            "موزع",
            "موزعين",
            "خزنة",
            "خزن",
            "صندوق",
            "غير نشط",
            "معطل",
            "كود",
            "code",
            "موبايل",
            "هاتف",
            "عنوان",
            "ملاحظات",
            "ضريبة",
            "سعر",
            "خصم",
            "mobile",
            "address",
            "notes",
            "tax",
            "price",
            "discount",
            "عدد",
            "كام",
            "احص",
            "إحص",
        )
    )


def _fast_database_plan(question: str) -> dict[str, Any] | None:
    normalized = _normalize_digits(question).lower()
    number = _first_number(question)

    account_code = _extract_account_code(question)
    if account_code:
        return {"tool": "get_account_by_code", "args": {"account_code": account_code}}

    word_filter = _extract_word_filter(question)
    if word_filter and any(token in normalized for token in ("حساب", "account", "اسم", "كلمة")):
        return {
            "tool": "execute_readonly_sql",
            "args": {
                "sql": (
                    "SELECT *\n"
                    "FROM accounts\n"
                    f"WHERE accounts_name ILIKE '%{word_filter.replace("'", "''")}%' \n"
                    "LIMIT 50;"
                )
            },
        }

    if any(token in normalized for token in ("موبايلها فاضي", "موبايل فاضي", "بدون موبايل", "mobile empty", "empty mobile")):
        return {
            "tool": "execute_readonly_sql",
            "args": {
                "sql": (
                    "SELECT *\n"
                    "FROM accounts\n"
                    "WHERE accounts_mobile IS NULL\n"
                    "OR accounts_mobile = ''\n"
                    "LIMIT 50;"
                )
            },
        }

    if number is not None:
        if any(token in normalized for token in ("ابناء", "أبناء", "children", "child", "الحسابات الفرعية", "فروع الحساب")):
            return {"tool": "get_child_accounts", "args": {"parent_id": number, "limit": 100}}
        if any(token in normalized for token in ("الاب", "الأب", "parent", "الحساب الرئيسي للحساب")):
            return {"tool": "get_parent_account", "args": {"account_id": number}}
        if any(token in normalized for token in ("شجرة", "tree", "hierarchy", "هيكل")):
            return {"tool": "get_account_tree", "args": {"root_id": number, "limit": 200}}
        if any(token in normalized for token in ("company", "companyid", "company id", "شركة", "شركه")):
            return {"tool": "get_accounts_by_company", "args": {"company_id": number, "limit": 100}}
        if "id" in normalized or "رقم" in normalized:
            return {"tool": "get_account_by_id", "args": {"account_id": number}}

    search_name = _extract_search_name(question)
    if search_name:
        return {"tool": "search_accounts_by_name", "args": {"name": search_name, "limit": 20}}

    wants_count = any(token in normalized for token in ("عدد", "كام", "how many", "count"))

    if wants_count and any(token in normalized for token in ("رئيسية", "الرئيسية", "رئيسيه", "الرئيسيه", "main")):
        return {
            "tool": "execute_readonly_sql",
            "args": {
                "sql": (
                    "SELECT COUNT(*) AS total_main_accounts\n"
                    "FROM accounts\n"
                    "WHERE accounts_ismain = true;"
                )
            },
        }

    if wants_count and any(token in normalized for token in ("فرعية", "الفرعية", "فرعيه", "الفرعيه", "sub")):
        return {
            "tool": "execute_readonly_sql",
            "args": {
                "sql": (
                    "SELECT COUNT(*) AS total_sub_accounts\n"
                    "FROM accounts\n"
                    "WHERE COALESCE(accounts_ismain, false) = false;"
                )
            },
        }

    if wants_count and any(token in normalized for token in ("عملاء", "عميل", "customers", "clients")):
        return {
            "tool": "execute_readonly_sql",
            "args": {
                "sql": "SELECT COUNT(*) AS total_customer_accounts FROM accounts WHERE accounts_isclient = true;"
            },
        }

    if wants_count and any(token in normalized for token in ("موظفين", "موظف", "employees")):
        return {
            "tool": "execute_readonly_sql",
            "args": {
                "sql": "SELECT COUNT(*) AS total_employee_accounts FROM accounts WHERE accounts_isemp = true;"
            },
        }

    if wants_count and any(token in normalized for token in ("موزعين", "موزع", "distributors")):
        return {
            "tool": "execute_readonly_sql",
            "args": {
                "sql": "SELECT COUNT(*) AS total_distributor_accounts FROM accounts WHERE accounts_isdistributor = true;"
            },
        }

    if wants_count and any(token in normalized for token in ("خزن", "خزنة", "خزينه", "صندوق", "cash", "treasury")):
        return {
            "tool": "execute_readonly_sql",
            "args": {
                "sql": "SELECT COUNT(*) AS total_cash_accounts FROM accounts WHERE accounts_issandouk = true;"
            },
        }

    if wants_count and any(token in normalized for token in ("غير نشط", "غير نشطة", "غير النشطة", "معطل", "inactive")):
        return {
            "tool": "execute_readonly_sql",
            "args": {
                "sql": "SELECT COUNT(*) AS total_inactive_accounts FROM accounts WHERE accounts_isnotactive = true;"
            },
        }

    if any(token in normalized for token in ("عدد", "كام", "how many", "count")):
        if any(token in normalized for token in ("احص", "إحص", "statistics", "stats", "تفصيل")):
            return {"tool": "get_account_statistics", "args": {}}
        return {"tool": "count_accounts", "args": {}}

    if any(token in normalized for token in ("احص", "إحص", "statistics", "stats")):
        return {"tool": "get_account_statistics", "args": {}}

    if any(token in normalized for token in ("شجرة", "tree", "hierarchy", "هيكل")):
        return {"tool": "get_account_tree", "args": {"root_id": None, "limit": 200}}

    if any(token in normalized for token in ("رئيسية", "الرئيسية", "main")):
        return {"tool": "get_main_accounts", "args": {"limit": number or 100}}

    if any(token in normalized for token in ("غير نشط", "غير نشطة", "غير النشطة", "معطل", "inactive")):
        return {"tool": "get_inactive_accounts", "args": {"limit": number or 100}}

    if any(token in normalized for token in ("عملاء", "عميل", "customers", "clients")):
        return {"tool": "get_customer_accounts", "args": {"limit": number or 100}}

    if any(token in normalized for token in ("موظفين", "موظف", "employees")):
        return {"tool": "get_employee_accounts", "args": {"limit": number or 100}}

    if any(token in normalized for token in ("موزعين", "موزع", "distributors")):
        return {"tool": "get_distributor_accounts", "args": {"limit": number or 100}}

    if any(token in normalized for token in ("خزن", "خزنة", "خزينه", "صندوق", "cash", "treasury")):
        return {"tool": "get_cash_accounts", "args": {"limit": number or 100}}

    if any(token in normalized for token in ("كل", "all", "list", "هات")) and any(
        token in normalized for token in ("حساب", "account")
    ):
        return {"tool": "get_accounts", "args": {"limit": number or 100, "order": "code"}}

    return None


def _plan_tool_call(question: str) -> dict[str, Any]:
    return {"tool": "execute_readonly_sql", "args": {"sql": _generate_sql_for_question(question)}}


def _format_account(account: dict[str, Any]) -> str:
    name = account.get("accounts_name") or "بدون اسم"
    account_id = account.get("id")
    flags = []
    if account.get("accounts_ismain"):
        flags.append("رئيسي")
    else:
        flags.append("فرعي")
    if account.get("accounts_isclient"):
        flags.append("عميل")
    if account.get("accounts_isemp"):
        flags.append("موظف")
    if account.get("accounts_isdistributor"):
        flags.append("موزع")
    if account.get("accounts_issandouk"):
        flags.append("خزنة")
    if account.get("accounts_isnotactive"):
        flags.append("غير نشط")
    suffix = "، ".join(flags) if flags else "غير محدد"
    return f"Id: {account_id} | {name} | {suffix}"


def _summarize_result(result: dict[str, Any]) -> str:
    if not result.get("success"):
        return "حدث خطأ أثناء جلب البيانات. حاول مرة أخرى أو حدّد الطلب بشكل أوضح."

    data = result.get("data")
    if data is None:
        return "لا توجد بيانات مطابقة للطلب."

    if isinstance(data, list):
        if not data:
            return "لا توجد حسابات مطابقة للطلب."
        if len(data) == 1 and isinstance(data[0], dict) and "count" in data[0]:
            return f"العدد: {data[0]['count']}"
        if len(data) == 1 and isinstance(data[0], dict):
            count_items = [(key, value) for key, value in data[0].items() if key.startswith("total_")]
            if len(count_items) == 1:
                return f"العدد: {count_items[0][1]}"
        lines = [f"تم العثور على {len(data)} حساب:"]
        for index, account in enumerate(data, start=1):
            if isinstance(account, dict):
                if "accounts_name" in account or "accounts_code" in account:
                    indent = "  " * int(account.get("level") or 0)
                    lines.append(f"{index}. {indent}{_format_account(account)}")
                else:
                    lines.append(f"{index}. {json.dumps(account, ensure_ascii=False, default=str)}")
            else:
                lines.append(f"{index}. {account}")
        return "\n".join(lines)

    if isinstance(data, dict):
        if set(data.keys()) == {"total_accounts"}:
            return f"عدد الحسابات: {data['total_accounts']}"
        if "total_accounts" in data:
            labels = {
                "total_accounts": "إجمالي الحسابات",
                "main_accounts": "الحسابات الرئيسية",
                "sub_accounts": "الحسابات الفرعية",
                "customer_accounts": "حسابات العملاء",
                "employee_accounts": "حسابات الموظفين",
                "distributor_accounts": "حسابات الموزعين",
                "cash_accounts": "حسابات الخزن",
                "inactive_accounts": "الحسابات غير النشطة",
                "companies_count": "عدد الشركات",
                "account_types_count": "عدد أنواع الحسابات",
            }
            return "\n".join(f"{labels.get(key, key)}: {value}" for key, value in data.items())
        return _format_account(data)

    return str(data)


def create_accounts_crew(question: str, **kwargs: Any) -> Crew:
    logger.info("Creating Accounts Crew")
    verbose = bool(kwargs.get("verbose", False))
    agent = kwargs.get("agent") or create_accounts_agent(verbose=verbose)
    task = create_accounts_task(question)
    task.agent = agent
    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=verbose,
        tracing=False,
    )


def ask_accounts_crew(question: str) -> str:
    if is_forbidden_account_write_request(question):
        return "هذه العملية غير مسموح بها. لا يمكن حذف البيانات أو تعديل بنية قاعدة البيانات."

    if is_account_update_request(question):
        proposal = create_account_update_proposal(question)
        return proposal["message"]

    if not _looks_like_accounts_request(question):
        return _chat_response(question)

    plan = _plan_tool_call(question)
    tool = TOOL_MAP[plan["tool"]]
    result = tool.run(**plan["args"])
    return _summarize_result(result)
