import os
from pathlib import Path

from dotenv import load_dotenv
from crewai import LLM

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")
OLLAMA_MODEL = f"ollama/{OLLAMA_MODEL}" if not OLLAMA_MODEL.startswith("ollama/") else OLLAMA_MODEL
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://173.212.196.100:11434")

local_llm = LLM(
    model=OLLAMA_MODEL,
    base_url=OLLAMA_BASE_URL,
)

print("Using LLM provider: Ollama")
print(f"Model: {local_llm.model}")
print(f"Base URL: {local_llm.base_url}")
