from datetime import datetime

from telegram_client import client
from telegram_sources import CHANNELS

from models import NewsItem
from sources_registry import apply_source_metadata


async def get_telegram_news(limit=5):

    news = []

    await client.start()

    for channel in CHANNELS:

        try:

            async for message in client.iter_messages(
                channel,
                limit=limit,
            ):

                if not message.text:
                    continue

                text = message.text.strip()

                if len(text) < 80:
                    continue

                if text.startswith("http"):
                    continue

                if "DM me" in text:
                    continue

                if "auction" in text.lower():
                    continue

                if text.count("#") > 8:
                    continue

                emoji_count = sum(
                    ord(c) > 10000
                    for c in text
                )

                if emoji_count > 10:
                    continue

                item = NewsItem(
                    title=text.split("\n")[0][:200],
                    summary="",
                    content=text,
                    link=f"https://t.me/{channel}/{message.id}",
                    published=str(
                        message.date or datetime.utcnow()
                    ),
                    source=channel,
                    category="Telegram",
                )

                news.append(apply_source_metadata(item))

        except Exception as e:

            print(f"⚠️ {channel}: {e}")

    await client.disconnect()

    return news
