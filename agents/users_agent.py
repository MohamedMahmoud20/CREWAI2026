import logging
import os
from typing import Any

from crewai import Agent, LLM
from dotenv import load_dotenv

from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL
from tools.users_tools import USERS_TOOLS


load_dotenv()

logger = logging.getLogger(__name__)


def build_llm() -> LLM:
    """
    Build the CrewAI LLM adapter.

    The default uses Ollama because this project already runs local/remote
    Ollama models. Override CREWAI_LLM_MODEL and OLLAMA_BASE_URL in .env when
    deploying to another Ollama model/server.
    """
    configured_model = os.getenv("CREWAI_LLM_MODEL", OLLAMA_MODEL)
    model = configured_model if configured_model.startswith("ollama/") else f"ollama/{configured_model}"
    base_url = os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
    llm = LLM(model=model, base_url=base_url)
    # gemma3:1b rejects OpenAI native tool payloads; use CrewAI's text tool loop.
    llm.supports_function_calling = lambda: False
    return llm


def create_users_agent(**kwargs: Any) -> Agent:
    """
    Create the Users domain agent.

    The agent can reason over natural-language questions, but it cannot execute
    arbitrary SQL. It only receives narrow, audited tools that use parameterized
    queries and hide password data.
    """
    logger.info("Creating Users Agent")
    return Agent(
        role="Senior Users Data Analyst",
        goal=(
            "Understand Arabic or English natural-language requests about users, "
            "call exactly one approved database tool when data is needed, then "
            "summarize the returned data clearly in the user's language."
        ),
        backstory=(
            "You are a production-grade data assistant for a business system. "
            "You understand user records, roles, permissions, company/branch "
            "scope, POS access, and operational reporting. You never request or "
            "expose passwords and you never invent data that was not returned by tools. "
            "If the user asks for all users, fetch a safe limited list. If no limit "
            "is given, use 10 rows."
        ),
        tools=USERS_TOOLS,
        llm=kwargs.get("llm") or build_llm(),
        verbose=bool(kwargs.get("verbose", False)),
        allow_delegation=False,
        max_iter=int(kwargs.get("max_iter", 3)),
    )
