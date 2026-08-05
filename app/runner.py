import asyncio
from datetime import datetime

from main import process_news


CHECK_EVERY = 300  # 5 minutos


async def runner():

    print("\n🚀 Radar Crítico iniciado.\n")

    while True:

        start = datetime.now()

        print(f"[{start.strftime('%H:%M:%S')}] 🔎 Buscando noticias...")

        try:

            await process_news()

        except Exception as e:

            print(f"\n❌ ERROR: {e}\n")

        end = datetime.now()

        elapsed = (end - start).total_seconds()

        print(
            f"[{end.strftime('%H:%M:%S')}] ✅ Revisión terminada "
            f"({elapsed:.1f}s)"
        )

        print(f"⏳ Esperando {CHECK_EVERY} segundos...\n")

        await asyncio.sleep(CHECK_EVERY)


if __name__ == "__main__":

    asyncio.run(runner())