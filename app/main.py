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
from config import DRY_RUN
from crypto_market_engine import fetch_btc_market_state, market_state_to_news_item
from diagnostics import (
    count_market_discards,
    count_selector_rejections,
    empty_discard_counter,
)
from dry_run_report import (
    print_btc_market_state,
    print_dry_run_report,
    print_funnel_summary,
)
from formatter import format_report
from publishing import publish_selected
from history import was_sent
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
    funnel = {}
    discard_counters = empty_discard_counter()

    acquisition_start = time.perf_counter()

    rss_news = get_news(limit_per_feed=RSS_LIMIT_PER_FEED)
    telegram_news = await get_telegram_news(limit=TELEGRAM_LIMIT_PER_CHANNEL)
    btc_market_state = fetch_btc_market_state() if DRY_RUN else None
    market_state_news = (
        [market_state_to_news_item(btc_market_state)]
        if DRY_RUN
        else []
    )
    market_state_news = [
        item
        for item in market_state_news
        if item is not None
    ]
    noticias = rss_news + telegram_news
    noticias.extend(market_state_news)

    acquisition_time = time.perf_counter() - acquisition_start

    total_rss = len(rss_news)
    total_telegram = len(telegram_news)
    funnel["rss"] = total_rss
    funnel["telegram"] = total_telegram

    noticias = [
        n
        for n in noticias
        if not was_sent(n.link)
        and not is_pending(n.link)
    ]

    total_after_history = len(noticias)

    noticias = clean_news(noticias)
    total_clean = len(noticias)
    funnel["after_filter"] = total_clean

    classifier_start = time.perf_counter()
    noticias = classify_news(noticias)
    noticias = score_market_news(noticias)
    classifier_time = time.perf_counter() - classifier_start
    funnel["after_market_scorer"] = len(noticias)
    discard_counters.update(count_market_discards(noticias))

    noticias = _preselect_market_candidates(noticias)
    total_precandidates = len(noticias)
    funnel["precandidates"] = total_precandidates

    if not noticias:
        funnel["after_enrichment"] = 0
        funnel["after_verification"] = 0
        funnel["after_deduper"] = 0
        funnel["selected"] = 0
        funnel["reviewer_pass"] = False
        funnel["would_publish"] = 0
        print_funnel_summary(funnel, discard_counters)
        if DRY_RUN:
            print_btc_market_state(btc_market_state)
        print("\nRADAR: NO MATERIAL EVENTS\n")
        return

    download_start = time.perf_counter()
    noticias = enrich_news(noticias)
    noticias = score_market_news(noticias)
    download_time = time.perf_counter() - download_start

    enricher_start = time.perf_counter()
    noticias = enrich_metadata(noticias)
    funnel["after_enrichment"] = len(noticias)
    noticias = score_market_news(noticias)
    noticias = verify_news(noticias)
    funnel["after_verification"] = len(noticias)
    before_dedupe = len(noticias)
    noticias = dedupe_news(noticias)
    discard_counters["duplicate"] += max(0, before_dedupe - len(noticias))
    funnel["after_deduper"] = len(noticias)
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
    selector_input = list(noticias)
    noticias = select_news_with_ai(noticias)
    noticias = noticias[:MAX_PUBLICATIONS]
    selector_time = time.perf_counter() - selector_start
    funnel["selected"] = len(noticias)
    discard_counters["selector_rejected"] += count_selector_rejections(
        selector_input,
        noticias,
    )

    before_safety = list(noticias)
    noticias = [
        item
        for item in noticias
        if passes_publish_safety(item)
    ]
    safety_links = {item.link for item in noticias}
    for item in before_safety:
        if item.link not in safety_links:
            if item.confidence == "Baja":
                discard_counters["low_confidence"] += 1
            elif item.source_type == "COMMUNITY":
                discard_counters["weak_source"] += 1
            else:
                discard_counters["low_materiality"] += 1

    if not noticias:
        funnel["reviewer_pass"] = False
        funnel["would_publish"] = 0
        print_funnel_summary(funnel, discard_counters)
        if DRY_RUN:
            print_btc_market_state(btc_market_state)
        print_dry_run_report([], [])
        return

    writer_start = time.perf_counter()
    informe = write_news(noticias)
    writer_time = time.perf_counter() - writer_start

    reviewer_start = time.perf_counter()
    revision = review_report(informe, len(noticias))
    reviewer_time = time.perf_counter() - reviewer_start
    reviewer_pass = bool(revision.get("ok"))
    funnel["reviewer_pass"] = reviewer_pass

    if not should_auto_publish(revision, noticias):
        discard_counters["reviewer_rejected"] += len(noticias)
        funnel["would_publish"] = 0

        print("\n⛔ Reviewer bloqueó la publicación:\n")

        for error in revision.get("errors", []):
            print("-", error)

        print("\nNo se publica nada en este ciclo.\n")
        print_funnel_summary(funnel, discard_counters)
        if DRY_RUN:
            print_btc_market_state(btc_market_state)
        return

    mensajes = format_report(informe)
    funnel["would_publish"] = len(mensajes)

    if DRY_RUN:
        print_funnel_summary(funnel, discard_counters)
        print_btc_market_state(btc_market_state)
        print_dry_run_report(noticias, mensajes)
        return

    auto_published = await publish_selected(noticias, mensajes)

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
