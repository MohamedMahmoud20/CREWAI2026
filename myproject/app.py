import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

load_dotenv(ROOT_DIR / ".env")

from myproject.crew_runner import kickoff_crew  # noqa: E402


class AgentRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Natural language request")
    company_id: int | None = Field(
        None,
        description="Optional company scope for tools (same as Telegram session company_id).",
    )


app = FastAPI(title="CrewAI Agent API", version="1.0.0")


@app.post("/agent")
def run_agent(payload: AgentRequest) -> dict[str, Any]:
    try:
        data = kickoff_crew(payload.message, company_id=payload.company_id)
        return {
            "success": True,
            "message": payload.message,
            "data": data,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "Crew execution failed",
                "details": str(exc),
            },
        ) from exc
