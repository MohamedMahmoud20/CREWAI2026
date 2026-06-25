import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

import psycopg2
from dotenv import load_dotenv
from psycopg2.extensions import connection as PsycopgConnection


load_dotenv()

logger = logging.getLogger(__name__)


class DatabaseConnectionError(RuntimeError):
    """Raised when PostgreSQL connection creation fails."""


class DatabaseConfig:
    """Centralized PostgreSQL configuration loaded from environment variables."""

    def __init__(self) -> None:
        self.host: str = os.getenv("POSTGRES_HOST", "104.248.246.2")
        self.port: int = int(os.getenv("POSTGRES_PORT", "5432"))
        self.database: str = os.getenv("POSTGRES_DB", "postgres")
        self.user: str = os.getenv("POSTGRES_USER", "user")
        self.password: str = os.getenv("POSTGRES_PASSWORD", "123123")
        self.connect_timeout: int = int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10"))

    def as_kwargs(self) -> dict[str, Any]:
        """Return psycopg2-compatible connection keyword arguments."""
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
            "connect_timeout": self.connect_timeout,
        }


def create_connection() -> PsycopgConnection:
    """
    Create a PostgreSQL connection using environment configuration.

    The rest of the application depends on this function instead of calling
    psycopg2 directly, which keeps database infrastructure isolated from the
    CrewAI agent and tools.
    """
    config = DatabaseConfig()
    try:
        return psycopg2.connect(**config.as_kwargs())
    except psycopg2.Error as exc:
        logger.exception("Failed to create PostgreSQL connection")
        raise DatabaseConnectionError(str(exc)) from exc


@contextmanager
def get_connection() -> Generator[PsycopgConnection, None, None]:
    """
    Yield a PostgreSQL connection and always close it afterwards.

    This context manager is the only connection lifecycle primitive used by the
    tools layer. It avoids leaked connections even when a query fails.
    """
    conn: PsycopgConnection | None = None
    try:
        conn = create_connection()
        yield conn
    finally:
        if conn is not None:
            conn.close()
