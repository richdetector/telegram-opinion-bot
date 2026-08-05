import asyncio

from telegram_client import client


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