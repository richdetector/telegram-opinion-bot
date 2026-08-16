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

from config import (
    ARTICLE_TIMEOUT_SECONDS,
    AUTO_PUBLISH_SHADOW,
    DRY_RUN,
    MARKET_DATA_TIMEOUT_SECONDS,
    OPENAI_TIMEOUT_SECONDS,
    QUIET_MARKET_ENABLED,
    RSS_TIMEOUT_SECONDS,
    TELEGRAM_TIMEOUT_SECONDS,
)
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
from quiet_market import evaluate_quiet_market, quiet_market_fingerprint
from reddit_reader import get_reddit_news
from rumor_gate import apply_rumor_gate
from runtime_guards import (
    empty_network_counter,
    log_checkpoint,
    run_async_phase,
    run_sync_phase,
)
from seen_cache import SeenCache
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


async def _handle_quiet_market(funnel, btc_market_state, has_market_alert=False):
    seen_cache = funnel.get("seen_cache")
    decision = evaluate_quiet_market(
        btc_market_state,
        has_market_alert=has_market_alert,
        seen_cache=seen_cache,
    )
    funnel["quiet_market"] = decision

    if not decision.passed:
        return 0

    if DRY_RUN or AUTO_PUBLISH_SHADOW:
        print("\n==============================")
        print("QUIET MARKET NOTE CANDIDATE")
        print("==============================")
        print(decision.message)
        print("==============================\n")
        return 0

    published = await publish_selected([decision.note], [decision.message])
    decision.published = bool(published)
    if decision.published and seen_cache:
        seen_cache.remember_quiet_market(
            quiet_market_fingerprint(btc_market_state),
            published=True,
        )
    return published


async def process_news():

    start = time.perf_counter()
    funnel = {}
    discard_counters = empty_discard_counter()
    network_counters = empty_network_counter()
    seen_cache = SeenCache()

    acquisition_start = time.perf_counter()

    log_checkpoint("[cycle] START process_news")

    rss_news = await run_sync_phase(
        "RSS",
        lambda: get_news(
            limit_per_feed=RSS_LIMIT_PER_FEED,
            diagnostics=network_counters,
            seen_cache=seen_cache,
        ),
        timeout=RSS_TIMEOUT_SECONDS,
        fallback=[],
        counters=network_counters,
        timeout_counter="rss_timeout",
    )
    telegram_news = await run_async_phase(
        "TELEGRAM",
        lambda: get_telegram_news(
            limit=TELEGRAM_LIMIT_PER_CHANNEL,
            diagnostics=network_counters,
            seen_cache=seen_cache,
        ),
        timeout=TELEGRAM_TIMEOUT_SECONDS,
        fallback=[],
        counters=network_counters,
        timeout_counter="telegram_timeout",
    )
    reddit_news, reddit_status = await run_sync_phase(
        "REDDIT",
        lambda: get_reddit_news(),
        timeout=MARKET_DATA_TIMEOUT_SECONDS,
        fallback=([], None),
        counters=network_counters,
        timeout_counter="market_data_timeout",
    )
    truth_news, truth_status = await run_sync_phase(
        "TRUTH SOCIAL",
        lambda: get_truth_social_news(),
        timeout=MARKET_DATA_TIMEOUT_SECONDS,
        fallback=([], None),
        counters=network_counters,
        timeout_counter="market_data_timeout",
    )
    market_state_enabled = DRY_RUN or AUTO_PUBLISH_SHADOW or QUIET_MARKET_ENABLED
    btc_market_state = (
        await run_sync_phase(
            "MARKET DATA",
            lambda: fetch_btc_market_state(
                sentiment_fetcher=lambda: sentiment_from_reddit_status(reddit_status)
            ),
            timeout=MARKET_DATA_TIMEOUT_SECONDS,
            fallback=None,
            counters=network_counters,
            timeout_counter="market_data_timeout",
        )
        if market_state_enabled
        else None
    )
    market_state_news = (
        [market_state_to_news_item(btc_market_state)]
        if market_state_enabled and btc_market_state is not None
        else []
    )
    market_state_news = [
        item
        for item in market_state_news
        if item is not None
    ]
    if (
        btc_market_state is not None
        and btc_market_state.onchain is not None
        and "coinmetrics_timeout" in btc_market_state.onchain.errors
    ):
        network_counters["coinmetrics_timeout"] += 1
    noticias = rss_news + telegram_news + reddit_news + truth_news
    noticias.extend(market_state_news)
    collected_total = len(noticias)
    noticias, intake_stats = seen_cache.filter_new_items(noticias)

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
    funnel["network_counters"] = network_counters
    funnel["intake_stats"] = intake_stats
    funnel["source_performance"] = seen_cache.source_performance()
    funnel["seen_cache"] = seen_cache
    funnel["collected_total"] = collected_total

    log_checkpoint("[phase] HISTORY/FILTER START")
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
    log_checkpoint("[phase] HISTORY/FILTER DONE")

    classifier_start = time.perf_counter()
    log_checkpoint("[phase] CLASSIFIER START")
    noticias = classify_news(noticias)
    noticias = score_market_news(noticias)
    classifier_time = time.perf_counter() - classifier_start
    log_checkpoint(f"[phase] CLASSIFIER DONE duration={classifier_time:.2f}s")
    funnel["after_market_scorer"] = len(noticias)
    discard_counters.update(count_market_discards(noticias))
    discard_counters.update(count_pre_candidate_rejections(noticias))
    for item in noticias:
        if not can_reach_selection(item):
            seen_cache.update_item_status(item, "DISCARDED")

    noticias = _preselect_market_candidates(noticias)
    total_precandidates = len(noticias)
    funnel["precandidates"] = total_precandidates
    seen_cache.mark_precandidates(noticias)
    _print_pre_candidates(noticias)

    if not noticias:
        funnel["after_enrichment"] = 0
        funnel["after_verification"] = 0
        funnel["after_deduper"] = 0
        funnel["selected"] = 0
        funnel["reviewer_pass"] = False
        funnel["would_publish"] = 0
        await _handle_quiet_market(funnel, btc_market_state)
        print_funnel_summary(funnel, discard_counters)
        if market_state_enabled:
            print_btc_market_state(btc_market_state)
        print("\nRADAR: NO MATERIAL EVENTS\n")
        log_checkpoint("[cycle] DONE process_news")
        return

    download_start = time.perf_counter()
    noticias = await run_sync_phase(
        "ARTICLE DOWNLOAD",
        lambda: enrich_news(noticias, diagnostics=network_counters),
        timeout=min(ARTICLE_TIMEOUT_SECONDS * max(1, len(noticias)), 60),
        fallback=[],
        counters=network_counters,
        timeout_counter="article_timeout",
    )
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
        await _handle_quiet_market(funnel, btc_market_state)
        print_funnel_summary(funnel, discard_counters)
        if market_state_enabled:
            print_btc_market_state(btc_market_state)
        print_dry_run_report([], [], dry_run=DRY_RUN, shadow=AUTO_PUBLISH_SHADOW)
        log_checkpoint("[cycle] DONE process_news")
        return

    enricher_start = time.perf_counter()
    noticias = await run_sync_phase(
        "AI ENRICHMENT",
        lambda: enrich_metadata(noticias),
        timeout=OPENAI_TIMEOUT_SECONDS,
        fallback=[],
        counters=network_counters,
        timeout_counter="openai_timeout",
    )
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
    noticias = await run_sync_phase(
        "SELECTOR",
        lambda: select_news_with_ai(noticias),
        timeout=OPENAI_TIMEOUT_SECONDS,
        fallback=[],
        counters=network_counters,
        timeout_counter="openai_timeout",
    )
    noticias = noticias[:MAX_PUBLICATIONS]
    selector_time = time.perf_counter() - selector_start
    funnel["selected"] = len(noticias)
    seen_cache.mark_selected(noticias)
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
        await _handle_quiet_market(funnel, btc_market_state, has_market_alert=True)
        print_funnel_summary(funnel, discard_counters)
        print_final_decision_gate(pre_gate_results)
        if market_state_enabled:
            print_btc_market_state(btc_market_state)
        print_dry_run_report([], [], dry_run=DRY_RUN, shadow=AUTO_PUBLISH_SHADOW)
        log_checkpoint("[cycle] DONE process_news")
        return

    writer_start = time.perf_counter()
    informe = await run_sync_phase(
        "WRITER",
        lambda: write_news(noticias),
        timeout=OPENAI_TIMEOUT_SECONDS,
        fallback=None,
        counters=network_counters,
        timeout_counter="openai_timeout",
    )
    writer_time = time.perf_counter() - writer_start

    if informe is None:
        funnel["reviewer_pass"] = False
        funnel["would_publish"] = 0
        await _handle_quiet_market(funnel, btc_market_state, has_market_alert=True)
        print_funnel_summary(funnel, discard_counters)
        if market_state_enabled:
            print_btc_market_state(btc_market_state)
        print_dry_run_report([], [], dry_run=DRY_RUN, shadow=AUTO_PUBLISH_SHADOW)
        log_checkpoint("[cycle] DONE process_news")
        return

    reviewer_start = time.perf_counter()
    revision = await run_sync_phase(
        "REVIEWER",
        lambda: review_report(informe, len(noticias)),
        timeout=OPENAI_TIMEOUT_SECONDS,
        fallback={"ok": False, "errors": ["openai_timeout"]},
        counters=network_counters,
        timeout_counter="openai_timeout",
    )
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
        await _handle_quiet_market(funnel, btc_market_state, has_market_alert=True)
        print_funnel_summary(funnel, discard_counters)
        print_final_decision_gate(final_gate_results)
        if market_state_enabled:
            print_btc_market_state(btc_market_state)
        print_dry_run_report([], [], dry_run=DRY_RUN, shadow=AUTO_PUBLISH_SHADOW)
        log_checkpoint("[cycle] DONE process_news")
        return

    noticias = publishable
    mensajes = format_report(informe)
    mensajes = mensajes[:len(noticias)]
    funnel["would_publish"] = len(mensajes)

    if DRY_RUN or AUTO_PUBLISH_SHADOW:
        print_funnel_summary(funnel, discard_counters)
        print_final_decision_gate(final_gate_results)
        print_btc_market_state(btc_market_state)
        print_dry_run_report(
            noticias,
            mensajes,
            dry_run=DRY_RUN,
            shadow=AUTO_PUBLISH_SHADOW,
        )
        log_checkpoint("[cycle] DONE process_news")
        return

    auto_published = await run_async_phase(
        "PUBLISHER",
        lambda: publish_selected(noticias, mensajes),
        timeout=TELEGRAM_TIMEOUT_SECONDS,
        fallback=0,
        counters=network_counters,
        timeout_counter="telegram_timeout",
    )
    seen_cache.mark_published(noticias)

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
    log_checkpoint("[cycle] DONE process_news")


async def main():

    await process_news()


if __name__ == "__main__":

    asyncio.run(main())
