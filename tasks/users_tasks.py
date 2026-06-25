import logging

from crewai import Task

from agents.users_agent import create_users_agent


logger = logging.getLogger(__name__)


def create_user_lookup_task(question: str) -> Task:
    """Create a task for finding users by ID, email, name, or existence checks."""
    return Task(
        description=(
            "Handle this user lookup request safely: {question}\n"
            "Choose the most specific lookup tool available. Do not expose raw SQL."
        ).format(question=question),
        expected_output=(
            "A concise Arabic or English answer matching the user's language, "
            "including the matched user fields returned by the tool and a clear "
            "not-found message when applicable."
        ),
        agent=create_users_agent(),
    )


def create_user_reporting_task(question: str) -> Task:
    """Create a task for user lists and operational reports."""
    return Task(
        description=(
            "Generate the requested user report: {question}\n"
            "Use only approved reporting tools such as latest users, admins, "
            "super admins, company, branch, department, POS, date range, and general "
            "user-list tools. For Arabic requests like 'هات كل المستخدمين' or "
            "'هات اول عشرة', use Get Users with a safe limit. If the user asks for "
            "all users without a number, return only 10 and say the result is limited."
        ).format(question=question),
        expected_output=(
            "A structured report in the same language as the user. Include counts "
            "when useful, summarize long lists, and mention if results are limited."
        ),
        agent=create_users_agent(),
    )


def create_user_analytics_task(question: str) -> Task:
    """Create a task for analytics and grouped user insights."""
    return Task(
        description=(
            "Analyze user data for this request: {question}\n"
            "Use statistics and grouping tools. Explain trends or notable points "
            "only when supported by returned data."
        ).format(question=question),
        expected_output=(
            "An analytical answer with key metrics, concise interpretation, and "
            "no unsupported assumptions. Match the user's language."
        ),
        agent=create_users_agent(),
    )


def create_user_statistics_task(question: str) -> Task:
    """Create a task for overall user statistics."""
    return Task(
        description=(
            "Calculate and explain user statistics for this request: {question}\n"
            "Prefer the Get User Statistics tool unless the user asks for a "
            "specific grouping such as users per company."
        ).format(question=question),
        expected_output=(
            "A clear statistics summary with totals and categories. Use Arabic or "
            "English based on the user's message."
        ),
        agent=create_users_agent(),
    )


def create_user_management_task(question: str) -> Task:
    """Create a task for safe user-management-style questions."""
    return Task(
        description=(
            "Answer this user management request: {question}\n"
            "This module is read-only. Use lookup, permission summary, existence, "
            "and reporting tools to provide guidance without modifying data."
        ).format(question=question),
        expected_output=(
            "A practical answer that explains the current user data or permissions. "
            "If the request requires writes, state that this Crew is read-only."
        ),
        agent=create_users_agent(),
    )


def create_users_task(question: str) -> Task:
    """
    Route a natural-language question to the best Users task category.

    This lightweight router keeps the public API simple for main.py while still
    aligning with Clean Architecture: application orchestration lives in tasks,
    data access lives in tools, and infrastructure lives in database.
    """
    normalized = question.lower()
    logger.info("Creating users task for question: %s", question)

    if any(token in normalized for token in ("id", "email", "named", "name", "exists", "find", "search", "اسم", "ابحث", "دور")):
        return create_user_lookup_task(question)
    if any(token in normalized for token in ("statistics", "stats", "احص", "إحص", "total", "how many", "عدد", "كام")):
        return create_user_statistics_task(question)
    if any(token in normalized for token in ("per company", "analytics", "analyze", "analysis", "تحليل", "لكل شركة")):
        return create_user_analytics_task(question)
    if any(token in normalized for token in ("permission", "permissions", "صلاح", "manage", "management")):
        return create_user_management_task(question)
    return create_user_reporting_task(question)
