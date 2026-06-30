import logging

from crewai import Task

from agents.accounts_agent import create_accounts_agent


logger = logging.getLogger(__name__)


def create_account_lookup_task(question: str) -> Task:
    return Task(
        description=(
            "Handle this account lookup request safely: {question}\n"
            "Use only approved accounts tools. Do not use users tools. Do not expose raw SQL."
        ).format(question=question),
        expected_output=(
            "إجابة عربية مختصرة وواضحة عن الحسابات المطابقة، مع توضيح عدم وجود نتائج عند الحاجة."
        ),
        agent=create_accounts_agent(),
    )


def create_account_reporting_task(question: str) -> Task:
    return Task(
        description=(
            "Generate the requested accounts report: {question}\n"
            "Accounts are chart-of-accounts records, not users. Use safe limits for large lists."
        ).format(question=question),
        expected_output="تقرير عربي منظم ومختصر عن الحسابات المطلوبة.",
        agent=create_accounts_agent(),
    )


def create_account_hierarchy_task(question: str) -> Task:
    return Task(
        description=(
            "Analyze this account hierarchy request: {question}\n"
            "Use accounts_fatherid and accounts_ismain to retrieve parent, child, or tree data."
        ).format(question=question),
        expected_output="شرح عربي واضح لشجرة الحسابات أو العلاقة بين الحسابات.",
        agent=create_accounts_agent(),
    )


def create_account_statistics_task(question: str) -> Task:
    return Task(
        description=(
            "Calculate accounting account statistics for this request: {question}\n"
            "Use read-only account statistics tools only."
        ).format(question=question),
        expected_output="ملخص عربي واضح للإحصائيات المطلوبة.",
        agent=create_accounts_agent(),
    )


def create_accounts_task(question: str) -> Task:
    normalized = question.lower()
    logger.info("Creating accounts task for question: %s", question)

    if any(token in normalized for token in ("شجرة", "هيكل", "hierarchy", "tree", "child", "children", "parent", "ابناء", "أبناء", "فرعي", "الاب", "الأب")):
        return create_account_hierarchy_task(question)
    if any(token in normalized for token in ("عدد", "كام", "احص", "إحص", "statistics", "stats", "count")):
        return create_account_statistics_task(question)
    if any(token in normalized for token in ("اسم", "اسمه", "code", "كود", "id", "search", "find", "ابحث", "دور")):
        return create_account_lookup_task(question)
    return create_account_reporting_task(question)
