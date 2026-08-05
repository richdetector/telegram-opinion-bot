import asyncio

from telegram import Bot

from config import TELEGRAM_TOKEN


async def main():

    bot = Bot(token=TELEGRAM_TOKEN)

    updates = await bot.get_updates()

    if not updates:
        print("\nNo hay actualizaciones.\n")
        print("Escribe un mensaje en el grupo y vuelve a ejecutar.\n")
        return

    print()

    for update in updates:

        chat = update.effective_chat

        if chat:

            print("--------------------------------")
            print("Nombre :", chat.title)
            print("Tipo   :", chat.type)
            print("ID     :", chat.id)
            print("--------------------------------")


if __name__ == "__main__":

    asyncio.run(main())