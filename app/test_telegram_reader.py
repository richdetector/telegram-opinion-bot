import asyncio

from telegram_reader import get_telegram_news


async def main():

    noticias = await get_telegram_news(limit=3)

    print()

    print(f"Noticias encontradas: {len(noticias)}")

    print()

    for noticia in noticias:

        print("=" * 80)

        print(noticia.source)

        print(noticia.title)

        print(noticia.link)

        print()


if __name__ == "__main__":

    asyncio.run(main())