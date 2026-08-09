from diagnostics import format_discard_counters


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
    print("DESCARTES")
    print(format_discard_counters(discard_counters))
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
        print("NO MATERIAL BTC MARKET ANOMALY")
        print("========================================\n")
        return

    snapshot = state.snapshot

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
    if state.signals:
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
        print("ON-CHAIN: UNKNOWN")
        if onchain and onchain.errors:
            print(f"On-chain errors: {_list_text(onchain.errors)}")
    else:
        print(f"Exchange inflows:  {_fmt(onchain.btc_exchange_inflow)}")
        print(f"Exchange outflows: {_fmt(onchain.btc_exchange_outflow)}")
        print(f"Netflow:           {_fmt(onchain.btc_exchange_netflow)}")
        print(f"Reserves:          {_fmt(onchain.btc_exchange_reserves)}")
        print(f"Whale activity:    {onchain.btc_whale_activity}")

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


def print_dry_run_report(news, messages):
    print("\n========================================")
    print("RADAR — DRY RUN")
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
        print()
        print("Por qué ha sobrevivido:")
        print(_why_survived(item))
        print()
        print("Señales detectadas:")
        print(_list_text(item.market_signals))
        print()
        print("TEXTO FINAL DE TELEGRAM:")
        print(message)
        print("========================================")

    print()
