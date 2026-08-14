import asyncio
import time

from collector import get_news, enrich_news
from telegram_reader import get_telegram_news

from filter import clean_news
from classifier import classify_news
from market_scorer import (
    can_reach_selection,
    pre_candidate_acceptance_reason,
    score_market_news,
)
from verification import verify_news
from deduper import dedupe_news
from enricher import enrich_metadata

from editor_selector import select_news_with_ai
from editor_writer import write_news
from editor_reviewer import review_report

from config import AUTO_PUBLISH_SHADOW, DRY_RUN
from crypto_market_engine import fetch_btc_market_state, market_state_to_news_item
from diagnostics import (
    count_market_discards,
    count_pre_candidate_rejections,
    count_selector_rejections,
    empty_discard_counter,
)
from dry_run_report import (
    print_btc_market_state,
    print_dry_run_report,
    print_final_decision_gate,
    print_funnel_summary,
)
from formatter import format_report
from publication_gate import apply_publication_gate
from publishing import publish_selected
from reddit_reader import get_reddit_news
from rumor_gate import apply_rumor_gate
from sentiment_engine import sentiment_from_reddit_status
from truth_social_reader import get_truth_social_news
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


def _print_pre_candidates(news):
    print("\n====================")
    print("PRE-CANDIDATES")
    print("====================")

    if not news:
        print("None")
        print("====================\n")
        return

    for item in news:
        print(f"title: {item.title}")
        print(f"score: {item.score}")
        print(f"market_impact: {item.market_impact}")
        print(f"materiality: {item.materiality}")
        print(f"verification_status: {item.verification_status}")
        print(f"is_rumor: {item.is_rumor}")
        print(f"source: {item.source}")
        print(f"source_type: {item.source_type}")
        print(f"event_type: {item.event_type}")
        print(f"affected_assets: {','.join(item.affected_assets)}")
        print(f"reason_accepted: {pre_candidate_acceptance_reason(item)}")
        print("----------------------------------------")

    print("====================\n")


def _revalidate_precandidates_after_download(news):
    return [
        item
        for item in news
        if can_reach_selection(item)
    ]


async def process_news():

    start = time.perf_counter()
    funnel = {}
    discard_counters = empty_discard_counter()

    acquisition_start = time.perf_counter()

    rss_news = get_news(limit_per_feed=RSS_LIMIT_PER_FEED)
    telegram_news = await get_telegram_news(limit=TELEGRAM_LIMIT_PER_CHANNEL)
    reddit_news, reddit_status = get_reddit_news()
    truth_news, truth_status = get_truth_social_news()
    market_state_enabled = DRY_RUN or AUTO_PUBLISH_SHADOW
    btc_market_state = (
        fetch_btc_market_state(
            sentiment_fetcher=lambda: sentiment_from_reddit_status(reddit_status)
        )
        if market_state_enabled
        else None
    )
    market_state_news = (
        [market_state_to_news_item(btc_market_state)]
        if market_state_enabled
        else []
    )
    market_state_news = [
        item
        for item in market_state_news
        if item is not None
    ]
    noticias = rss_news + telegram_news + reddit_news + truth_news
    noticias.extend(market_state_news)

    acquisition_time = time.perf_counter() - acquisition_start

    total_rss = len(rss_news)
    total_telegram = len(telegram_news)
    funnel["rss"] = total_rss
    funnel["telegram"] = total_telegram
    funnel["reddit"] = len(reddit_news)
    funnel["truth_social"] = len(truth_news)
    funnel["market_state_signals"] = len(market_state_news)
    funnel["reddit_status"] = reddit_status
    funnel["truth_social_status"] = truth_status

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
    discard_counters.update(count_pre_candidate_rejections(noticias))

    noticias = _preselect_market_candidates(noticias)
    total_precandidates = len(noticias)
    funnel["precandidates"] = total_precandidates
    _print_pre_candidates(noticias)

    if not noticias:
        funnel["after_enrichment"] = 0
        funnel["after_verification"] = 0
        funnel["after_deduper"] = 0
        funnel["selected"] = 0
        funnel["reviewer_pass"] = False
        funnel["would_publish"] = 0
        print_funnel_summary(funnel, discard_counters)
        if market_state_enabled:
            print_btc_market_state(btc_market_state)
        print("\nRADAR: NO MATERIAL EVENTS\n")
        return

    download_start = time.perf_counter()
    noticias = enrich_news(noticias)
    noticias = score_market_news(noticias)
    noticias = _revalidate_precandidates_after_download(noticias)
    download_time = time.perf_counter() - download_start

    if not noticias:
        funnel["after_enrichment"] = 0
        funnel["after_verification"] = 0
        funnel["after_deduper"] = 0
        funnel["selected"] = 0
        funnel["reviewer_pass"] = False
        funnel["would_publish"] = 0
        print_funnel_summary(funnel, discard_counters)
        if market_state_enabled:
            print_btc_market_state(btc_market_state)
        print_dry_run_report([], [])
        return

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

    normal_pre, pre_gate_results, pre_gate_counters = apply_publication_gate(
        noticias,
        {"ok": True, "errors": []},
    )
    rumor_pre, rumor_pre_results = apply_rumor_gate(
        noticias,
        {"ok": True, "errors": []},
    )
    normal_links = {item.link for item in normal_pre}
    noticias = normal_pre + [
        item
        for item in rumor_pre
        if item.link not in normal_links
    ]
    normal_pass_links = {result.item.link for result in pre_gate_results if result.passed}
    pre_gate_results = pre_gate_results + [
        result
        for result in rumor_pre_results
        if result.passed and result.item.link not in normal_pass_links
    ]
    discard_counters.update(pre_gate_counters)

    if not noticias:
        funnel["reviewer_pass"] = False
        funnel["would_publish"] = 0
        print_funnel_summary(funnel, discard_counters)
        print_final_decision_gate(pre_gate_results)
        if market_state_enabled:
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

    normal_publishable, final_gate_results, final_gate_counters = apply_publication_gate(
        noticias,
        revision,
    )
    rumor_publishable, rumor_final_results = apply_rumor_gate(
        noticias,
        revision,
    )
    normal_links = {item.link for item in normal_publishable}
    publishable = normal_publishable + [
        item
        for item in rumor_publishable
        if item.link not in normal_links
    ]
    normal_pass_links = {result.item.link for result in final_gate_results if result.passed}
    final_gate_results = final_gate_results + [
        result
        for result in rumor_final_results
        if result.passed and result.item.link not in normal_pass_links
    ]
    discard_counters.update(final_gate_counters)

    if not publishable:
        funnel["would_publish"] = 0

        print("\n⛔ Final decision gate bloqueó la publicación:\n")

        for error in revision.get("errors", []):
            print("-", error)

        print("\nNo se publica nada en este ciclo.\n")
        print_funnel_summary(funnel, discard_counters)
        print_final_decision_gate(final_gate_results)
        if market_state_enabled:
            print_btc_market_state(btc_market_state)
        print_dry_run_report([], [])
        return

    noticias = publishable
    mensajes = format_report(informe)
    mensajes = mensajes[:len(noticias)]
    funnel["would_publish"] = len(mensajes)

    if DRY_RUN or AUTO_PUBLISH_SHADOW:
        print_funnel_summary(funnel, discard_counters)
        print_final_decision_gate(final_gate_results)
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
