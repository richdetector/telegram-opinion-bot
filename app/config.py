import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# Telegram Bot

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Grupo privado (borradores)
EDITOR_CHAT_ID = os.getenv("EDITOR_CHAT_ID")

# Canal público
CHANNEL_CHAT_ID = os.getenv("CHANNEL_CHAT_ID")

# Telegram Client (Telethon)

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID") or 0)
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")

# OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Optional market data providers
BLOCKWORKS_API_KEY = os.getenv("BLOCKWORKS_API_KEY")
GLASSNODE_API_KEY = os.getenv("GLASSNODE_API_KEY")


def _env_bool(name, default=False):
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


# Safe default: never publish unless explicitly disabled.
DRY_RUN = _env_bool("DRY_RUN", default=True)
