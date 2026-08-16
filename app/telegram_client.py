from telethon import TelegramClient

from config import TELEGRAM_TIMEOUT_SECONDS
from config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
)

client = TelegramClient(
    "radar_session",
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    connection_retries=2,
    request_retries=2,
    retry_delay=2,
    timeout=TELEGRAM_TIMEOUT_SECONDS,
)
