import asyncio

from telethon import TelegramClient
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged

from app.config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
)


client = TelegramClient(
    "test_session",
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    connection=ConnectionTcpAbridged,
)


async def main():

    await client.start()

    me = await client.get_me()

    print()

    print("✅ Sesión iniciada correctamente")

    print(f"Usuario: {me.first_name}")

    if me.username:
        print(f"@{me.username}")

    print()

    await client.disconnect()


if __name__ == "__main__":

    asyncio.run(main())