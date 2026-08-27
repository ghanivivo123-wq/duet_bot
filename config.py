import os
import sys
import logging
from functools import wraps
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ContextTypes

# Load .env file
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

# Config variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
GOOGLE_SERVICE_ACCOUNT_JSON_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH", "service_account.json").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()

# Parse ALLOWED_CHAT_ID safely
_raw_chat_id = os.getenv("ALLOWED_CHAT_ID", "").strip()
try:
    ALLOWED_CHAT_ID = int(_raw_chat_id) if _raw_chat_id else None
except ValueError:
    ALLOWED_CHAT_ID = None
    logger.error("ALLOWED_CHAT_ID must be a valid integer.")


def validate_config() -> bool:
    """Validate all required configuration variables."""
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if ALLOWED_CHAT_ID is None:
        missing.append("ALLOWED_CHAT_ID")
    if not GOOGLE_SHEET_ID:
        missing.append("GOOGLE_SHEET_ID")
    if not GOOGLE_SERVICE_ACCOUNT_JSON_PATH and not GOOGLE_SERVICE_ACCOUNT_JSON:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON_PATH (atau GOOGLE_SERVICE_ACCOUNT_JSON)")

    if missing:
        logger.critical(
            "Konfigurasi belum lengkap! Variabel berikut hilang atau kosong di .env:\n  - %s",
            "\n  - ".join(missing),
        )
        return False

    # If raw JSON string is provided, skip file path check
    if GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SERVICE_ACCOUNT_JSON.startswith("{"):
        return True

    # Check if Google Service Account JSON exists
    sa_path = Path(GOOGLE_SERVICE_ACCOUNT_JSON_PATH)
    if not sa_path.is_absolute():
        sa_path = Path(__file__).resolve().parent / sa_path
    if not sa_path.exists():
        logger.warning(
            "File Service Account '%s' tidak ditemukan di path yang ditentukan! "
            "Pastikan file JSON kredensial Google Cloud sudah diletakkan dengan benar.",
            sa_path,
        )

    return True


def is_authorized(chat_id: int) -> bool:
    """Check if the user is authorized."""
    if ALLOWED_CHAT_ID is None:
        return False
    return chat_id == ALLOWED_CHAT_ID


def restricted(func):
    """
    Decorator for Telegram handlers to silently ignore or restrict unauthorized users.
    Single-user security constraint.
    """
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        chat = update.effective_chat
        
        if not chat or not is_authorized(chat.id):
            logger.warning(
                "Akses ditolak untuk user_id: %s (username: %s, chat_id: %s)",
                getattr(user, "id", None),
                getattr(user, "username", None),
                getattr(chat, "id", None),
            )
            # Silent ignore: do not respond to unauthorized users
            return None
        return await func(update, context, *args, **kwargs)

    return wrapped
