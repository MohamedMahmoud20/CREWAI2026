import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from crewai.tools import tool
from psycopg2.extras import RealDictCursor

from database.connection import get_connection


logger = logging.getLogger(__name__)

ACCOUNT_PUBLIC_COLUMNS: tuple[str, ...] = (
    "id",
    "accounts_id",
    "accounts_code",
    "accounts_name",
    "accounts_mobile",
    "accounts_address",
    "accounts_notes",
    "accounts_discount",
    "accounts_type_id",
    "accounts_ismain",
    "accounts_fatherid",
    "accounts_isclient",
    "accounts_isemp",
    "accounts_isdistributor",
    "accounts_issandouk",
    "accounts_isnotactive",
    "accounts_contactperson_name",
    "accounts_taxregnum",
    "accounts_price",
    '"companyId"',
    '"createdAt"',
    '"updatedAt"',
)

ACCOUNT_PUBLIC_SELECT = ", ".join(ACCOUNT_PUBLIC_COLUMNS)
FORBIDDEN_SQL_TOKENS: tuple[str, ...] = (
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


def _qualified_select(alias: str) -> str:
    return ", ".join(f"{alias}.{column}" for column in ACCOUNT_PUBLIC_COLUMNS)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _to_json_friendly(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default))


def _success(data: Any, message: str = "OK") -> dict[str, Any]:
    return {"success": True, "message": message, "data": _to_json_friendly(data)}


def _failure(exc: Exception, message: str) -> dict[str, Any]:
    logger.exception(message)
    return {"success": False, "message": message, "data": None}


def _safe_limit(limit: int, maximum: int = 200) -> int:
    return max(1, min(int(limit), maximum))


def _fetch_one(query: str, params: Iterable[Any]) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
            return dict(row) if row else None


def _fetch_all(query: str, params: Iterable[Any]) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]


def _readonly_sql_denied() -> dict[str, Any]:
    return {
        "success": False,
        "message": "Access denied. Only SELECT queries are allowed.",
        "data": None,
    }


def _is_readonly_accounts_select(sql: str) -> bool:
    normalized = sql.strip().lower()
    if not normalized.startswith("select"):
        return False
    if any(re.search(rf"\b{re.escape(token)}\b", normalized) for token in FORBIDDEN_SQL_TOKENS):
        return False
    if "accounts" not in normalized:
        return False
    if re.search(r"\busers\b", normalized):
        return False
    return True


@tool("Execute Readonly SQL")
def execute_readonly_sql(sql: str) -> dict[str, Any]:
    """
    Execute a dynamically generated PostgreSQL SELECT query against accounts.

    The tool is intentionally read-only: it rejects any query that does not
    start with SELECT or contains write/DDL/security operations.
    """
    cleaned_sql = sql.strip()
    if not _is_readonly_accounts_select(cleaned_sql):
        return _readonly_sql_denied()

    try:
        print("=" * 50)
        print("SQL GENERATED:")
        print(sql)
        print("=" * 50)
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(cleaned_sql)
                rows = [dict(row) for row in cursor.fetchall()]
        return _success(rows, "Query executed successfully")
    except Exception as exc:
        return _failure(exc, "Failed to execute readonly SQL")


@tool("Get Account By ID")
def get_account_by_id(account_id: int) -> dict[str, Any]:
    """Fetch one accounting account by accounts.id."""
    try:
        row = _fetch_one(
            f"SELECT {ACCOUNT_PUBLIC_SELECT} FROM accounts WHERE id = %s LIMIT 1",
            (account_id,),
        )
        return _success(row, "Account lookup completed")
    except Exception as exc:
        return _failure(exc, "Failed to get account by ID")


@tool("Get Account By Code")
def get_account_by_code(account_code: str) -> dict[str, Any]:
    """Fetch one accounting account by accounts_code."""
    try:
        row = _fetch_one(
            f"""
            SELECT {ACCOUNT_PUBLIC_SELECT}
            FROM accounts
            WHERE accounts_code = %s
            LIMIT 1
            """,
            (account_code,),
        )
        return _success(row, "Account lookup completed")
    except Exception as exc:
        return _failure(exc, "Failed to get account by code")


@tool("Search Accounts By Name")
def search_accounts_by_name(name: str, limit: int = 20) -> dict[str, Any]:
    """Search accounting accounts by partial account name using ILIKE."""
    try:
        rows = _fetch_all(
            f"""
            SELECT {ACCOUNT_PUBLIC_SELECT}
            FROM accounts
            WHERE accounts_name ILIKE %s
            ORDER BY accounts_code ASC NULLS LAST, accounts_name ASC
            LIMIT %s
            """,
            (f"%{name}%", _safe_limit(limit)),
        )
        return _success(rows, "Account search completed")
    except Exception as exc:
        return _failure(exc, "Failed to search accounts")


@tool("Get Accounts")
def get_accounts(limit: int = 100, order: str = "code") -> dict[str, Any]:
    """Fetch a limited list of accounting accounts."""
    try:
        order_sql = {
            "code": "accounts_code ASC NULLS LAST, accounts_name ASC",
            "name": "accounts_name ASC NULLS LAST",
            "latest": '"createdAt" DESC NULLS LAST',
            "oldest": '"createdAt" ASC NULLS LAST',
        }.get(str(order).lower(), "accounts_code ASC NULLS LAST, accounts_name ASC")
        rows = _fetch_all(
            f"SELECT {ACCOUNT_PUBLIC_SELECT} FROM accounts ORDER BY {order_sql} LIMIT %s",
            (_safe_limit(limit),),
        )
        return _success(rows, "Accounts fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get accounts")


@tool("Count Accounts")
def count_accounts() -> dict[str, Any]:
    """Count all accounting accounts."""
    try:
        row = _fetch_one("SELECT COUNT(*) AS total_accounts FROM accounts", ())
        return _success(row, "Accounts counted")
    except Exception as exc:
        return _failure(exc, "Failed to count accounts")


@tool("Get Account Statistics")
def get_account_statistics() -> dict[str, Any]:
    """Calculate high-level account statistics."""
    try:
        row = _fetch_one(
            """
            SELECT
                COUNT(*) AS total_accounts,
                COUNT(*) FILTER (WHERE accounts_ismain = TRUE) AS main_accounts,
                COUNT(*) FILTER (WHERE COALESCE(accounts_ismain, FALSE) = FALSE) AS sub_accounts,
                COUNT(*) FILTER (WHERE accounts_isclient = TRUE) AS customer_accounts,
                COUNT(*) FILTER (WHERE accounts_isemp = TRUE) AS employee_accounts,
                COUNT(*) FILTER (WHERE accounts_isdistributor = TRUE) AS distributor_accounts,
                COUNT(*) FILTER (WHERE accounts_issandouk = TRUE) AS cash_accounts,
                COUNT(*) FILTER (WHERE accounts_isnotactive = TRUE) AS inactive_accounts,
                COUNT(DISTINCT "companyId") AS companies_count,
                COUNT(DISTINCT accounts_type_id) AS account_types_count
            FROM accounts
            """,
            (),
        )
        return _success(row, "Account statistics calculated")
    except Exception as exc:
        return _failure(exc, "Failed to get account statistics")


@tool("Get Main Accounts")
def get_main_accounts(limit: int = 100) -> dict[str, Any]:
    """Fetch main accounts where accounts_ismain is true."""
    return _get_accounts_by_boolean("accounts_ismain", True, limit, "Main accounts fetched")


@tool("Get Customer Accounts")
def get_customer_accounts(limit: int = 100) -> dict[str, Any]:
    """Fetch customer accounts where accounts_isclient is true."""
    return _get_accounts_by_boolean("accounts_isclient", True, limit, "Customer accounts fetched")


@tool("Get Employee Accounts")
def get_employee_accounts(limit: int = 100) -> dict[str, Any]:
    """Fetch employee accounts where accounts_isemp is true."""
    return _get_accounts_by_boolean("accounts_isemp", True, limit, "Employee accounts fetched")


@tool("Get Distributor Accounts")
def get_distributor_accounts(limit: int = 100) -> dict[str, Any]:
    """Fetch distributor accounts where accounts_isdistributor is true."""
    return _get_accounts_by_boolean("accounts_isdistributor", True, limit, "Distributor accounts fetched")


@tool("Get Cash Accounts")
def get_cash_accounts(limit: int = 100) -> dict[str, Any]:
    """Fetch cash or treasury accounts where accounts_issandouk is true."""
    return _get_accounts_by_boolean("accounts_issandouk", True, limit, "Cash accounts fetched")


@tool("Get Inactive Accounts")
def get_inactive_accounts(limit: int = 100) -> dict[str, Any]:
    """Fetch inactive accounts where accounts_isnotactive is true."""
    return _get_accounts_by_boolean("accounts_isnotactive", True, limit, "Inactive accounts fetched")


def _get_accounts_by_boolean(column: str, value: bool, limit: int, message: str) -> dict[str, Any]:
    allowed_columns = {
        "accounts_ismain",
        "accounts_isclient",
        "accounts_isemp",
        "accounts_isdistributor",
        "accounts_issandouk",
        "accounts_isnotactive",
    }
    if column not in allowed_columns:
        return {"success": False, "message": "Unsupported account filter", "data": None}
    try:
        rows = _fetch_all(
            f"""
            SELECT {ACCOUNT_PUBLIC_SELECT}
            FROM accounts
            WHERE {column} = %s
            ORDER BY accounts_code ASC NULLS LAST, accounts_name ASC
            LIMIT %s
            """,
            (value, _safe_limit(limit)),
        )
        return _success(rows, message)
    except Exception as exc:
        return _failure(exc, "Failed to get filtered accounts")


@tool("Get Accounts By Company")
def get_accounts_by_company(company_id: int, limit: int = 100) -> dict[str, Any]:
    """Fetch accounts belonging to a specific companyId."""
    try:
        rows = _fetch_all(
            f"""
            SELECT {ACCOUNT_PUBLIC_SELECT}
            FROM accounts
            WHERE "companyId" = %s
            ORDER BY accounts_code ASC NULLS LAST, accounts_name ASC
            LIMIT %s
            """,
            (company_id, _safe_limit(limit)),
        )
        return _success(rows, "Company accounts fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get accounts by company")


@tool("Get Child Accounts")
def get_child_accounts(parent_id: int, limit: int = 100) -> dict[str, Any]:
    """Fetch direct child accounts using accounts_fatherid."""
    try:
        rows = _fetch_all(
            f"""
            SELECT {ACCOUNT_PUBLIC_SELECT}
            FROM accounts
            WHERE accounts_fatherid = %s
            ORDER BY accounts_code ASC NULLS LAST, accounts_name ASC
            LIMIT %s
            """,
            (parent_id, _safe_limit(limit)),
        )
        return _success(rows, "Child accounts fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get child accounts")


@tool("Get Parent Account")
def get_parent_account(account_id: int) -> dict[str, Any]:
    """Fetch the parent account of one account using accounts_fatherid."""
    try:
        row = _fetch_one(
            f"""
            SELECT {_qualified_select("parent")}
            FROM accounts child
            JOIN accounts parent ON parent.id = child.accounts_fatherid
            WHERE child.id = %s
            LIMIT 1
            """,
            (account_id,),
        )
        return _success(row, "Parent account fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get parent account")


@tool("Get Account Tree")
def get_account_tree(root_id: int | None = None, limit: int = 200) -> dict[str, Any]:
    """Fetch an account hierarchy using a PostgreSQL recursive SELECT."""
    try:
        safe_limit = _safe_limit(limit, 500)
        if root_id is None:
            rows = _fetch_all(
                f"""
                WITH RECURSIVE account_tree AS (
                    SELECT
                        {ACCOUNT_PUBLIC_SELECT},
                        0 AS level,
                        ARRAY[id] AS path
                    FROM accounts
                    WHERE accounts_fatherid IS NULL OR accounts_ismain = TRUE

                    UNION ALL

                    SELECT
                        {_qualified_select("child")},
                        parent.level + 1 AS level,
                        parent.path || child.id AS path
                    FROM accounts child
                    JOIN account_tree parent ON child.accounts_fatherid = parent.id
                    WHERE NOT child.id = ANY(parent.path)
                )
                SELECT *
                FROM account_tree
                ORDER BY path
                LIMIT %s
                """,
                (safe_limit,),
            )
        else:
            rows = _fetch_all(
                f"""
                WITH RECURSIVE account_tree AS (
                    SELECT
                        {ACCOUNT_PUBLIC_SELECT},
                        0 AS level,
                        ARRAY[id] AS path
                    FROM accounts
                    WHERE id = %s

                    UNION ALL

                    SELECT
                        {_qualified_select("child")},
                        parent.level + 1 AS level,
                        parent.path || child.id AS path
                    FROM accounts child
                    JOIN account_tree parent ON child.accounts_fatherid = parent.id
                    WHERE NOT child.id = ANY(parent.path)
                )
                SELECT *
                FROM account_tree
                ORDER BY path
                LIMIT %s
                """,
                (root_id, safe_limit),
            )
        return _success(rows, "Account tree fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get account tree")


ACCOUNTS_TOOLS = [
    get_account_by_id,
    get_account_by_code,
    search_accounts_by_name,
    get_accounts,
    count_accounts,
    get_account_statistics,
    get_main_accounts,
    get_customer_accounts,
    get_employee_accounts,
    get_distributor_accounts,
    get_cash_accounts,
    get_inactive_accounts,
    get_accounts_by_company,
    get_child_accounts,
    get_parent_account,
    get_account_tree,
    execute_readonly_sql,
]
