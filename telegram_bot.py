import logging
import asyncio
import json
import sys
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
)
from config.settings import BOT_TOKEN
from auth.login import login_user
from crews.users_crew import ask_users_crew

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.ERROR
)
logger = logging.getLogger(__name__)

# Conversation states
STATE_EMAIL, STATE_PASSWORD = range(2)

# Session persistence file path
SESSIONS_FILE = Path(__file__).resolve().parent / "sessions.json"

NATURAL_CHAT_SYSTEM_PROMPT = (
    "You are a friendly, helpful Telegram assistant. Reply naturally to normal "
    "conversation and general questions. Do not force the user into the app or "
    "authentication flow unless they explicitly ask about login, account data, "
    "or app-specific actions. Always reply in the same language as the user's "
    "message. If the user mixes languages, reply with the same mixed-language "
    "style."
)


def get_reply_language_instruction(text: str) -> str:
    """Returns a direct language instruction based on the user's message."""
    arabic_chars = sum(1 for char in text if "\u0600" <= char <= "\u06ff")
    english_chars = sum(1 for char in text.lower() if "a" <= char <= "z")

    if arabic_chars and arabic_chars >= english_chars:
        return "رد باللغة العربية فقط وبأسلوب طبيعي. لا ترد بالإنجليزية."
    if english_chars:
        return "Reply in English only, naturally."
    return "Reply in the same language as the user's message."


def build_chat_prompt(user_text: str) -> str:
    language_instruction = get_reply_language_instruction(user_text)
    return (
        f"{language_instruction}\n\n"
        f"User message:\n{user_text}\n\n"
        "Assistant response:"
    )


def load_sessions() -> dict:
    """Loads all saved user sessions from sessions.json."""
    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load sessions file: {e}")
    return {}


def save_session(telegram_user_id: int, email: str, auth_header: str, company_id: int) -> None:
    """Saves the user session details to sessions.json."""
    sessions = load_sessions()
    sessions[str(telegram_user_id)] = {
        "email": email,
        "auth_header": auth_header,
        "company_id": company_id,
    }
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save session: {e}")


def delete_session(telegram_user_id: int) -> None:
    """Deletes the user session details from sessions.json."""
    sessions = load_sessions()
    user_key = str(telegram_user_id)
    if user_key in sessions:
        del sessions[user_key]
        try:
            with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(sessions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")


def ensure_session(telegram_user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Ensures that session credentials are loaded in memory.
    If not in memory, attempts to restore them from sessions.json.
    Returns True if logged in, False otherwise.
    """
    if "auth_header" in context.user_data:
        return True

    sessions = load_sessions()
    user_key = str(telegram_user_id)
    if user_key in sessions:
        session_data = sessions[user_key]
        context.user_data["email"] = session_data.get("email")
        context.user_data["auth_header"] = session_data.get("auth_header")
        context.user_data["company_id"] = session_data.get("company_id")
        return True

    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and instructions."""
    uid = update.effective_user.id
    if ensure_session(uid, context):
        welcome_text = (
            "مرحبًا بك مجددًا! 🤖\n\n"
            "أنت مسجل الدخول بالفعل. يمكنك التحدث معي وسأقوم بالرد عليك باستخدام موديل Ollama.\n\n"
            "إذا أردت تسجيل الخروج، استخدم الأمر:\n/logout"
        )
    else:
        welcome_text = (
            "مرحبًا بك في بوت Ollama و Authentication! 🤖\n\n"
            "يمكنك التحدث معي مباشرة وسأرد عليك بشكل طبيعي.\n\n"
            "إذا أردت ربط حسابك أو استخدام ميزات الحساب، استخدم الأمر:\n"
            "/login"
        )
    await update.message.reply_text(welcome_text)


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the login conversation flow."""
    uid = update.effective_user.id
    if ensure_session(uid, context):
        await update.message.reply_text(
            "أنت مسجل الدخول بالفعل! يمكنك البدء في كتابة رسائلك وسأرد عليك.\n"
            "لتسجيل الخروج، استخدم الأمر:\n/logout"
        )
        return ConversationHandler.END

    await update.message.reply_text("يرجى إدخال البريد الإلكتروني الخاص بك:")
    return STATE_EMAIL


async def login_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the email and asks for the password."""
    email = update.message.text.strip()
    if not email:
        await update.message.reply_text("البريد الإلكتروني لا يمكن أن يكون فارغًا. يرجى المحاولة مرة أخرى:")
        return STATE_EMAIL

    context.user_data["email"] = email
    await update.message.reply_text("يرجى إدخال كلمة المرور الخاصة بك:")
    return STATE_PASSWORD


async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Performs the authentication check and persists the session."""
    password = update.message.text.strip()
    email = context.user_data.get("email")
    uid = update.effective_user.id

    await update.message.reply_text("جاري التحقق من البيانات وتوصيل الحساب...")

    try:
        # Run synchronous login logic in a separate thread to keep bot responsive
        auth_header, company_id, err = await asyncio.to_thread(
            login_user, email, password
        )

        if err:
            await update.message.reply_text(
                f"فشل تسجيل الدخول: {err}\n\n"
                "يرجى إعادة المحاولة باستخدام الأمر /login"
            )
            context.user_data.clear()
            return ConversationHandler.END

        context.user_data["auth_header"] = auth_header
        context.user_data["company_id"] = company_id
        
        # Persist session to JSON file
        save_session(uid, email, auth_header, company_id)

        await update.message.reply_text(
            "تم تسجيل الدخول بنجاح! 🎉\n"
            f"مُعرف الشركة: {company_id}\n\n"
            "يمكنك الآن التحدث معي مباشرة وسأقوم بالإجابة على استفساراتك."
        )
    except Exception as e:
        logger.error(f"Error during login: {e}")
        await update.message.reply_text(
            f"حدث خطأ غير متوقع أثناء تسجيل الدخول: {e}\n"
            "يرجى إعادة المحاولة لاحقًا."
        )
        context.user_data.clear()

    return ConversationHandler.END


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs out the user and clears stored session."""
    uid = update.effective_user.id
    if ensure_session(uid, context):
        delete_session(uid)
        context.user_data.clear()
        await update.message.reply_text(
            "تم تسجيل الخروج بنجاح! 🔒\n"
            "لاستخدام البوت مجددًا، يرجى تسجيل الدخول باستخدام /login."
        )
    else:
        await update.message.reply_text("أنت لست مسجل الدخول حاليًا.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the login conversation."""
    await update.message.reply_text("تم إلغاء عملية تسجيل الدخول.")
    context.user_data.clear()
    return ConversationHandler.END


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles Telegram messages by running the Users CrewAI assistant."""
    user_text = update.message.text.strip()
    if not user_text:
        return

    await update.message.chat.send_action(action="typing")
    status_message = await update.message.reply_text("بفهم طلبك وبراجع البيانات...")

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(ask_users_crew, user_text),
            timeout=180,
        )
        if response:
            await status_message.edit_text(response[:4000])
        else:
            await status_message.edit_text("لم يتم تلقي استجابة.")
    except asyncio.TimeoutError:
        await status_message.edit_text("الموديل أخذ وقت طويل في تحليل الطلب. حاول تكتب الطلب بشكل أقصر.")
    except Exception as e:
        logger.error(f"Error running Users CrewAI agent: {e}")
        await status_message.edit_text(f"حدث خطأ أثناء تشغيل الـ agent: {e}")


def main() -> None:
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN is not set in the environment or .env file.")
        sys.exit(1)

    print("Telegram bot is running. Send messages to the bot.")
    application = Application.builder().token(BOT_TOKEN).build()

    # Login conversation handler
    login_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            STATE_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_email)],
            STATE_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(login_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()


if __name__ == "__main__":
    main()
