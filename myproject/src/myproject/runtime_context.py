"""
Request-scoped company_id for CrewAI tool calls (e.g. Telegram user session).

Set via company_id_scope() around crew.kickoff() so tools can read get_active_company_id().
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_company_id: ContextVar[int | None] = ContextVar("active_company_id", default=None)
_skip_name_confirmation: ContextVar[bool] = ContextVar("skip_name_confirmation", default=False)
_auth_header: ContextVar[str | None] = ContextVar("active_auth_header", default=None)
_fiscal_year_id: ContextVar[int | None] = ContextVar("active_fiscal_year_id", default=None)


def get_active_company_id() -> int | None:
    return _company_id.get()


def get_skip_name_confirmation() -> bool:
    return _skip_name_confirmation.get()


def get_active_auth_header() -> str | None:
    return _auth_header.get()


def get_active_fiscal_year_id() -> int | None:
    return _fiscal_year_id.get()


@contextmanager
def company_id_scope(company_id: int | None):
    """When company_id is set, tools should prefer it over LLM-provided defaults."""
    if company_id is None:
        yield
        return
    token = _company_id.set(company_id)
    try:
        yield
    finally:
        _company_id.reset(token)


@contextmanager
def skip_name_confirmation_scope(skip: bool = False):
    if not skip:
        yield
        return
    token = _skip_name_confirmation.set(True)
    try:
        yield
    finally:
        _skip_name_confirmation.reset(token)


@contextmanager
def auth_header_scope(auth_header: str | None):
    if not auth_header:
        yield
        return
    token = _auth_header.set(auth_header)
    try:
        yield
    finally:
        _auth_header.reset(token)


@contextmanager
def fiscal_year_id_scope(fiscal_year_id: int | None):
    if fiscal_year_id is None:
        yield
        return
    token = _fiscal_year_id.set(fiscal_year_id)
    try:
        yield
    finally:
        _fiscal_year_id.reset(token)
