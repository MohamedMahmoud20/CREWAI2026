import os
from pathlib import Path
from dotenv import load_dotenv

# Path to the project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load configuration variables from .env file
load_dotenv(PROJECT_ROOT / ".env")

USERS_API_BASE = os.getenv("USERS_API_BASE", "http://104.248.246.2/api").rstrip("/")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://173.212.196.100:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")
# Strip ollama/ prefix if configured with it, for standard Ollama API requests
OLLAMA_CLEAN_MODEL = OLLAMA_MODEL.replace("ollama/", "") if OLLAMA_MODEL.startswith("ollama/") else OLLAMA_MODEL

BOT_TOKEN = os.getenv("BOT_TOKEN")
