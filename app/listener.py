from telegram.ext import (
    Application,
    CallbackQueryHandler,
)

from config import TELEGRAM_TOKEN
from telegram_handlers import callback_handler


app = Application.builder().token(TELEGRAM_TOKEN).build()

app.add_handler(
    CallbackQueryHandler(callback_handler)
)


def main():

    print("🎧 Escuchando botones...")

    app.run_polling()


if __name__ == "__main__":

    main()
