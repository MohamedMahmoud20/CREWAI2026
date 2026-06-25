import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from crewai.tools import tool
from psycopg2.extras import RealDictCursor

from database.connection import get_connection


logger = logging.getLogger(__name__)

USER_PUBLIC_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "dep_id",
    "out",
    "email",
    "is_admin",
    "is_super_admin",
    "isposuser",
    "maxdiscount",
    "usercanchangeitemprices",
    "formid",
    "progid",
    "levels_id",
    "stock_shopcard_id",
    "justuseexactshop",
    "bransh_id",
    "justuseexactbransh",
    "usercannotsoldbynegative",
    "usercannotseedocforothers",
    "programlanguage",
    "isposuser_market",
    '"createdAt"',
    '"updatedAt"',
    "group_id",
    '"companyId"',
)

USER_PUBLIC_SELECT = ", ".join(USER_PUBLIC_COLUMNS)


def _json_default(value: Any) -> str:
    """Serialize database-specific values into JSON-friendly strings."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _to_json_friendly(value: Any) -> Any:
    """Convert psycopg2 results into values that can be returned by CrewAI tools."""
    return json.loads(json.dumps(value, default=_json_default))


def _success(data: Any, message: str = "OK") -> dict[str, Any]:
    """Build a standard successful tool response."""
    return {"success": True, "message": message, "data": _to_json_friendly(data)}


def _failure(exc: Exception, message: str) -> dict[str, Any]:
    """Build a standard error response without exposing SQL internals."""
    logger.exception(message)
    return {"success": False, "message": message, "error": str(exc), "data": None}


def _fetch_one(query: str, params: Iterable[Any]) -> dict[str, Any] | None:
    """Execute a safe SELECT query and return one row as a dictionary."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
            return dict(row) if row else None


def _fetch_all(query: str, params: Iterable[Any]) -> list[dict[str, Any]]:
    """Execute a safe SELECT query and return all rows as dictionaries."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]


@tool("Get User By ID")
def get_user_by_id(user_id: int) -> dict[str, Any]:
    """
    Fetch a single user by numeric ID.

    Args:
        user_id: The users.id value to look up.

    Returns:
        A JSON-friendly response containing the matched user without the
        password column, or None when no user exists.
    """
    try:
        row = _fetch_one(
            f'SELECT {USER_PUBLIC_SELECT} FROM users WHERE id = %s LIMIT 1',
            (user_id,),
        )
        return _success(row, "User lookup completed")
    except Exception as exc:
        return _failure(exc, "Failed to get user by ID")


@tool("Get User By Email")
def get_user_by_email(email: str) -> dict[str, Any]:
    """
    Fetch a single user by email address.

    Args:
        email: Email address to search for. Matching is case-insensitive.

    Returns:
        A JSON-friendly response containing the matched user without the
        password column, or None when no user exists.
    """
    try:
        row = _fetch_one(
            f'SELECT {USER_PUBLIC_SELECT} FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1',
            (email,),
        )
        return _success(row, "User lookup completed")
    except Exception as exc:
        return _failure(exc, "Failed to get user by email")


@tool("Search Users By Name")
def search_users_by_name(name: str, limit: int = 20) -> dict[str, Any]:
    """
    Search users by partial name match.

    Args:
        name: Name fragment to search for.
        limit: Maximum number of rows to return. The value is capped at 100.

    Returns:
        A JSON-friendly list of matching users without password data.
    """
    try:
        safe_limit = max(1, min(int(limit), 100))
        rows = _fetch_all(
            f'SELECT {USER_PUBLIC_SELECT} FROM users WHERE name ILIKE %s ORDER BY name ASC LIMIT %s',
            (f"%{name}%", safe_limit),
        )
        return _success(rows, "User search completed")
    except Exception as exc:
        return _failure(exc, "Failed to search users by name")


@tool("Get Latest Users")
def get_latest_users(limit: int = 10) -> dict[str, Any]:
    """
    Fetch the newest users by creation timestamp.

    Args:
        limit: Maximum number of latest users to return. The value is capped at 100.

    Returns:
        A JSON-friendly list of recent users without password data.
    """
    try:
        safe_limit = max(1, min(int(limit), 100))
        rows = _fetch_all(
            f'SELECT {USER_PUBLIC_SELECT} FROM users ORDER BY "createdAt" DESC NULLS LAST LIMIT %s',
            (safe_limit,),
        )
        return _success(rows, "Latest users fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get latest users")


@tool("Get Users")
def get_users(limit: int = 10, order: str = "latest") -> dict[str, Any]:
    """
    Fetch a limited user list in a requested safe order.

    Args:
        limit: Maximum number of users to return. The value is capped at 200.
        order: One of latest, oldest, or name.

    Returns:
        A JSON-friendly list of users without password data.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
        order_sql = {
            "latest": '"createdAt" DESC NULLS LAST',
            "oldest": '"createdAt" ASC NULLS LAST',
            "name": "name ASC NULLS LAST",
        }.get(str(order).lower(), '"createdAt" DESC NULLS LAST')
        rows = _fetch_all(
            f"SELECT {USER_PUBLIC_SELECT} FROM users ORDER BY {order_sql} LIMIT %s",
            (safe_limit,),
        )
        return _success(rows, "Users fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get users")


@tool("Count Users")
def count_users() -> dict[str, Any]:
    """
    Count all users in the users table.

    Returns:
        A JSON-friendly response with total_users.
    """
    try:
        row = _fetch_one("SELECT COUNT(*) AS total_users FROM users", ())
        return _success(row, "Users counted")
    except Exception as exc:
        return _failure(exc, "Failed to count users")


@tool("Get Admin Users")
def get_admin_users(limit: int = 100) -> dict[str, Any]:
    """
    Fetch users marked as administrators.

    Args:
        limit: Maximum number of admin users to return. The value is capped at 200.

    Returns:
        A JSON-friendly list of admin users without password data.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
        rows = _fetch_all(
            f'SELECT {USER_PUBLIC_SELECT} FROM users WHERE is_admin = TRUE ORDER BY name ASC LIMIT %s',
            (safe_limit,),
        )
        return _success(rows, "Admin users fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get admin users")


@tool("Get Super Admin Users")
def get_super_admin_users(limit: int = 100) -> dict[str, Any]:
    """
    Fetch users marked as super administrators.

    Args:
        limit: Maximum number of super admin users to return. The value is capped at 200.

    Returns:
        A JSON-friendly list of super admin users without password data.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
        rows = _fetch_all(
            f'SELECT {USER_PUBLIC_SELECT} FROM users WHERE is_super_admin = TRUE ORDER BY name ASC LIMIT %s',
            (safe_limit,),
        )
        return _success(rows, "Super admin users fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get super admin users")


@tool("Get Users By Company")
def get_users_by_company(company_id: int, limit: int = 100) -> dict[str, Any]:
    """
    Fetch users belonging to a specific company.

    Args:
        company_id: The users.companyId value to filter by.
        limit: Maximum number of users to return. The value is capped at 200.

    Returns:
        A JSON-friendly list of users for the company.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
        rows = _fetch_all(
            f'SELECT {USER_PUBLIC_SELECT} FROM users WHERE "companyId" = %s ORDER BY name ASC LIMIT %s',
            (company_id, safe_limit),
        )
        return _success(rows, "Company users fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get users by company")


@tool("Get Users By Branch")
def get_users_by_branch(branch_id: int, limit: int = 100) -> dict[str, Any]:
    """
    Fetch users assigned to a specific branch.

    Args:
        branch_id: The users.bransh_id value to filter by.
        limit: Maximum number of users to return. The value is capped at 200.

    Returns:
        A JSON-friendly list of users for the branch.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
        rows = _fetch_all(
            f"SELECT {USER_PUBLIC_SELECT} FROM users WHERE bransh_id = %s ORDER BY name ASC LIMIT %s",
            (branch_id, safe_limit),
        )
        return _success(rows, "Branch users fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get users by branch")


@tool("Get Users By Department")
def get_users_by_department(department_id: int, limit: int = 100) -> dict[str, Any]:
    """
    Fetch users assigned to a specific department.

    Args:
        department_id: The users.dep_id value to filter by.
        limit: Maximum number of users to return. The value is capped at 200.

    Returns:
        A JSON-friendly list of users for the department.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
        rows = _fetch_all(
            f"SELECT {USER_PUBLIC_SELECT} FROM users WHERE dep_id = %s ORDER BY name ASC LIMIT %s",
            (department_id, safe_limit),
        )
        return _success(rows, "Department users fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get users by department")


@tool("Get POS Users")
def get_pos_users(limit: int = 100) -> dict[str, Any]:
    """
    Fetch users who can use POS features.

    Args:
        limit: Maximum number of POS users to return. The value is capped at 200.

    Returns:
        A JSON-friendly list of POS users without password data.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
        rows = _fetch_all(
            f"""
            SELECT {USER_PUBLIC_SELECT}
            FROM users
            WHERE isposuser = TRUE OR isposuser_market = TRUE
            ORDER BY name ASC
            LIMIT %s
            """,
            (safe_limit,),
        )
        return _success(rows, "POS users fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get POS users")


@tool("Get Users Created Between Dates")
def get_users_created_between_dates(start_date: str, end_date: str, limit: int = 100) -> dict[str, Any]:
    """
    Fetch users created between two dates or timestamps.

    Args:
        start_date: Inclusive start date, such as 2026-01-01.
        end_date: Inclusive end date, such as 2026-12-31.
        limit: Maximum number of users to return. The value is capped at 200.

    Returns:
        A JSON-friendly list of users created inside the requested date range.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
        rows = _fetch_all(
            f"""
            SELECT {USER_PUBLIC_SELECT}
            FROM users
            WHERE "createdAt" >= %s::timestamp
              AND "createdAt" < (%s::timestamp + INTERVAL '1 day')
            ORDER BY "createdAt" DESC NULLS LAST
            LIMIT %s
            """,
            (start_date, end_date, safe_limit),
        )
        return _success(rows, "Users created between dates fetched")
    except Exception as exc:
        return _failure(exc, "Failed to get users created between dates")


@tool("Get User Statistics")
def get_user_statistics() -> dict[str, Any]:
    """
    Calculate high-level user statistics.

    Returns:
        A JSON-friendly response containing totals for admins, super admins,
        active users, inactive users, POS users, companies, branches, and
        departments.
    """
    try:
        row = _fetch_one(
            """
            SELECT
                COUNT(*) AS total_users,
                COUNT(*) FILTER (WHERE COALESCE(out, FALSE) = FALSE) AS active_users,
                COUNT(*) FILTER (WHERE out = TRUE) AS inactive_users,
                COUNT(*) FILTER (WHERE is_admin = TRUE) AS admin_users,
                COUNT(*) FILTER (WHERE is_super_admin = TRUE) AS super_admin_users,
                COUNT(*) FILTER (WHERE isposuser = TRUE OR isposuser_market = TRUE) AS pos_users,
                COUNT(DISTINCT "companyId") AS companies_count,
                COUNT(DISTINCT bransh_id) AS branches_count,
                COUNT(DISTINCT dep_id) AS departments_count,
                COUNT(*) FILTER (WHERE email IS NULL OR email = '') AS users_without_email
            FROM users
            """,
            (),
        )
        return _success(row, "User statistics calculated")
    except Exception as exc:
        return _failure(exc, "Failed to get user statistics")


@tool("Check User Exists")
def check_user_exists(user_id: int | None = None, email: str | None = None) -> dict[str, Any]:
    """
    Check if a user exists by ID or email.

    Args:
        user_id: Optional users.id value to check.
        email: Optional email address to check case-insensitively.

    Returns:
        A JSON-friendly response with exists and matched_by fields.
    """
    try:
        if user_id is not None:
            row = _fetch_one("SELECT EXISTS(SELECT 1 FROM users WHERE id = %s) AS exists", (user_id,))
            return _success({"exists": bool(row and row["exists"]), "matched_by": "id"}, "User existence checked")
        if email:
            row = _fetch_one(
                "SELECT EXISTS(SELECT 1 FROM users WHERE LOWER(email) = LOWER(%s)) AS exists",
                (email,),
            )
            return _success({"exists": bool(row and row["exists"]), "matched_by": "email"}, "User existence checked")
        return _success({"exists": False, "matched_by": None}, "No identifier supplied")
    except Exception as exc:
        return _failure(exc, "Failed to check user existence")


@tool("Get User Permissions Summary")
def get_user_permissions_summary(user_id: int) -> dict[str, Any]:
    """
    Summarize permissions and restrictions for one user.

    Args:
        user_id: The users.id value to summarize.

    Returns:
        A JSON-friendly response focused on permission flags, POS access,
        discount limits, scope restrictions, and grouping metadata. Password is
        never returned.
    """
    try:
        row = _fetch_one(
            """
            SELECT
                id,
                name,
                email,
                is_admin,
                is_super_admin,
                isposuser,
                isposuser_market,
                maxdiscount,
                usercanchangeitemprices,
                usercannotsoldbynegative,
                usercannotseedocforothers,
                justuseexactshop,
                stock_shopcard_id,
                justuseexactbransh,
                bransh_id,
                dep_id,
                levels_id,
                group_id,
                "companyId",
                programlanguage
            FROM users
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        if not row:
            return _success(None, "User not found")

        summary = {
            "user": {"id": row["id"], "name": row["name"], "email": row["email"]},
            "roles": {
                "is_admin": row["is_admin"],
                "is_super_admin": row["is_super_admin"],
                "is_pos_user": row["isposuser"],
                "is_market_pos_user": row["isposuser_market"],
            },
            "permissions": {
                "max_discount": row["maxdiscount"],
                "can_change_item_prices": row["usercanchangeitemprices"],
                "cannot_sell_negative_stock": row["usercannotsoldbynegative"],
                "cannot_see_documents_for_others": row["usercannotseedocforothers"],
            },
            "scope": {
                "company_id": row["companyId"],
                "department_id": row["dep_id"],
                "branch_id": row["bransh_id"],
                "only_exact_branch": row["justuseexactbransh"],
                "shop_card_id": row["stock_shopcard_id"],
                "only_exact_shop": row["justuseexactshop"],
                "level_id": row["levels_id"],
                "group_id": row["group_id"],
            },
            "preferences": {"program_language": row["programlanguage"]},
        }
        return _success(summary, "User permissions summarized")
    except Exception as exc:
        return _failure(exc, "Failed to get user permissions summary")


@tool("Count Users Per Company")
def count_users_per_company(limit: int = 50) -> dict[str, Any]:
    """
    Count users grouped by company.

    Args:
        limit: Maximum number of company groups to return. The value is capped at 200.

    Returns:
        A JSON-friendly list of company_id and total_users rows.
    """
    try:
        safe_limit = max(1, min(int(limit), 200))
        rows = _fetch_all(
            """
            SELECT "companyId" AS company_id, COUNT(*) AS total_users
            FROM users
            GROUP BY "companyId"
            ORDER BY total_users DESC, company_id ASC
            LIMIT %s
            """,
            (safe_limit,),
        )
        return _success(rows, "Users counted per company")
    except Exception as exc:
        return _failure(exc, "Failed to count users per company")


USERS_TOOLS = [
    get_user_by_id,
    get_user_by_email,
    search_users_by_name,
    get_latest_users,
    get_users,
    count_users,
    get_admin_users,
    get_super_admin_users,
    get_users_by_company,
    get_users_by_branch,
    get_users_by_department,
    get_pos_users,
    get_users_created_between_dates,
    get_user_statistics,
    check_user_exists,
    get_user_permissions_summary,
    count_users_per_company,
]
