#!/usr/bin/env python
"""تشغيل الـ Crew: تسجيل عميل جديد أو جلب بيانات عميل."""
import sys
import warnings
import json
from pathlib import Path

# تحميل .env قبل أي استيراد من CrewAI (مطلوب لـ OLLAMA_BASE_URL / OLLAMA_MODEL)
from dotenv import load_dotenv
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

from myproject.config.crew_setup import client_crew
from myproject.crew_runner import run_crewai, run_crewai_with_trigger

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


def run():
    """
    تشغيل الـ crew بناءً على طلب المستخدم (سطر أوامر أو إدخال تفاعلي).
    """
    if len(sys.argv) > 1:
        user_request = " ".join(sys.argv[1:])
    else:
        user_request = input(
            "Enter request (example: create a new client named Client 1 with phone 01000000000): "
        ).strip()
        if not user_request:
            # Keep the default request ASCII-safe for Windows terminals.
            user_request = "Create a new client named Client 1 with phone 01000000000 and address Cairo"

    try:
        out = run_crewai(user_request)
        print("\n--- Crew Result ---")
        print(out)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}") from e


def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        client_crew.replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    raw_cid = trigger_payload.get("company_id")
    company_id = None
    if raw_cid is not None:
        try:
            company_id = int(raw_cid)
        except (TypeError, ValueError):
            company_id = None

    try:
        result = run_crewai_with_trigger(trigger_payload, company_id=company_id)
        print(result)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")


if __name__ == "__main__":
    # تشغيل من مجلد myproject (بعد تفعيل الـ venv):
    #   cd myproject
    #   .venv\Scripts\activate
    #   python -m myproject.main "سجل عميل جديد اسمه عميل 1 ورقمه 01000000000"
    #   python -m myproject.main "هات بيانات العميل 884"
    run()