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
SANTIMENT_API_KEY = os.getenv("SANTIMENT_API_KEY")

# Optional Reddit OAuth credentials.
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT")


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
AUTO_PUBLISH_SHADOW = _env_bool("AUTO_PUBLISH_SHADOW", default=False)

# Conservative publication gate defaults.
AUTO_PUBLISH_ALLOW_MEDIUM = _env_bool("AUTO_PUBLISH_ALLOW_MEDIUM", default=False)
AUTO_PUBLISH_ALLOW_CRITICAL_RUMORS = _env_bool(
    "AUTO_PUBLISH_ALLOW_CRITICAL_RUMORS",
    default=False,
)
AUTO_PUBLISH_MAX_PER_CYCLE = int(os.getenv("AUTO_PUBLISH_MAX_PER_CYCLE") or 2)
AUTO_PUBLISH_MAX_PER_DAY = int(os.getenv("AUTO_PUBLISH_MAX_PER_DAY") or 2)
AUTO_PUBLISH_DUPLICATE_WINDOW_HOURS = int(
    os.getenv("AUTO_PUBLISH_DUPLICATE_WINDOW_HOURS") or 24
)

# Network/runtime safety defaults for unattended 24/7 operation.
RSS_TIMEOUT_SECONDS = int(os.getenv("RSS_TIMEOUT_SECONDS") or 15)
ARTICLE_TIMEOUT_SECONDS = int(os.getenv("ARTICLE_TIMEOUT_SECONDS") or 15)
TELEGRAM_TIMEOUT_SECONDS = int(os.getenv("TELEGRAM_TIMEOUT_SECONDS") or 30)
MARKET_DATA_TIMEOUT_SECONDS = int(os.getenv("MARKET_DATA_TIMEOUT_SECONDS") or 15)
RSS_PHASE_TIMEOUT_SECONDS = int(os.getenv("RSS_PHASE_TIMEOUT_SECONDS") or 60)
MARKET_DATA_PHASE_TIMEOUT_SECONDS = int(os.getenv("MARKET_DATA_PHASE_TIMEOUT_SECONDS") or 60)
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS") or 60)
CYCLE_TIMEOUT_SECONDS = int(os.getenv("CYCLE_TIMEOUT_SECONDS") or 180)

# Quiet Market Mode: secondary lane for infrequent market-state notes.
QUIET_MARKET_ENABLED = _env_bool("QUIET_MARKET_ENABLED", default=True)
QUIET_MARKET_AFTER_HOURS = int(os.getenv("QUIET_MARKET_AFTER_HOURS") or 12)
QUIET_MARKET_MAX_PER_DAY = int(os.getenv("QUIET_MARKET_MAX_PER_DAY") or 1)
QUIET_MARKET_MIN_SCORE = int(os.getenv("QUIET_MARKET_MIN_SCORE") or 70)

# Intraday BTC lane: separate from structural market alerts.
INTRADAY_ENGINE_ENABLED = _env_bool("INTRADAY_ENGINE_ENABLED", default=True)
INTRADAY_MIN_CONFLUENCE = int(os.getenv("INTRADAY_MIN_CONFLUENCE") or 75)
INTRADAY_MAX_DATA_AGE_MINUTES = int(os.getenv("INTRADAY_MAX_DATA_AGE_MINUTES") or 10)
INTRADAY_MAX_PER_4H = int(os.getenv("INTRADAY_MAX_PER_4H") or 2)
