import asyncio
from datetime import datetime

from config import TELEGRAM_TIMEOUT_SECONDS
from telegram_client import client
from telegram_sources import CHANNELS

from models import NewsItem
from sources_registry import apply_source_metadata


async def get_telegram_news(limit=5, diagnostics=None, seen_cache=None):

    news = []

    try:
        await asyncio.wait_for(
            client.start(),
            timeout=TELEGRAM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        if diagnostics is not None:
            diagnostics["telegram_timeout"] += 1
        print("⚠️ Telegram start: TIMEOUT", flush=True)
        return news

    try:
        for channel in CHANNELS:

            try:
                source_state = seen_cache.get_source_state(channel) if seen_cache else {}
                last_message_id = int(source_state.get("last_seen_entry_id") or 0)

                kwargs = {"limit": limit}
                if last_message_id:
                    kwargs["min_id"] = last_message_id

                messages = await asyncio.wait_for(
                    client.get_messages(channel, **kwargs),
                    timeout=TELEGRAM_TIMEOUT_SECONDS,
                )

                max_message_id = last_message_id

                for message in messages:
                    max_message_id = max(max_message_id, int(message.id or 0))

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

                if seen_cache and max_message_id > last_message_id:
                    seen_cache.update_source_state(
                        channel,
                        entry_id=str(max_message_id),
                        published=str(datetime.utcnow()),
                        latest_urls="",
                    )

            except asyncio.TimeoutError:
                if diagnostics is not None:
                    diagnostics["telegram_timeout"] += 1
                if seen_cache:
                    seen_cache.increment_source(channel, "timeouts")
                print(f"⚠️ {channel}: TIMEOUT", flush=True)

            except Exception as e:
                if seen_cache:
                    seen_cache.increment_source(channel, "errors")

                print(f"⚠️ {channel}: {e}", flush=True)

    finally:
        try:
            await asyncio.wait_for(
                client.disconnect(),
                timeout=TELEGRAM_TIMEOUT_SECONDS,
            )
        except Exception:
            pass

    return news
