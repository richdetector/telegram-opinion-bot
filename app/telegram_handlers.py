from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot import publish_message
from pending import get_pending, remove_pending
from history import remember


class PendingNews:

    def __init__(self, data):

        self.title = data["title"]
        self.link = data["link"]
        self.category = data["category"]
        self.score = data["score"]
        self.editorial_topic = data["editorial_topic"]

        self.source = data["source"]
        self.published = data["published"]
        self.content = data["content"]


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    action, pending_id = query.data.split(":")

    pending = get_pending(pending_id)

    if pending is None:

        await query.edit_message_text(
            "⚠️ Esta noticia ya no está disponible."
        )

        return

    news = PendingNews(pending["news"])

    if action == "publish":

        await publish_message(
            pending["message"]
        )

        remember(
            news,
            "published"
        )

        remove_pending(pending_id)

        await query.edit_message_reply_markup(reply_markup=None)

        await query.answer("✅ Publicada")

        return

    if action == "discard":

        remember(
            news,
            "discarded"
        )

        remove_pending(pending_id)

        await query.edit_message_text(
            "🗑️ Noticia descartada."
        )

        return

    if action == "rewrite":

        await query.answer(
            "🚧 Reedición todavía no implementada."
        )

        return