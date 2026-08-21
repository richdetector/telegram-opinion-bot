from config import AUTO_PUBLISH_SHADOW, DRY_RUN
from editorial_image import prepare_editorial_image
from history import remember
from telegram_bot import publish_message, publish_photo, send_review


class DryRunPublishBlocked(RuntimeError):
    pass


async def safe_publish_message(text):
    if DRY_RUN:
        raise DryRunPublishBlocked(
            "DRY_RUN=true blocks Telegram publication."
        )
    if AUTO_PUBLISH_SHADOW:
        raise DryRunPublishBlocked(
            "AUTO_PUBLISH_SHADOW=true blocks Telegram publication."
        )

    return await publish_message(text)


async def safe_publish_photo(image_path, caption=""):
    if DRY_RUN:
        raise DryRunPublishBlocked(
            "DRY_RUN=true blocks Telegram photo publication."
        )
    if AUTO_PUBLISH_SHADOW:
        raise DryRunPublishBlocked(
            "AUTO_PUBLISH_SHADOW=true blocks Telegram photo publication."
        )

    return await publish_photo(image_path, caption=caption)


async def safe_send_review(*args, **kwargs):
    if DRY_RUN:
        raise DryRunPublishBlocked(
            "DRY_RUN=true blocks Telegram review messages."
        )
    if AUTO_PUBLISH_SHADOW:
        raise DryRunPublishBlocked(
            "AUTO_PUBLISH_SHADOW=true blocks Telegram review messages."
        )

    return await send_review(*args, **kwargs)


async def publish_selected(news, messages):
    published = 0

    for item, message in zip(news, messages):
        image_path = prepare_editorial_image(item)
        if image_path:
            caption = message
            if len(caption) > 1000:
                caption = caption[:950].rstrip() + "\n\nTexto completo a continuacion."
                await safe_publish_photo(image_path, caption=caption)
                await safe_publish_message(message)
            else:
                await safe_publish_photo(image_path, caption=caption)
        else:
            await safe_publish_message(message)

        remember(
            item,
            "published",
        )

        published += 1

    return published
