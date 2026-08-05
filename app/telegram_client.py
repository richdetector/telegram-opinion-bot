from telethon import TelegramClient

from config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
)

client = TelegramClient(
    "radar_session",
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
)