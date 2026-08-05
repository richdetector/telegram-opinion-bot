import asyncio
import time

from collector import get_news, enrich_news
from telegram_reader import get_telegram_news

from filter import clean_news
from classifier import classify_news
from enricher import enrich_metadata

from editor_selector import select_news_with_ai
from editor_writer import write_news
from editor_reviewer import review_report

from formatter import format_report
from telegram_bot import send_review, publish_message
from history import was_sent, remember
from pending import add_pending, is_pending


CANDIDATES = 15
AUTO_PUBLISH_SCORE = 95


async def process_news():

    start = time.perf_counter()

    # RSS + Telegram
    rss_start = time.perf_counter()

    rss_news = get_news(limit_per_feed=10)

    telegram_news = await get_telegram_news(limit=3)

    noticias = rss_news + telegram_news

    rss_time = time.perf_counter() - rss_start

    total_rss = len(rss_news)
    total_telegram = len(telegram_news)

    # Historial + pendientes
    noticias = [
        n
        for n in noticias
        if not was_sent(n.link)
        and not is_pending(n.link)
    ]

    total_after_history = len(noticias)

    # Limpieza
    noticias = clean_news(noticias)
    total_clean = len(noticias)

    # Clasificador
    classifier_start = time.perf_counter()
    noticias = classify_news(noticias)
    classifier_time = time.perf_counter() - classifier_start

    # Top candidatas
    noticias.sort(key=lambda n: n.score, reverse=True)
    noticias = noticias[:CANDIDATES]
    total_candidates = len(noticias)

    # Enriquecimiento IA
    enricher_start = time.perf_counter()
    noticias = enrich_metadata(noticias)
    enricher_time = time.perf_counter() - enricher_start

    print("\n==================== SCORES ====================")

    for noticia in noticias:

        print(
            f"{noticia.score:>3} | "
            f"{noticia.editorial_topic:<30} | "
            f"{noticia.title}"
        )

    print("================================================\n")

    # Reordenar por score IA
    noticias.sort(key=lambda n: n.score, reverse=True)

    # Selector IA
    selector_start = time.perf_counter()
    noticias = select_news_with_ai(noticias)
    selector_time = time.perf_counter() - selector_start

    # Si hoy no hay ninguna noticia realmente importante
    if not noticias:

        print("\n✅ No hay noticias suficientemente relevantes para publicar.\n")
        return

    # Descargar contenido completo
    download_start = time.perf_counter()
    noticias = enrich_news(noticias)
    download_time = time.perf_counter() - download_start

    # Writer
    writer_start = time.perf_counter()
    informe = write_news(noticias)
    writer_time = time.perf_counter() - writer_start

    # Reviewer
    reviewer_start = time.perf_counter()
    revision = review_report(informe, len(noticias))
    reviewer_time = time.perf_counter() - reviewer_start

    if not revision["ok"]:

        print("\n⚠️ Observaciones del reviewer:\n")

        for error in revision["errors"]:
            print("-", error)

        print("\nEl boletín se enviará igualmente.\n")

    mensajes = format_report(informe)

    auto_published = 0
    pending_reviews = 0

    for noticia, mensaje in zip(noticias, mensajes):

        if noticia.score >= AUTO_PUBLISH_SCORE:

            await publish_message(mensaje)

            remember(
                noticia,
                "published"
            )

            auto_published += 1

            print(
                f"🚀 Publicación automática ({noticia.score}/100): "
                f"{noticia.title}"
            )

        else:

            pending_id = add_pending(
                news=noticia,
                message=mensaje,
            )

            await send_review(
                text=mensaje,
                pending_id=pending_id,
            )

            pending_reviews += 1

    total_time = time.perf_counter() - start

    print("\n==============================")
    print("RESUMEN DE EJECUCIÓN")
    print("==============================")
    print(f"RSS leídos:              {total_rss}")
    print(f"Telegram leídos:         {total_telegram}")
    print(f"Tras historial:          {total_after_history}")
    print(f"Tras limpieza:           {total_clean}")
    print(f"Candidatas IA:           {total_candidates}")
    print(f"Seleccionadas por IA:    {len(noticias)}")
    print(f"Publicadas auto:         {auto_published}")
    print(f"Enviadas a redacción:    {pending_reviews}")
    print()
    print(f"Tiempo RSS:              {rss_time:.2f}s")
    print(f"Tiempo clasificador:     {classifier_time:.2f}s")
    print(f"Tiempo enricher IA:      {enricher_time:.2f}s")
    print(f"Tiempo selector IA:      {selector_time:.2f}s")
    print(f"Tiempo descarga:         {download_time:.2f}s")
    print(f"Tiempo writer IA:        {writer_time:.2f}s")
    print(f"Tiempo reviewer IA:      {reviewer_time:.2f}s")
    print(f"Tiempo total:            {total_time:.2f}s")
    print("==============================\n")


async def main():

    await process_news()


if __name__ == "__main__":

    asyncio.run(main())