from diagnostics import format_discard_counters
from quiet_market import format_quiet_market_diagnostic
from runtime_guards import format_network_counters
from seen_cache import format_intake_stats, format_source_performance


def _list_text(values):
    if not values:
        return "None"

    return ", ".join(str(value) for value in values)


def _why_survived(item):
    reasons = [
        f"market impact {item.market_impact}/100",
        f"materiality {item.materiality}",
        f"verification {item.verification_status}",
        f"source {item.source_type} reliability {item.source_reliability}",
    ]

    if item.mechanism:
        reasons.append(f"mechanism: {item.mechanism}")

    return "; ".join(reasons)


def print_funnel_summary(funnel, discard_counters):
    print("\n========================================")
    print("RADAR — FUNNEL")
    print("========================================")
    print(f"Señales RSS:                 {funnel.get('rss', 0)}")
    print(f"Señales Telegram:            {funnel.get('telegram', 0)}")
    print(f"Señales Reddit:              {funnel.get('reddit', 0)}")
    print(f"Señales Truth Social:        {funnel.get('truth_social', 0)}")
    print(f"Market state synthetic:      {funnel.get('market_state_signals', 0)}")
    print(f"Tras filtro:                 {funnel.get('after_filter', 0)}")
    print(f"Tras market scorer:          {funnel.get('after_market_scorer', 0)}")
    print(f"Precandidatas:               {funnel.get('precandidates', 0)}")
    print(f"Tras enrichment:             {funnel.get('after_enrichment', 0)}")
    print(f"Tras verification:           {funnel.get('after_verification', 0)}")
    print(f"Eventos únicos tras deduper: {funnel.get('after_deduper', 0)}")
    print(f"Seleccionadas:               {funnel.get('selected', 0)}")
    print(f"Reviewer PASS:               {funnel.get('reviewer_pass', False)}")
    print(f"Habrían sido publicadas:     {funnel.get('would_publish', 0)}")
    print()
    intraday_pipeline = funnel.get("intraday_pipeline")
    if intraday_pipeline:
        print("INTRADAY PUBLICATION FLOW")
        for key in [
            "state_decision",
            "candidate_created",
            "market_interpreter",
            "writer",
            "reviewer",
            "note_gate",
            "alert_gate",
            "dedupe",
            "frequency",
            "publisher",
            "final_result",
            "rejection_reason",
        ]:
            print(f"{key}: {intraday_pipeline.get(key, 'UNKNOWN')}")
        print()
    daily_recap = funnel.get("daily_recap")
    if daily_recap:
        note = daily_recap.note
        context = getattr(daily_recap, "context", None)
        summary = note.intelligence_summary if note and note.intelligence_summary else {}
        print("DAILY MARKET RECAP")
        print(f"Eligible: {daily_recap.eligible}")
        print(f"24h move: {summary.get('CURRENT_24H_MOVE', getattr(context, 'change_24h', 'UNKNOWN'))}")
        print(f"Max 15m move 24h: {summary.get('MAX_MOVE_15M_24H', getattr(context, 'max_abs_move_15m_24h', 'UNKNOWN'))}")
        print(f"Max 1h move 24h: {summary.get('MAX_MOVE_1H_24H', getattr(context, 'max_abs_move_1h_24h', 'UNKNOWN'))}")
        print(f"Max 4h move 24h: {summary.get('MAX_MOVE_4H_24H', getattr(context, 'max_abs_move_4h_24h', 'UNKNOWN'))}")
        print(f"Peak volume: {summary.get('MAX_VOLUME_RATIO_24H', getattr(context, 'peak_volume_ratio_24h', 'UNKNOWN'))}")
        print(f"Peak volatility: {summary.get('MAX_VOLATILITY_RATIO_24H', getattr(context, 'peak_volatility_ratio_24h', 'UNKNOWN'))}")
        print(f"OI context: {summary.get('OI_DAILY_CONTEXT', getattr(context, 'oi_daily_context', 'UNKNOWN'))}")
        print(f"OI 1h: {summary.get('OI_CONTEXT_1H', getattr(context, 'oi_change_1h', 'UNKNOWN'))}")
        print(f"OI 4h: {summary.get('OI_CONTEXT_4H', getattr(context, 'oi_change_4h', 'UNKNOWN'))}")
        print(f"Funding: {summary.get('FUNDING', getattr(context, 'funding', 'UNKNOWN'))}")
        print(f"Structure: {summary.get('STRUCTURE', getattr(context, 'data_status', 'UNKNOWN'))}")
        print(f"Liquidity: {summary.get('LIQUIDITY_CONTEXT', getattr(context, 'liquidity_context', 'UNKNOWN'))}")
        print(f"Data status: {summary.get('DATA_STATUS', getattr(context, 'data_status', 'UNKNOWN'))}")
        print("Recent relevant events:")
        if daily_recap.recent_events:
            for event in daily_recap.recent_events[:5]:
                relevance = event.get("btc_context_relevance", "UNKNOWN")
                print(f"- {event.get('title')} ({event.get('source')}) relevance={relevance}")
        else:
            print("None")
        print(f"Score: {daily_recap.score}")
        print(f"Decision: {daily_recap.decision}")
        print(f"Duplicate: {daily_recap.duplicate}")
        print(f"Image eligible: {getattr(note, 'image_eligible', False) if note else False}")
        print(f"Published: {'yes' if daily_recap.published else 'no'}")
        print(f"Reason: {daily_recap.reason}")
        if context:
            trace = context.trace or {}
            print()
            print("DAILY CONTEXT TRACE")
            for key in [
                "market_snapshot_24h",
                "intraday_24h",
                "resolved_24h",
                "rolling_1h_peak",
                "rolling_4h_peak",
                "rolling_volume_peak",
                "oi_raw",
                "oi_context",
                "structure_raw",
                "structure_resolved",
                "events_before_filter",
                "events_after_filter",
                "daily_score",
                "decision",
            ]:
                print(f"{key}: {trace.get(key, 'UNKNOWN')}")
        print()
    print("INTAKE / NOVELTY")
    print(format_intake_stats(funnel.get("intake_stats")))
    print()
    print("DESCARTES")
    print(format_discard_counters(discard_counters))
    print()
    print("NETWORK / TIMEOUTS")
    print(format_network_counters(funnel.get("network_counters")))
    print()
    print("REDDIT")
    reddit_status = funnel.get("reddit_status")
    if reddit_status is None:
        print("REDDIT: UNKNOWN")
    else:
        print(f"Posts read:     {reddit_status.posts_read}")
        print(f"Posts accepted: {reddit_status.posts_accepted}")
        print(f"Top narratives: {_list_text(reddit_status.top_narratives)}")
        print(f"Attention:      {reddit_status.attention}")
        print(f"Sentiment:      {reddit_status.sentiment}")
        print(f"Errors/status:  {reddit_status.status}")
        if reddit_status.errors:
            print(f"Errors detail:  {_list_text(reddit_status.errors)}")
    print()
    print("TRUTH SOCIAL")
    truth_status = funnel.get("truth_social_status")
    if truth_status is None:
        print("TRUTH SOCIAL: UNKNOWN")
    elif truth_status.status == "UNAVAILABLE_FREE_SOURCE":
        print("TRUTH SOCIAL: UNAVAILABLE_FREE_SOURCE")
        if truth_status.errors:
            print(f"Errors: {_list_text(truth_status.errors)}")
    else:
        print(f"Status:                      {truth_status.status}")
        print(f"Posts read:                  {truth_status.posts_read}")
        print(f"Market-sensitive posts:      {truth_status.market_sensitive_posts}")
        print(f"Latest relevant declaration: {truth_status.latest_relevant_declaration or 'None'}")
        if truth_status.errors:
            print(f"Errors:                      {_list_text(truth_status.errors)}")
    print()
    quiet_market = funnel.get("quiet_market")
    if quiet_market is not None:
        print(format_quiet_market_diagnostic(quiet_market))
    print()
    print("SOURCE PERFORMANCE")
    print(format_source_performance(funnel.get("source_performance")))
    print("========================================\n")


def _fmt(value, suffix=""):
    if value is None:
        return "UNKNOWN"

    if isinstance(value, float):
        return f"{value:,.4f}{suffix}"

    return f"{value}{suffix}"


def print_btc_market_state(state):
    print("\n========================================")
    print("BTC MARKET STATE")
    print("========================================")

    if state is None:
        print("BTC MARKET STATE: INSUFFICIENT DATA")
        print("========================================\n")
        print_btc_intraday_state(None)
        return

    snapshot = state.snapshot

    market_status = getattr(state, "status", "UNKNOWN")
    print(f"Status:         {market_status}")
    if market_status == "INSUFFICIENT":
        print("BTC MARKET STATE: INSUFFICIENT DATA")
    elif market_status == "DEGRADED":
        print("BTC MARKET STATE: DEGRADED")
    print(f"Price:          {_fmt(snapshot.price)}")
    print(f"24h:            {_fmt(snapshot.price_change_24h, '%')}")
    print(f"Volume:         {_fmt(snapshot.volume_24h)}")
    print(f"Volatility:     {_fmt(snapshot.volatility, '%')}")
    print(f"Open interest:  {_fmt(snapshot.open_interest)}")
    print(f"Funding:        {_fmt(snapshot.funding_rate)}")
    print(
        "Liquidations:   "
        f"long={_fmt(snapshot.liquidations_long)} "
        f"short={_fmt(snapshot.liquidations_short)}"
    )
    print(f"Liquidations status: {snapshot.liquidations_status}")

    print()
    print("ETF flows:")
    etf = state.etf_flows
    if etf is None or etf.btc_etf_net_flow is None:
        status = getattr(etf, "status", "UNKNOWN") if etf else "UNKNOWN"
        if status == "NOT_CONFIGURED":
            print("ETF FLOWS: NOT_CONFIGURED")
        elif status == "API_ERROR":
            print("ETF FLOWS: API_ERROR")
        else:
            print("ETF FLOWS: UNKNOWN")
        if etf and etf.errors:
            print(f"ETF errors:      {_list_text(etf.errors)}")
    else:
        print(f"Daily net:      {_fmt(etf.btc_etf_net_flow)}")
        print(f"3d avg:         {_fmt(etf.btc_etf_flow_3d_avg)}")
        print(f"7d avg:         {_fmt(etf.btc_etf_flow_7d_avg)}")
        print(f"Streak:         {_fmt(etf.btc_etf_flow_streak)}")
        print(f"Regime:         {etf.btc_etf_flow_regime}")

    if snapshot.errors:
        print(f"Data errors:    {_list_text(snapshot.errors)}")

    print()
    print("Signals:")
    if market_status == "INSUFFICIENT":
        print("INSUFFICIENT DATA")
    elif state.signals:
        for signal in state.signals:
            print(
                f"- {signal.name} "
                f"strength={signal.strength} "
                f"certainty={signal.certainty} "
                f"evidence={signal.evidence}"
            )
    else:
        print("NO MATERIAL BTC MARKET ANOMALY")

    print()
    print("ON-CHAIN")
    onchain = state.onchain
    if onchain is None or (
        onchain.btc_exchange_inflow is None
        and onchain.btc_exchange_outflow is None
        and onchain.btc_exchange_netflow is None
        and onchain.btc_exchange_reserves is None
        and onchain.btc_large_transfer_volume is None
    ):
        status = getattr(onchain, "status", "UNKNOWN") if onchain else "UNKNOWN"
        if status == "NOT_CONFIGURED":
            print("ON-CHAIN: NOT_CONFIGURED")
        elif status == "API_ERROR":
            print("ON-CHAIN: API_ERROR")
        else:
            print("ON-CHAIN: UNKNOWN")
        if onchain and onchain.errors:
            print(f"On-chain errors: {_list_text(onchain.errors)}")
    else:
        print(f"Exchange inflows:  {_fmt(onchain.btc_exchange_inflow)}")
        print(f"Exchange outflows: {_fmt(onchain.btc_exchange_outflow)}")
        print(f"Netflow:           {_fmt(onchain.btc_exchange_netflow)}")
        print(f"Reserves:          {_fmt(onchain.btc_exchange_reserves)}")
        print(f"Whale activity:    {onchain.btc_whale_activity}")

    if onchain and getattr(onchain, "coin_metrics_status", "UNKNOWN") != "UNKNOWN":
        print(f"Coin Metrics:      {onchain.coin_metrics_status}")
        print(f"BTC tx count:      {_fmt(onchain.btc_tx_count)}")
        print(f"Active addresses:  {_fmt(onchain.btc_active_addresses)}")
        print(f"Hash rate:         {_fmt(onchain.btc_hash_rate)}")

    print(f"On-chain regime: {state.onchain_regime}")

    print()
    print("SENTIMENT / POSITIONING")
    sentiment = state.sentiment
    if sentiment is None or (
        sentiment.retail_sentiment == "UNKNOWN"
        and sentiment.retail_attention == "UNKNOWN"
        and sentiment.market_sentiment == "UNKNOWN"
        and sentiment.crowding_state == "UNKNOWN"
        and sentiment.positioning_bias == "UNKNOWN"
        and sentiment.institutional_flow_proxy == "UNKNOWN"
        and sentiment.narrative_state == "UNKNOWN"
        and sentiment.sentiment_divergence == "UNKNOWN"
    ):
        print("SENTIMENT: UNKNOWN")
        if sentiment and sentiment.errors:
            print(f"Sentiment errors: {_list_text(sentiment.errors)}")
    else:
        print(f"Retail:              {sentiment.retail_sentiment}")
        print(f"Market:              {sentiment.market_sentiment}")
        print(f"Positioning:         {sentiment.positioning_bias}")
        print(f"Crowding:            {sentiment.crowding_state}")
        print(f"Institutional proxy: {sentiment.institutional_flow_proxy}")
        print(f"Narrative:           {sentiment.narrative_state}")
        print(f"Divergence:          {sentiment.sentiment_divergence}")

    sentiment_signal_names = {
        "RETAIL_BULLISH",
        "RETAIL_BEARISH",
        "RETAIL_EUPHORIA",
        "RETAIL_PANIC",
        "RETAIL_ATTENTION_SPIKE",
        "REDDIT_ATTENTION_LOW",
        "REDDIT_ATTENTION_ELEVATED",
        "REDDIT_ATTENTION_EXTREME",
        "CROWDED_LONG",
        "CROWDED_SHORT",
        "POSITIVE_FLOW_NEGATIVE_RETAIL_DIVERGENCE",
        "NEGATIVE_FLOW_POSITIVE_RETAIL_DIVERGENCE",
        "NARRATIVE_OVERHEAT",
        "COMPLACENCY",
        "CAPITULATION",
        "CROWDING_CONFLUENCE",
        "CROWDING_RISK_CONFLUENCE",
        "SENTIMENT_FLOW_DIVERGENCE_CONFLUENCE",
        "SENTIMENT_DISTRIBUTION_RISK_CONFLUENCE",
    }
    sentiment_signals = [
        signal
        for signal in state.signals
        if signal.name in sentiment_signal_names
    ]
    print("Sentiment signals:")
    if sentiment_signals:
        for signal in sentiment_signals:
            print(
                f"- {signal.name} "
                f"strength={signal.strength} "
                f"certainty={signal.certainty} "
                f"evidence={signal.evidence}"
            )
    else:
        print("None")

    print()
    print("LIQUIDITY / STRUCTURE")
    liquidity = state.liquidity_structure
    if liquidity is None or (
        liquidity.best_bid is None
        and liquidity.best_ask is None
        and liquidity.book_imbalance is None
        and liquidity.structure == "UNKNOWN"
        and liquidity.breakout_state == "UNKNOWN"
        and liquidity.liquidity_sweep == "UNKNOWN"
        and not liquidity.smc_signals
    ):
        print("LIQUIDITY / STRUCTURE: UNKNOWN")
        if liquidity and liquidity.errors:
            print(f"Liquidity errors: {_list_text(liquidity.errors)}")
    else:
        bid_cluster = liquidity.largest_bid_cluster
        ask_cluster = liquidity.largest_ask_cluster
        print(f"Spread:          {_fmt(liquidity.spread)}")
        print(f"Book imbalance:  {_fmt(liquidity.book_imbalance)}")
        print(f"Bid liquidity:   {_fmt(liquidity.bid_depth_1pct)} within 1%")
        print(f"Ask liquidity:   {_fmt(liquidity.ask_depth_1pct)} within 1%")
        print(
            "Liquidity above: "
            f"{_fmt(ask_cluster.price if ask_cluster else None)} "
            f"notional={_fmt(ask_cluster.notional if ask_cluster else None)}"
        )
        print(
            "Liquidity below: "
            f"{_fmt(bid_cluster.price if bid_cluster else None)} "
            f"notional={_fmt(bid_cluster.notional if bid_cluster else None)}"
        )
        print(f"Structure:       {liquidity.structure}")
        print(f"Breakout state:  {liquidity.breakout_state}")
        print(f"Liquidity sweep: {liquidity.liquidity_sweep}")
        print(f"SMC signals:     {_list_text(liquidity.smc_signals)}")
        print(f"Interpretation:  {liquidity.interpretation}")

    liquidity_signal_names = {
        "BID_LIQUIDITY_EXTREME",
        "ASK_LIQUIDITY_EXTREME",
        "ORDERBOOK_IMBALANCE_BID",
        "ORDERBOOK_IMBALANCE_ASK",
        "LIQUIDITY_VACUUM_ABOVE",
        "LIQUIDITY_VACUUM_BELOW",
        "BULLISH_BREAK_OF_STRUCTURE",
        "BEARISH_BREAK_OF_STRUCTURE",
        "CHANGE_OF_CHARACTER_BULLISH",
        "CHANGE_OF_CHARACTER_BEARISH",
        "LIQUIDITY_SWEEP_ABOVE",
        "LIQUIDITY_SWEEP_BELOW",
        "FAILED_BREAKOUT",
        "DISPLACEMENT_UP",
        "DISPLACEMENT_DOWN",
        "FVG_ABOVE",
        "FVG_BELOW",
        "STRUCTURE_CROWDING_RISK_CONFLUENCE",
        "CONSTRUCTIVE_STRUCTURE_FLOW_CONFLUENCE",
    }
    liquidity_signals = [
        signal
        for signal in state.signals
        if signal.name in liquidity_signal_names
    ]
    print("Liquidity/structure signals:")
    if liquidity_signals:
        for signal in liquidity_signals:
            print(
                f"- {signal.name} "
                f"strength={signal.strength} "
                f"certainty={signal.certainty} "
                f"evidence={signal.evidence}"
            )
    else:
        print("None")

    print()
    print(f"Confluence:     {state.confluence}")
    print(f"Market regime:  {state.market_regime}")
    print("========================================\n")

    print_btc_intraday_state(getattr(state, "intraday", None))


def print_btc_intraday_state(intraday):
    print("\n========================================")
    print("BTC INTRADAY STATE")
    print("========================================")

    if intraday is None:
        print("Status: INSUFFICIENT")
        print("Decision: INSUFFICIENT_DATA")
        print("========================================\n")
        return

    snapshot = intraday.snapshot
    liquidity = snapshot.liquidity

    status = getattr(intraday, "status", getattr(snapshot, "status", "UNKNOWN"))
    available = getattr(intraday, "data_available", None) or getattr(snapshot, "data_available", {}) or {}
    print(f"Status: {status}")
    print("Data available:")
    for key in ["price", "klines", "volume", "open_interest", "funding", "order_book"]:
        print(f"{key}={'yes' if available.get(key) else 'no'}")
    if snapshot.errors:
        print(f"Errors: {_list_text(snapshot.errors)}")
    print()
    print("PRICE")
    print(f"5m:   {_fmt(snapshot.price_change_5m, '%')}")
    print(f"15m:  {_fmt(snapshot.price_change_15m, '%')}")
    print(f"30m:  {_fmt(snapshot.price_change_30m, '%')}")
    print(f"1h:   {_fmt(snapshot.price_change_1h, '%')}")
    print(f"4h:   {_fmt(snapshot.price_change_4h, '%')}")
    print(f"24h:  {_fmt(snapshot.price_change_24h, '%')}")
    print()
    print("VOLUME")
    print(f"15m:   {_fmt(snapshot.volume_15m)} ratio={_fmt(snapshot.volume_ratio_15m)}")
    print(f"1h:    {_fmt(snapshot.volume_1h)} ratio={_fmt(snapshot.volume_ratio_1h)}")
    print(f"4h:    {_fmt(snapshot.volume_4h)} ratio={_fmt(snapshot.volume_ratio_4h)}")
    print()
    print("VOLATILITY")
    print(f"15m: {_fmt(snapshot.realized_volatility_15m, '%')} ratio={_fmt(snapshot.volatility_ratio_15m)}")
    print(f"1h:  {_fmt(snapshot.realized_volatility_1h, '%')} ratio={_fmt(snapshot.volatility_ratio_1h)}")
    print(f"4h:  {_fmt(snapshot.realized_volatility_4h, '%')} ratio={_fmt(snapshot.volatility_ratio_4h)}")
    print()
    print("DERIVATIVES")
    print(f"OI 15m: {_fmt(snapshot.oi_change_15m, '%')}")
    print(f"OI 1h:  {_fmt(snapshot.oi_change_1h, '%')}")
    print(f"OI 4h:  {_fmt(snapshot.oi_change_4h, '%')}")
    print(f"Funding: {_fmt(snapshot.funding_rate)}")
    print(f"Funding regime: {snapshot.funding_regime}")
    print()
    print("STRUCTURE")
    print(f"15m: {snapshot.structure_15m}")
    print(f"1h:  {snapshot.structure_1h}")
    print(f"4h:  {snapshot.structure_4h}")
    print(f"1d:  {snapshot.structure_1d}")
    print()
    print("LIQUIDITY")
    print(f"Visible above: {_fmt(liquidity.nearest_visible_above)} ({liquidity.visible_above})")
    print(f"Visible below: {_fmt(liquidity.nearest_visible_below)} ({liquidity.visible_below})")
    print(f"Inferred above: {_fmt(liquidity.equal_highs)} ({liquidity.inferred_above})")
    print(f"Inferred below: {_fmt(liquidity.equal_lows)} ({liquidity.inferred_below})")
    print(f"Previous day high: {_fmt(liquidity.previous_day_high)}")
    print(f"Previous day low:  {_fmt(liquidity.previous_day_low)}")
    print(f"Previous week high: {_fmt(liquidity.previous_week_high)}")
    print(f"Previous week low:  {_fmt(liquidity.previous_week_low)}")
    print(f"Liquidity imbalance: {liquidity.liquidity_imbalance}")
    print()
    print("SMC / PRICE ACTION")
    if intraday.signals:
        for signal in intraday.signals:
            print(
                f"- {signal.name} timeframe={signal.timeframe} "
                f"strength={signal.strength} certainty={signal.certainty} "
                f"source={signal.source} evidence={signal.evidence}"
            )
    else:
        print("None")
    print()
    print("CATALYST")
    print(f"Status: {intraday.catalyst_status}")
    print(f"Source: {intraday.catalyst_source or 'None'}")
    print(f"Confidence: {intraday.catalyst_confidence}")
    print()
    print("SCORING")
    print(f"Move abnormality:       {intraday.move_abnormality_score}")
    print(f"Liquidity importance:   {intraday.liquidity_importance_score}")
    print(f"SMC confluence:         {intraday.smc_confluence_score}")
    print(f"Intraday news relevance:{intraday.intraday_news_relevance}")
    print(f"Intraday confluence:    {intraday.intraday_confluence_score}")
    print(f"Materiality:            {intraday.intraday_materiality}")
    print(f"Decision:               {intraday.decision}")
    print(f"Time horizon:           {intraday.time_horizon}")
    if snapshot.errors:
        print(f"Errors:                 {_list_text(snapshot.errors)}")
    print("========================================\n")


def print_final_decision_gate(results):
    print("\n========================================")
    print("FINAL DECISION GATE")
    print("========================================")

    if not results:
        print("No selected stories reached final gate.")
        print("========================================\n")
        return

    for result in results:
        item = result.item
        print(f"{item.final_decision}: {item.title}")
        print(f"Market impact:      {item.market_impact}")
        print(f"Materiality:        {item.materiality}")
        print(f"Verification:       {item.verification_status}")
        print(f"Confidence:         {item.confidence}")
        print(f"Mechanism strength: {getattr(result, 'mechanism_strength', getattr(item, 'mechanism_of_impact', 'UNKNOWN'))}")
        print(f"Editorial quality:  {getattr(result, 'editorial_quality', getattr(item, 'editorial_quality', 0))}")
        if getattr(item, "declaration_status", "UNKNOWN") != "UNKNOWN":
            print(f"Declaration status: {item.declaration_status}")
        if getattr(item, "rumor_score", 0):
            print(f"Rumor score:        {item.rumor_score}")
        if result.reasons:
            print(f"FINAL_REJECT:       {_list_text(result.reasons)}")
        else:
            print("FINAL_REJECT:       None")
        print("----------------------------------------")

    print("========================================\n")


def report_mode_title(dry_run=True, shadow=False):
    if dry_run:
        return "RADAR — DRY RUN"
    if shadow:
        return "RADAR — SHADOW AUTO"
    return "RADAR — LIVE"


def print_dry_run_report(news, messages, dry_run=True, shadow=False):
    print("\n========================================")
    print(report_mode_title(dry_run=dry_run, shadow=shadow))
    print("========================================")

    if not news:
        print("RADAR: NO MATERIAL EVENTS")
        print("========================================\n")
        return

    for item, message in zip(news, messages):
        print("Título:")
        print(item.title)
        print()
        print("Fuente(s):")
        sources = [item.source] + list(item.related_sources)
        print(_list_text(sources))
        print()
        print(f"Event type: {item.event_type}")
        print(f"Affected assets: {_list_text(item.affected_assets)}")
        print(f"Market impact score: {item.market_impact}")
        print(f"Materiality: {item.materiality}")
        print(f"Verification: {item.verification_status}")
        print(f"Confidence: {item.confidence}")
        print(f"Discountedness: {item.discountedness}")
        print(f"Image eligible: {getattr(item, 'image_eligible', False)}")
        if getattr(item, "image_brief", ""):
            print("Generated image brief:")
            print(item.image_brief)
        print()
        print("Por qué ha sobrevivido:")
        print(_why_survived(item))
        print()
        print("Señales detectadas:")
        print(_list_text(item.market_signals))
        print()
        interpretation = (item.intelligence_summary or {}).get("EDITORIAL_INTERPRETATION", {})
        if interpretation:
            print("EDITORIAL INTERPRETATION")
            print(f"Story angle: {interpretation.get('story_angle', 'UNKNOWN')}")
            print(f"Primary hypothesis: {interpretation.get('primary_hypothesis', 'UNKNOWN')}")
            print(f"Alternative hypothesis: {interpretation.get('alternative_hypothesis', 'UNKNOWN')}")
            print(f"Evidence for: {_list_text(interpretation.get('evidence_for', []))}")
            print(f"Evidence against: {_list_text(interpretation.get('evidence_against', []))}")
            print(f"Catalyst confidence: {interpretation.get('catalyst_confidence', 'UNKNOWN')}")
            print(f"Interesting data selected: {_list_text(interpretation.get('interesting_data_selected', []))}")
            print(f"Data omitted from publication: {_list_text(interpretation.get('data_omitted_from_publication', []))}")
            print(f"What confirms: {interpretation.get('what_confirms', 'UNKNOWN')}")
            print(f"What invalidates: {interpretation.get('what_invalidates', 'UNKNOWN')}")
            print(f"News summary: {interpretation.get('news_summary', 'UNKNOWN')}")
            print(f"Market interpretation: {interpretation.get('market_interpretation', 'UNKNOWN')}")
            print(f"Analysis value ratio: {interpretation.get('analysis_value_ratio', 'UNKNOWN')}")
            print(f"Editorial duplicate: {interpretation.get('editorial_duplicate', False)}")
            print()
        print("TEXTO FINAL DE TELEGRAM:")
        print(message)
        print("========================================")

    print()
