from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from config import (
    TELEGRAM_TOKEN,
    EDITOR_CHAT_ID,
    CHANNEL_CHAT_ID,
)


bot = Bot(token=TELEGRAM_TOKEN)


async def publish_message(text):

    await bot.send_message(
        chat_id=CHANNEL_CHAT_ID,
        text=text,
        parse_mode="Markdown",
    )


async def send_review(
    text,
    pending_id,
    reply_to_message_id=None,
):

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🟢 Publicar",
                    callback_data=f"publish:{pending_id}",
                ),
                InlineKeyboardButton(
                    "🟡 Reeditar",
                    callback_data=f"rewrite:{pending_id}",
                ),
                InlineKeyboardButton(
                    "🔴 Descartar",
                    callback_data=f"discard:{pending_id}",
                ),
            ]
        ]
    )

    return await bot.send_message(
        chat_id=EDITOR_CHAT_ID,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
        reply_to_message_id=reply_to_message_id,
    )