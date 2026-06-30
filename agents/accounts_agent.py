import logging
import os
from typing import Any

from crewai import Agent, LLM
from dotenv import load_dotenv

from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL
from tools.accounts_tools import ACCOUNTS_TOOLS


load_dotenv()

logger = logging.getLogger(__name__)


def build_llm() -> LLM:
    configured_model = os.getenv("CREWAI_LLM_MODEL", OLLAMA_MODEL)
    model = configured_model if configured_model.startswith("ollama/") else f"ollama/{configured_model}"
    base_url = os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
    llm = LLM(model=model, base_url=base_url)
    llm.supports_function_calling = lambda: False
    return llm


def create_accounts_agent(**kwargs: Any) -> Agent:
    """Create the accounting chart-of-accounts assistant agent."""
    logger.info("Creating Accounts Agent")
    return Agent(
        role="Senior Accounting Database Assistant",
        goal=(
            "Help users retrieve, search, filter, summarize, and explain accounting "
            "chart-of-accounts data from the accounts table in Arabic. Convert "
            "Arabic natural-language questions into PostgreSQL SELECT queries when "
            "data is being retrieved. For account updates, show the generated UPDATE "
            "SQL and require explicit user confirmation before execution."
        ),
        backstory=(
            "You understand that accounts records are accounting entities in a "
            "hierarchical chart of accounts. They are not application users. "
            "accounts_ismain marks main accounts, accounts_fatherid links parent "
            "accounts, accounts_isclient marks customers, accounts_isemp marks "
            "employees, accounts_isdistributor marks distributors, accounts_issandouk "
            "marks cash or treasury accounts, and accounts_isnotactive marks inactive "
            "accounts. Important fields include id, accounts_id, accounts_code, "
            "accounts_name, accounts_mobile, accounts_address, accounts_notes, "
            "accounts_ismain, accounts_fatherid, accounts_isclient, accounts_isemp, "
            "accounts_isdistributor, accounts_issandouk, accounts_isnotactive, "
            "companyId, createdAt, and updatedAt. SELECT queries may execute directly. "
            "UPDATE statements are allowed only for account fields after showing SQL "
            "and receiving confirmation. Never delete data or modify database structure."
        ),
        tools=ACCOUNTS_TOOLS,
        llm=kwargs.get("llm") or build_llm(),
        verbose=bool(kwargs.get("verbose", False)),
        allow_delegation=False,
        max_iter=int(kwargs.get("max_iter", 3)),
    )
