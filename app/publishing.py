from config import DRY_RUN
from history import remember
from telegram_bot import publish_message, send_review


class DryRunPublishBlocked(RuntimeError):
    pass


async def safe_publish_message(text):
    if DRY_RUN:
        raise DryRunPublishBlocked(
            "DRY_RUN=true blocks Telegram publication."
        )

    return await publish_message(text)


async def safe_send_review(*args, **kwargs):
    if DRY_RUN:
        raise DryRunPublishBlocked(
            "DRY_RUN=true blocks Telegram review messages."
        )

    return await send_review(*args, **kwargs)


async def publish_selected(news, messages):
    published = 0

    for item, message in zip(news, messages):
        await safe_publish_message(message)

        remember(
            item,
            "published",
        )

        published += 1

    return published
