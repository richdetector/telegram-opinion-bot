import asyncio
import time

from collector import get_news, enrich_news
from telegram_reader import get_telegram_news

from filter import clean_news
from classifier import classify_news
from market_scorer import can_reach_selection, score_market_news
from verification import passes_publish_safety, verify_news
from deduper import dedupe_news
from enricher import enrich_metadata

from editor_selector import select_news_with_ai
from editor_writer import write_news
from editor_reviewer import review_report

from auto_publish_engine import should_auto_publish
from formatter import format_report
from telegram_bot import publish_message
from history import was_sent, remember
from pending import is_pending


PRE_CANDIDATES = 30
MAX_PUBLICATIONS = 2
RSS_LIMIT_PER_FEED = 10
TELEGRAM_LIMIT_PER_CHANNEL = 3


def _preselect_market_candidates(news):

    candidates = [
        item
        for item in news
        if can_reach_selection(item)
    ]

    candidates.sort(
        key=lambda item: (
            item.materiality == "CRITICAL",
            item.market_impact,
            item.confluence_score,
            item.source_reliability,
            item.source_speed,
        ),
        reverse=True,
    )

    return candidates[:PRE_CANDIDATES]


async def process_news():

    start = time.perf_counter()

    acquisition_start = time.perf_counter()

    rss_news = get_news(limit_per_feed=RSS_LIMIT_PER_FEED)
    telegram_news = await get_telegram_news(limit=TELEGRAM_LIMIT_PER_CHANNEL)
    noticias = rss_news + telegram_news

    acquisition_time = time.perf_counter() - acquisition_start

    total_rss = len(rss_news)
    total_telegram = len(telegram_news)

    noticias = [
        n
        for n in noticias
        if not was_sent(n.link)
        and not is_pending(n.link)
    ]

    total_after_history = len(noticias)

    noticias = clean_news(noticias)
    total_clean = len(noticias)

    classifier_start = time.perf_counter()
    noticias = classify_news(noticias)
    noticias = score_market_news(noticias)
    classifier_time = time.perf_counter() - classifier_start

    noticias = _preselect_market_candidates(noticias)
    total_precandidates = len(noticias)

    if not noticias:
        print("\n✅ No hay señales con impacto material suficiente.\n")
        return

    download_start = time.perf_counter()
    noticias = enrich_news(noticias)
    noticias = score_market_news(noticias)
    download_time = time.perf_counter() - download_start

    enricher_start = time.perf_counter()
    noticias = enrich_metadata(noticias)
    noticias = score_market_news(noticias)
    noticias = verify_news(noticias)
    noticias = dedupe_news(noticias)
    enricher_time = time.perf_counter() - enricher_start

    noticias.sort(
        key=lambda n: (
            n.materiality == "CRITICAL",
            n.market_impact,
            n.confluence_score,
            n.source_reliability,
        ),
        reverse=True,
    )

    print("\n==================== MARKET IMPACT ====================")

    for noticia in noticias:

        print(
            f"{noticia.market_impact:>3} | "
            f"{noticia.materiality:<8} | "
            f"{noticia.verification_status:<11} | "
            f"{','.join(noticia.affected_assets)[:28]:<28} | "
            f"{noticia.title}"
        )

    print("=======================================================\n")

    selector_start = time.perf_counter()
    noticias = select_news_with_ai(noticias)
    noticias = noticias[:MAX_PUBLICATIONS]
    selector_time = time.perf_counter() - selector_start

    noticias = [
        item
        for item in noticias
        if passes_publish_safety(item)
    ]

    if not noticias:

        print("\n✅ El selector no encontró acontecimientos publicables.\n")
        return

    writer_start = time.perf_counter()
    informe = write_news(noticias)
    writer_time = time.perf_counter() - writer_start

    reviewer_start = time.perf_counter()
    revision = review_report(informe, len(noticias))
    reviewer_time = time.perf_counter() - reviewer_start

    if not should_auto_publish(revision, noticias):

        print("\n⛔ Reviewer bloqueó la publicación:\n")

        for error in revision.get("errors", []):
            print("-", error)

        print("\nNo se publica nada en este ciclo.\n")
        return

    mensajes = format_report(informe)

    auto_published = 0

    for noticia, mensaje in zip(noticias, mensajes):

        await publish_message(mensaje)

        remember(
            noticia,
            "published"
        )

        auto_published += 1

        print(
            f"🚀 Publicado automáticamente ({noticia.market_impact}/100): "
            f"{noticia.title}"
        )

    total_time = time.perf_counter() - start

    print("\n==============================")
    print("RESUMEN DE EJECUCIÓN")
    print("==============================")
    print(f"RSS leídos:              {total_rss}")
    print(f"Telegram leídos:         {total_telegram}")
    print(f"Tras historial:          {total_after_history}")
    print(f"Tras limpieza:           {total_clean}")
    print(f"Precandidatas mercado:   {total_precandidates}")
    print(f"Seleccionadas por IA:    {len(noticias)}")
    print(f"Publicadas auto:         {auto_published}")
    print()
    print(f"Tiempo adquisición:      {acquisition_time:.2f}s")
    print(f"Tiempo clasificador:     {classifier_time:.2f}s")
    print(f"Tiempo descarga:         {download_time:.2f}s")
    print(f"Tiempo enricher/verif:   {enricher_time:.2f}s")
    print(f"Tiempo selector IA:      {selector_time:.2f}s")
    print(f"Tiempo writer IA:        {writer_time:.2f}s")
    print(f"Tiempo reviewer IA:      {reviewer_time:.2f}s")
    print(f"Tiempo total:            {total_time:.2f}s")
    print("==============================\n")


async def main():

    await process_news()


if __name__ == "__main__":

    asyncio.run(main())
