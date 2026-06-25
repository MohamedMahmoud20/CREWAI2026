import logging
import json
import re
from datetime import date
from typing import Any

from crewai import Crew, Process

from agents.users_agent import create_users_agent
from tasks.users_tasks import create_users_task
from llm.ollama_client import local_llm
from tools.users_tools import (
    check_user_exists,
    count_users,
    count_users_per_company,
    get_admin_users,
    get_latest_users,
    get_pos_users,
    get_super_admin_users,
    get_user_by_email,
    get_user_by_id,
    get_user_statistics,
    get_users,
    get_users_by_branch,
    get_users_by_company,
    get_users_by_department,
    get_users_created_between_dates,
    search_users_by_name,
)


logger = logging.getLogger(__name__)


TOOL_MAP = {
    "count_users": count_users,
    "get_user_statistics": get_user_statistics,
    "get_users": get_users,
    "get_latest_users": get_latest_users,
    "get_users_created_between_dates": get_users_created_between_dates,
    "get_user_by_id": get_user_by_id,
    "get_user_by_email": get_user_by_email,
    "search_users_by_name": search_users_by_name,
    "get_admin_users": get_admin_users,
    "get_super_admin_users": get_super_admin_users,
    "get_pos_users": get_pos_users,
    "get_users_by_company": get_users_by_company,
    "get_users_by_branch": get_users_by_branch,
    "get_users_by_department": get_users_by_department,
    "check_user_exists": check_user_exists,
    "count_users_per_company": count_users_per_company,
}


def _chat_response(message: str) -> str:
    prompt = f"""
You are a friendly GPT-like Telegram assistant. Reply naturally in the same language as the user.
Do not query or mention the database unless the user asks for application/user data.

User: {message}
Assistant:
""".strip()
    return local_llm.generate(prompt, timeout=45).strip()


def _classify_intent(message: str) -> dict[str, Any]:
    prompt = f"""
Classify this Telegram message. Return only valid JSON.

Choose:
- "chat" if it is greeting, small talk, general conversation, thanks, help, or any normal GPT-style question not asking for database records.
- "database" only if the user clearly asks to retrieve, count, search, filter, analyze, or list users/data from the system database.

Important examples:
User: عامل اي
JSON: {{"intent": "chat"}}
User: ازيك
JSON: {{"intent": "chat"}}
User: اشرحلي يعني ايه API
JSON: {{"intent": "chat"}}
User: هات كل المستخدمين
JSON: {{"intent": "database"}}
User: هاتلي اخر 10 مستخدمين
JSON: {{"intent": "database"}}
User: كام مستخدم عندي
JSON: {{"intent": "database"}}
User: دور على مستخدم اسمه محمد
JSON: {{"intent": "database"}}

Message: {message}
JSON:
""".strip()
    try:
        result = _extract_json(local_llm.generate(prompt, timeout=30))
        intent = result.get("intent")
        if intent in {"chat", "database"}:
            return {"intent": intent}
    except Exception:
        logger.exception("Failed to classify message intent")

    return {"intent": "chat"}


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model response: {text}")
    return json.loads(match.group(0))


def _normalize_digits(text: str) -> str:
    arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return text.translate(arabic_digits)


def _first_number(text: str) -> int | None:
    text = _normalize_digits(text)
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def _extract_email(text: str) -> str | None:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
    return match.group(0) if match else None


def _extract_search_name(text: str) -> str | None:
    patterns = (
        r"(?:اسمه|اسمها|اسم|باسم|اسمه هو)\s+(.+)$",
        r"(?:name is|named|name|search for|search|find)\s+(.+)$",
        r"(?:دور على|ابحث عن|هات المستخدم)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text.strip(), flags=re.IGNORECASE)
        if match:
            name = match.group(1).strip(" .،؟?!")
            name = re.sub(r"^(?:اللي|الى|اللي اسمه|اسمه)\s+", "", name).strip(" .،؟?!")
            if name and not re.fullmatch(r"\d+", _normalize_digits(name)):
                return name
    return None


def _looks_like_database_request(question: str) -> bool:
    normalized = _normalize_digits(question).lower()
    return any(
        token in normalized
        for token in (
            "user",
            "users",
            "مستخدم",
            "المستخدم",
            "المستخدمين",
            "شركة",
            "شركه",
            "شركتهم",
            "company",
            "فرع",
            "branch",
            "قسم",
            "department",
            "admin",
            "ادمن",
            "أدمن",
            "pos",
            "كاشير",
            "اخر",
            "آخر",
            "اول",
            "أول",
            "عدد",
            "كام",
            "احص",
            "إحص",
            "id",
            "email",
            "اسم",
            "اسمه",
            "named",
            "name",
            "search",
            "find",
            "دور على",
            "ابحث عن",
        )
    )


def _apply_database_guardrails(question: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Correct obvious tool-selection mistakes without replacing natural language planning."""
    normalized = _normalize_digits(question).lower()
    number = _first_number(question)

    if number is not None:
        if any(token in normalized for token in ("company", "companyid", "company id", "شركة", "شركه", "شركتهم")):
            return {"tool": "get_users_by_company", "args": {"company_id": number, "limit": 100}}

        if any(token in normalized for token in ("branch", "branchid", "branch id", "فرع")):
            return {"tool": "get_users_by_branch", "args": {"branch_id": number, "limit": 100}}

        if any(token in normalized for token in ("department", "departmentid", "department id", "dep", "قسم")):
            return {"tool": "get_users_by_department", "args": {"department_id": number, "limit": 100}}

        if any(token in normalized for token in ("user id", "userid", "id بتاعه", "id بتاع", "رقمه", "رقم المستخدم")):
            return {"tool": "get_user_by_id", "args": {"user_id": number}}

        if "id" in normalized and any(token in normalized for token in ("user", "مستخدم", "المستخدم")):
            return {"tool": "get_user_by_id", "args": {"user_id": number}}

    return plan


def _fast_database_plan(question: str) -> dict[str, Any] | None:
    normalized = _normalize_digits(question).lower()
    number = _first_number(question)

    email = _extract_email(question)
    if email:
        return {"tool": "get_user_by_email", "args": {"email": email}}

    search_name = _extract_search_name(question)
    if search_name and any(token in normalized for token in ("اسم", "اسمه", "name", "named", "search", "find", "دور", "ابحث")):
        return {"tool": "search_users_by_name", "args": {"name": search_name, "limit": 20}}

    if number is not None:
        guarded = _apply_database_guardrails(question, {"tool": "get_users", "args": {"limit": 10, "order": "latest"}})
        if guarded["tool"] != "get_users":
            return guarded

    if any(token in normalized for token in ("عدد", "كام", "how many", "count")) and any(
        token in normalized for token in ("user", "users", "مستخدم", "المستخدمين")
    ):
        return {"tool": "count_users", "args": {}}

    if any(token in normalized for token in ("احص", "إحص", "statistics", "stats")):
        return {"tool": "get_user_statistics", "args": {}}

    if any(token in normalized for token in ("اخر", "آخر", "latest", "new users")) and any(
        token in normalized for token in ("user", "users", "مستخدم", "المستخدمين")
    ):
        return {"tool": "get_latest_users", "args": {"limit": number or 10}}

    if any(token in normalized for token in ("اول", "أول", "first")) and any(
        token in normalized for token in ("user", "users", "مستخدم", "المستخدمين")
    ):
        return {"tool": "get_users", "args": {"limit": number or 10, "order": "oldest"}}

    if any(token in normalized for token in ("كل", "all")) and any(
        token in normalized for token in ("user", "users", "مستخدم", "المستخدمين")
    ):
        return {"tool": "get_users", "args": {"limit": number or 10, "order": "latest"}}

    return None


def _date_only(value: Any) -> str:
    if not value:
        return "غير محدد"
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def _plan_tool_call(question: str) -> dict[str, Any]:
    fast_plan = _fast_database_plan(question)
    if fast_plan is not None:
        return fast_plan

    today = date.today().isoformat()
    prompt = f"""
You are a database tool planner for a users table. Convert the user's Arabic or English request into exactly one JSON object.

Return only valid JSON, no markdown, no explanation.

Available tools and args:
- count_users {{}}
- get_user_statistics {{}}
- get_users {{"limit": number, "order": "latest" | "oldest" | "name"}}
- get_latest_users {{"limit": number}}
- get_users_created_between_dates {{"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "limit": number}}
- get_user_by_id {{"user_id": number}}
- get_user_by_email {{"email": string}}
- search_users_by_name {{"name": string, "limit": number}}
- get_admin_users {{"limit": number}}
- get_super_admin_users {{"limit": number}}
- get_pos_users {{"limit": number}}
- get_users_by_company {{"company_id": number, "limit": number}}
- get_users_by_branch {{"branch_id": number, "limit": number}}
- get_users_by_department {{"department_id": number, "limit": number}}
- check_user_exists {{"user_id": number}} or {{"email": string}}
- count_users_per_company {{"limit": number}}

Rules:
- If the user asks for all users, use get_users with limit 10 unless the user gives another number.
- If the user says first users / اول مستخدمين, use get_users order oldest.
- If the user says latest / اخر / آخر, use get_latest_users.
- If the user says today / انهارده / النهاردة, use today's date: {today}.
- If the user mentions company / شركة / شركتهم with a number, use get_users_by_company and pass that number as company_id.
- If the user mentions branch / فرع with a number, use get_users_by_branch and pass that number as branch_id.
- If the user mentions department / قسم with a number, use get_users_by_department and pass that number as department_id.
- If the user mentions a user id, like "id بتاعه 3" or "user id 3", use get_user_by_id.
- Never invent arguments. If a required id/email/name is missing, use get_users with limit 10.

Examples:
User: هات كل المستخدمين
JSON: {{"tool": "get_users", "args": {{"limit": 10, "order": "latest"}}}}
User: هات اول عشرة بس
JSON: {{"tool": "get_users", "args": {{"limit": 10, "order": "oldest"}}}}
User: هاتلي اللي اتعملو جديد انهارده
JSON: {{"tool": "get_users_created_between_dates", "args": {{"start_date": "{today}", "end_date": "{today}", "limit": 20}}}}
User: هاتلي اخر 10 مستخدمين
JSON: {{"tool": "get_latest_users", "args": {{"limit": 10}}}}
User: انا عايز المستخدمين اللي id شركتهم 19
JSON: {{"tool": "get_users_by_company", "args": {{"company_id": 19, "limit": 100}}}}
User: هات مستخدمين الشركة 15
JSON: {{"tool": "get_users_by_company", "args": {{"company_id": 15, "limit": 100}}}}
User: عايز المستخدم اللي id بتاعه 3
JSON: {{"tool": "get_user_by_id", "args": {{"user_id": 3}}}}

User request: {question}
JSON:
""".strip()
    plan = _extract_json(local_llm.generate(prompt, timeout=45))
    tool_name = plan.get("tool")
    if tool_name not in TOOL_MAP:
        raise ValueError(f"Unsupported tool selected: {tool_name}")
    args = plan.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError("Tool args must be a JSON object")
    return _apply_database_guardrails(question, {"tool": tool_name, "args": args})


def _summarize_result(question: str, result: dict[str, Any]) -> str:
    if not result.get("success"):
        return f"حصل خطأ أثناء جلب البيانات: {result.get('message')}\n{result.get('error', '')}".strip()

    data = result.get("data")
    if data is None:
        return "مفيش بيانات مطابقة للطلب."

    if isinstance(data, list):
        if not data:
            return "مفيش مستخدمين مطابقين للطلب."

        lines = [f"لقيت {len(data)} مستخدم:"]
        for index, user in enumerate(data, start=1):
            if not isinstance(user, dict):
                lines.append(f"{index}. {user}")
                continue
            summary = {
                "id": user.get("id"),
                "name": user.get("name"),
                "bransh_id": user.get("bransh_id"),
                "is_admin": user.get("is_admin"),
                "is_super_admin": user.get("is_super_admin"),
            }
            lines.append(f"{index}. {json.dumps(summary, ensure_ascii=False, default=str)}")
        return "\n".join(lines)

    if isinstance(data, dict):
        if set(data.keys()) == {"total_users"}:
            return f"عدد المستخدمين: {data['total_users']}"
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)

    return str(data)


def create_users_crew(question: str, **kwargs: Any) -> Crew:
    """
    Create a complete CrewAI configuration for the Users module.

    The crew uses a sequential process with one domain-specialized agent. This
    is intentionally simple and production-friendly for read-only database
    assistance: the LLM plans, chooses approved tools, and produces a final
    user-facing answer.
    """
    logger.info("Creating Users Crew")
    verbose = bool(kwargs.get("verbose", False))
    agent = kwargs.get("agent") or create_users_agent(verbose=verbose)
    task = create_users_task(question)
    task.agent = agent

    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=verbose,
        tracing=False,
    )


def ask_users_crew(question: str) -> str:
    """
    Execute the Users Crew for a natural-language question.

    Args:
        question: User question in Arabic or English.

    Returns:
        The final CrewAI answer as text.
    """
    if not _looks_like_database_request(question):
        return _chat_response(question)

    plan = _plan_tool_call(question)
    tool = TOOL_MAP[plan["tool"]]
    result = tool.run(**plan["args"])
    return _summarize_result(question, result)
