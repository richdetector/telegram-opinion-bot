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

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")

# OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")