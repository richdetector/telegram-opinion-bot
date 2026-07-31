from telegram import Bot
from dotenv import load_dotenv
import os
import asyncio

# Carga las variables del archivo .env
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def main():
    bot = Bot(token=TOKEN)
    await bot.send_message(
        chat_id=CHAT_ID,
        text="🚀 ¡Enhorabuena! Tu bot ya está funcionando."
    )

if __name__ == "__main__":
    asyncio.run(main())