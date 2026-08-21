import asyncio
import time

from collector import get_news, enrich_news
from telegram_reader import get_telegram_news

from filter import clean_news
from classifier import classify_news
from market_scorer import (
    accepted_by_paths,
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
    DAILY_RECAP_ENABLED,
    MARKET_DATA_TIMEOUT_SECONDS,
    MARKET_DATA_PHASE_TIMEOUT_SECONDS,
    OPENAI_TIMEOUT_SECONDS,
    RSS_PHASE_TIMEOUT_SECONDS,
    QUIET_MARKET_ENABLED,
    TELEGRAM_TIMEOUT_SECONDS,
)
from combined_story import attach_market_reaction_to_news
from crypto_market_engine import fetch_btc_market_state, market_state_to_news_item
from daily_publication_gate import apply_daily_publication_gate
from daily_recap import evaluate_daily_market_recap
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
from editorial_lanes import (
    direct_lane_item,
    lane_for_item,
    sort_for_publication,
    split_selector_lanes,
)
from editorial_image import build_image_brief
from formatter import format_report
from intraday_engine import attach_intraday_catalyst
from intraday_publication_gate import apply_intraday_publication_gate
from market_interpreter import attach_editorial_interpretations
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
MAX_PUBLICATIONS = 6
RSS_LIMIT_PER_FEED = 10
TELEGRAM_LIMIT_PER_CHANNEL = 3


def _preselect_market_candidates(news):

    candidates = [
        item
        for item in news
        if can_reach_selection(item)
    ]

    candidates = sort_for_publication(candidates)

    return candidates[:PRE_CANDIDATES]


def _dedupe_extend(base, additions):
    links = {item.link for item in base}
    for item in additions:
        if item.link not in links:
            base.append(item)
            links.add(item.link)
    return base


def _is_intraday_lane_item(item):
    return (
        lane_for_item(item) in {"INTRADAY_NOTE", "INTRADAY_ALERT"}
    )


def _intraday_flow(funnel):
    return funnel.setdefault(
        "intraday_pipeline",
        {
            "state_decision": "UNKNOWN",
            "candidate_created": "no",
            "market_interpreter": "NOT_RUN",
            "writer": "NOT_RUN",
            "reviewer": "NOT_RUN",
            "note_gate": "NOT_RUN",
            "alert_gate": "NOT_RUN",
            "dedupe": "NOT_RUN",
            "frequency": "NOT_RUN",
            "publisher": "NOT_RUN",
            "final_result": "NO_INTRADAY_CANDIDATE",
            "rejection_reason": "NO_INTRADAY_CANDIDATE",
        },
    )


def _prepare_image_diagnostics(items):
    for item in items:
        brief = build_image_brief(item)
        item.image_eligible = brief.eligible
        item.image_brief = brief.brief


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
        print(f"structural_relevance: {item.structural_news_relevance}")
        print(f"daily_relevance: {item.daily_news_relevance}")
        print(f"intraday_relevance: {item.intraday_news_relevance}")
        print(f"rumor_relevance: {item.rumor_relevance}")
        print(f"accepted_by: {','.join(accepted_by_paths(item))}")
        print(f"reason_accepted: {pre_candidate_acceptance_reason(item)}")
        print(f"image_eligible: {item.image_eligible}")
        if item.image_brief:
            print(f"image_brief: {item.image_brief}")
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
        timeout=RSS_PHASE_TIMEOUT_SECONDS,
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
            timeout=MARKET_DATA_PHASE_TIMEOUT_SECONDS,
            fallback=None,
            counters=network_counters,
            timeout_counter="market_data_timeout",
        )
        if market_state_enabled
        else None
    )
    if (
        btc_market_state is not None
        and btc_market_state.onchain is not None
        and "coinmetrics_timeout" in btc_market_state.onchain.errors
    ):
        network_counters["coinmetrics_timeout"] += 1
    fast_context_news = rss_news + telegram_news + reddit_news + truth_news
    if btc_market_state is not None and getattr(btc_market_state, "intraday", None) is not None:
        attach_intraday_catalyst(btc_market_state.intraday, fast_context_news)

    daily_recap_decision = (
        evaluate_daily_market_recap(btc_market_state, seen_cache=seen_cache)
        if DAILY_RECAP_ENABLED and market_state_enabled
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
    if daily_recap_decision and daily_recap_decision.note is not None:
        market_state_news.append(daily_recap_decision.note)
    intraday_flow = _intraday_flow(funnel)
    intraday_state = getattr(btc_market_state, "intraday", None) if btc_market_state is not None else None
    intraday_flow["state_decision"] = getattr(intraday_state, "decision", "UNKNOWN")
    intraday_flow["candidate_created"] = "yes" if any(_is_intraday_lane_item(item) for item in market_state_news) else "no"
    if intraday_flow["candidate_created"] == "yes":
        intraday_flow["final_result"] = "CANDIDATE_CREATED"
        intraday_flow["rejection_reason"] = ""
    funnel["daily_recap"] = daily_recap_decision

    noticias = list(fast_context_news)
    noticias.extend(market_state_news)
    collected_total = len(noticias)
    noticias, intake_stats = seen_cache.filter_new_items(noticias)
    if intraday_flow["candidate_created"] == "yes":
        intraday_flow["dedupe"] = "PASS" if any(_is_intraday_lane_item(item) for item in noticias) else "FAIL"
        if intraday_flow["dedupe"] == "FAIL":
            intraday_flow["final_result"] = "REJECTED"
            intraday_flow["rejection_reason"] = "duplicate_or_seen_cache"

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
    if btc_market_state is not None and getattr(btc_market_state, "intraday", None) is not None:
        noticias = attach_market_reaction_to_news(noticias, btc_market_state.intraday)
    classifier_time = time.perf_counter() - classifier_start
    log_checkpoint(f"[phase] CLASSIFIER DONE duration={classifier_time:.2f}s")
    funnel["after_market_scorer"] = len(noticias)
    discard_counters.update(count_market_discards(noticias))
    discard_counters.update(count_pre_candidate_rejections(noticias))
    for item in noticias:
        if not can_reach_selection(item):
            seen_cache.update_item_status(item, "DISCARDED")

    noticias = _preselect_market_candidates(noticias)
    _prepare_image_diagnostics(noticias)
    total_precandidates = len(noticias)
    funnel["precandidates"] = total_precandidates
    seen_cache.mark_precandidates(noticias)
    _print_pre_candidates(noticias)
    if intraday_flow["candidate_created"] == "yes" and any(_is_intraday_lane_item(item) for item in noticias):
        intraday_flow["final_result"] = "PRECANDIDATE"
    elif intraday_flow["candidate_created"] == "yes" and intraday_flow.get("dedupe") != "FAIL":
        intraday_flow["final_result"] = "REJECTED"
        intraday_flow["rejection_reason"] = "pre_candidate_filter"

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
    if btc_market_state is not None and getattr(btc_market_state, "intraday", None) is not None:
        noticias = attach_market_reaction_to_news(noticias, btc_market_state.intraday)
    noticias = _revalidate_precandidates_after_download(noticias)
    _prepare_image_diagnostics(noticias)
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
    if btc_market_state is not None and getattr(btc_market_state, "intraday", None) is not None:
        noticias = attach_market_reaction_to_news(noticias, btc_market_state.intraday)
    _prepare_image_diagnostics(noticias)
    noticias = verify_news(noticias)
    funnel["after_verification"] = len(noticias)
    before_dedupe = len(noticias)
    noticias = dedupe_news(noticias)
    discard_counters["duplicate"] += max(0, before_dedupe - len(noticias))
    funnel["after_deduper"] = len(noticias)
    if intraday_flow["candidate_created"] == "yes":
        intraday_flow["dedupe"] = "PASS" if any(_is_intraday_lane_item(item) for item in noticias) else "FAIL"
        if intraday_flow["dedupe"] == "FAIL":
            intraday_flow["final_result"] = "REJECTED"
            intraday_flow["rejection_reason"] = "deduper"
    enricher_time = time.perf_counter() - enricher_start

    noticias = sort_for_publication(noticias)

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
    structural_lane, direct_lanes = split_selector_lanes(noticias)
    selected_by_ai = await run_sync_phase(
        "SELECTOR",
        lambda: select_news_with_ai(structural_lane),
        timeout=OPENAI_TIMEOUT_SECONDS,
        fallback=[],
        counters=network_counters,
        timeout_counter="openai_timeout",
    )
    noticias = []
    _dedupe_extend(noticias, direct_lanes)
    _dedupe_extend(noticias, selected_by_ai)
    noticias = sort_for_publication(noticias)
    noticias = noticias[:MAX_PUBLICATIONS]
    selector_time = time.perf_counter() - selector_start
    funnel["selected"] = len(noticias)
    seen_cache.mark_selected(noticias)
    discard_counters["selector_rejected"] += count_selector_rejections(
        selector_input,
        noticias,
    )

    structural_gate_items = [item for item in noticias if not direct_lane_item(item)]
    normal_pre, pre_gate_results, pre_gate_counters = apply_publication_gate(
        structural_gate_items,
        {"ok": True, "errors": []},
    )
    rumor_pre, rumor_pre_results = apply_rumor_gate(
        noticias,
        {"ok": True, "errors": []},
    )
    intraday_pre, intraday_pre_results, intraday_pre_counters = apply_intraday_publication_gate(
        noticias,
        {"ok": True, "errors": []},
    )
    intraday_results = [result for result in intraday_pre_results]
    if intraday_results:
        decision = (intraday_results[0].item.intelligence_summary or {}).get("INTRADAY_DECISION")
        if decision == "INTRADAY_NOTE":
            intraday_flow["note_gate"] = "PASS" if intraday_pre else "FAIL"
            intraday_flow["alert_gate"] = "NOT_REQUIRED"
        elif decision == "INTRADAY_ALERT":
            intraday_flow["alert_gate"] = "PASS" if intraday_pre else "FAIL"
            intraday_flow["note_gate"] = "NOT_REQUIRED"
        intraday_flow["frequency"] = "PASS" if intraday_pre else "FAIL"
        intraday_flow["final_result"] = "PRE_GATE_PASS" if intraday_pre else "REJECTED"
        intraday_flow["rejection_reason"] = (
            "PASS" if intraday_pre else ",".join(intraday_results[0].reasons)
        )
    daily_pre, daily_pre_results, daily_pre_counters = apply_daily_publication_gate(
        noticias,
        {"ok": True, "errors": []},
    )
    noticias = []
    for lane in [normal_pre, intraday_pre, daily_pre, rumor_pre]:
        _dedupe_extend(noticias, lane)
    noticias = sort_for_publication(noticias)
    noticias = noticias[:MAX_PUBLICATIONS]
    normal_pass_links = {result.item.link for result in pre_gate_results if result.passed}
    pre_gate_results = pre_gate_results + [
        result
        for result in rumor_pre_results
        if result.passed and result.item.link not in normal_pass_links
    ]
    pre_gate_results.extend(intraday_pre_results)
    pre_gate_results.extend(daily_pre_results)
    discard_counters.update(pre_gate_counters)
    discard_counters.update(intraday_pre_counters)
    discard_counters.update(daily_pre_counters)

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

    attach_editorial_interpretations(noticias)
    if any(_is_intraday_lane_item(item) for item in noticias):
        intraday_flow["market_interpreter"] = "PASS"
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
    if any(item.event_type == "BTC_INTRADAY_MOVE" for item in noticias):
        intraday_flow["writer"] = "PASS"

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
    if any(item.event_type == "BTC_INTRADAY_MOVE" for item in noticias):
        intraday_flow["reviewer"] = "PASS" if reviewer_pass else "FAIL"

    structural_gate_items = [item for item in noticias if not direct_lane_item(item)]
    normal_publishable, final_gate_results, final_gate_counters = apply_publication_gate(
        structural_gate_items,
        revision,
    )
    rumor_publishable, rumor_final_results = apply_rumor_gate(
        noticias,
        revision,
    )
    intraday_publishable, intraday_final_results, intraday_final_counters = apply_intraday_publication_gate(
        noticias,
        revision,
    )
    if intraday_final_results:
        decision = (intraday_final_results[0].item.intelligence_summary or {}).get("INTRADAY_DECISION")
        if decision == "INTRADAY_NOTE":
            intraday_flow["note_gate"] = "PASS" if intraday_publishable else "FAIL"
            intraday_flow["alert_gate"] = "NOT_REQUIRED"
        elif decision == "INTRADAY_ALERT":
            intraday_flow["alert_gate"] = "PASS" if intraday_publishable else "FAIL"
            intraday_flow["note_gate"] = "NOT_REQUIRED"
        intraday_flow["frequency"] = "PASS" if intraday_publishable else "FAIL"
        intraday_flow["final_result"] = "GATE_PASS" if intraday_publishable else "REJECTED"
        intraday_flow["rejection_reason"] = (
            "PASS" if intraday_publishable else ",".join(intraday_final_results[0].reasons)
        )
    daily_publishable, daily_final_results, daily_final_counters = apply_daily_publication_gate(
        noticias,
        revision,
    )
    publishable = []
    for lane in [normal_publishable, intraday_publishable, daily_publishable, rumor_publishable]:
        _dedupe_extend(publishable, lane)
    publishable = sort_for_publication(publishable)
    publishable = publishable[:MAX_PUBLICATIONS]
    normal_pass_links = {result.item.link for result in final_gate_results if result.passed}
    final_gate_results = final_gate_results + [
        result
        for result in rumor_final_results
        if result.passed and result.item.link not in normal_pass_links
    ]
    final_gate_results.extend(intraday_final_results)
    final_gate_results.extend(daily_final_results)
    discard_counters.update(final_gate_counters)
    discard_counters.update(intraday_final_counters)
    discard_counters.update(daily_final_counters)

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
    if any(item.event_type == "BTC_INTRADAY_MOVE" for item in noticias):
        intraday_flow["publisher"] = "DRY_RUN" if DRY_RUN else "SHADOW_AUTO" if AUTO_PUBLISH_SHADOW else "LIVE"
        intraday_flow["final_result"] = "WOULD_PUBLISH" if (DRY_RUN or AUTO_PUBLISH_SHADOW) else "PUBLISHED"
        intraday_flow["rejection_reason"] = "PASS"
    mensajes = format_report(informe)
    mensajes = mensajes[:len(noticias)]
    funnel["would_publish"] = len(mensajes)

    if DRY_RUN or AUTO_PUBLISH_SHADOW:
        seen_cache.mark_would_publish(noticias, shadow=AUTO_PUBLISH_SHADOW)
        if any(item.event_type == "BTC_DAILY_RECAP" for item in noticias) and daily_recap_decision:
            seen_cache.remember_daily_recap(
                daily_recap_decision.fingerprint,
                published=False,
                shadow=AUTO_PUBLISH_SHADOW,
            )
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
    if any(item.event_type == "BTC_DAILY_RECAP" for item in noticias) and daily_recap_decision:
        seen_cache.remember_daily_recap(daily_recap_decision.fingerprint, published=True)

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
