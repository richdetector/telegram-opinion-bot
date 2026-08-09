from dataclasses import dataclass, field

from market_data import (
    BtcEtfFlowSnapshot,
    BtcMarketSnapshot,
    BtcOnchainSnapshot,
    fetch_btc_etf_flow_snapshot,
    fetch_btc_market_snapshot,
    fetch_btc_onchain_snapshot,
)
from liquidity_structure_engine import (
    BtcLiquidityStructureSnapshot,
    analyze_liquidity_structure,
    fetch_btc_liquidity_structure_snapshot,
)
from models import NewsItem
from sentiment_engine import (
    BtcSentimentSnapshot,
    analyze_sentiment_positioning,
    fetch_btc_sentiment_snapshot,
)


@dataclass
class MarketSignal:
    name: str
    strength: int
    certainty: str
    evidence: str
    timestamp: str = ""
    source: str = ""


@dataclass
class BtcMarketState:
    snapshot: BtcMarketSnapshot
    etf_flows: BtcEtfFlowSnapshot | None = None
    onchain: BtcOnchainSnapshot | None = None
    sentiment: BtcSentimentSnapshot | None = None
    liquidity_structure: BtcLiquidityStructureSnapshot | None = None
    signals: list[MarketSignal] = field(default_factory=list)
    confluence: str = "LOW"
    confluence_score: int = 0
    market_regime: str = "UNKNOWN"
    onchain_regime: str = "UNKNOWN"
    summary: str = "NO MATERIAL BTC MARKET ANOMALY"


def _add_signal(signals, name, strength, certainty, evidence, timestamp="", source=""):
    signals.append(
        MarketSignal(
            name=name,
            strength=max(0, min(100, int(strength))),
            certainty=certainty,
            evidence=evidence,
            timestamp=timestamp,
            source=source,
        )
    )


def analyze_btc_market_snapshot(snapshot):
    return analyze_btc_market_state(snapshot)


def _analyze_etf_flow_signals(etf_flows):
    if etf_flows is None or etf_flows.btc_etf_net_flow is None:
        return []

    signals = []
    flow = etf_flows.btc_etf_net_flow
    zscore = etf_flows.btc_etf_flow_zscore
    streak = etf_flows.btc_etf_flow_streak or 0

    abs_zscore = abs(zscore) if zscore is not None else 0
    strong_relative = abs_zscore >= 2
    extreme_relative = abs_zscore >= 3

    if flow > 0 and strong_relative:
        _add_signal(
            signals,
            "ETF_INFLOW_EXTREME" if extreme_relative else "ETF_INFLOW_STRONG",
            min(100, abs_zscore * 28),
            "CALCULATED",
            f"BTC ETF net inflow {flow:,.0f} USD; z-score {zscore:.2f}",
        )
    elif flow < 0 and strong_relative:
        _add_signal(
            signals,
            "ETF_OUTFLOW_EXTREME" if extreme_relative else "ETF_OUTFLOW_STRONG",
            min(100, abs_zscore * 28),
            "CALCULATED",
            f"BTC ETF net outflow {abs(flow):,.0f} USD; z-score {zscore:.2f}",
        )

    if streak >= 5:
        _add_signal(
            signals,
            "ETF_POSITIVE_REGIME",
            min(100, streak * 14),
            "INFERRED",
            f"{streak} consecutive positive BTC ETF flow sessions.",
        )
    elif streak <= -5:
        _add_signal(
            signals,
            "ETF_NEGATIVE_REGIME",
            min(100, abs(streak) * 14),
            "INFERRED",
            f"{abs(streak)} consecutive negative BTC ETF flow sessions.",
        )

    avg_3d = etf_flows.btc_etf_flow_3d_avg
    avg_7d = etf_flows.btc_etf_flow_7d_avg
    if avg_3d is not None and avg_7d not in {None, 0}:
        acceleration = avg_3d - avg_7d
        if acceleration > abs(avg_7d) * 0.75 and avg_3d > 0:
            _add_signal(
                signals,
                "ETF_FLOW_ACCELERATION",
                min(100, abs(acceleration) / max(abs(avg_7d), 1) * 40),
                "CALCULATED",
                f"3d average {avg_3d:,.0f} USD vs 7d average {avg_7d:,.0f} USD.",
            )
        elif acceleration < -abs(avg_7d) * 0.75:
            _add_signal(
                signals,
                "ETF_FLOW_DECELERATION",
                min(100, abs(acceleration) / max(abs(avg_7d), 1) * 40),
                "CALCULATED",
                f"3d average {avg_3d:,.0f} USD vs 7d average {avg_7d:,.0f} USD.",
            )

    if len(signals) >= 2 and streak in {1, -1} and avg_7d is not None:
        if (flow > 0 > avg_7d) or (flow < 0 < avg_7d):
            _add_signal(
                signals,
                "ETF_FLOW_REVERSAL",
                65,
                "INFERRED",
                f"Latest flow {flow:,.0f} USD reversed the recent 7d average {avg_7d:,.0f} USD.",
            )

    return signals


def _analyze_onchain_signals(onchain):
    if onchain is None:
        return []

    signals = []

    inflow_z = onchain.btc_exchange_inflow_zscore
    outflow_z = onchain.btc_exchange_outflow_zscore
    netflow_z = onchain.btc_exchange_netflow_zscore
    reserve_1d = onchain.btc_exchange_reserve_change_1d
    reserve_7d = onchain.btc_exchange_reserve_change_7d
    miner_z = onchain.btc_miner_to_exchange_zscore

    if inflow_z is not None and inflow_z >= 2:
        _add_signal(
            signals,
            "EXCHANGE_INFLOW_EXTREME" if inflow_z >= 3 else "EXCHANGE_INFLOW_ELEVATED",
            min(100, inflow_z * 28),
            "CALCULATED",
            f"Exchange inflow z-score vs recent baseline: {inflow_z:.2f}",
        )

    if outflow_z is not None and outflow_z >= 2:
        _add_signal(
            signals,
            "EXCHANGE_OUTFLOW_EXTREME" if outflow_z >= 3 else "EXCHANGE_OUTFLOW_ELEVATED",
            min(100, outflow_z * 28),
            "CALCULATED",
            f"Exchange outflow z-score vs recent baseline: {outflow_z:.2f}",
        )

    if netflow_z is not None:
        if netflow_z >= 2.5:
            _add_signal(
                signals,
                "NETFLOW_POSITIVE_EXTREME",
                min(100, netflow_z * 28),
                "CALCULATED",
                f"Exchange netflow z-score: {netflow_z:.2f}",
            )
        elif netflow_z <= -2.5:
            _add_signal(
                signals,
                "NETFLOW_NEGATIVE_EXTREME",
                min(100, abs(netflow_z) * 28),
                "CALCULATED",
                f"Exchange netflow z-score: {netflow_z:.2f}",
            )

    if reserve_1d is not None and reserve_7d is not None:
        if reserve_1d > 0.5 and reserve_7d > 1:
            _add_signal(
                signals,
                "EXCHANGE_RESERVES_RISING",
                min(100, (reserve_1d + reserve_7d) * 20),
                "CALCULATED",
                f"Exchange reserves change: 1d {reserve_1d:.2f}%, 7d {reserve_7d:.2f}%",
            )
        elif reserve_1d < -0.5 and reserve_7d < -1:
            _add_signal(
                signals,
                "EXCHANGE_RESERVES_FALLING",
                min(100, abs(reserve_1d + reserve_7d) * 20),
                "CALCULATED",
                f"Exchange reserves change: 1d {reserve_1d:.2f}%, 7d {reserve_7d:.2f}%",
            )

    if onchain.btc_large_transfer_count is not None and onchain.btc_large_transfer_count >= 3:
        _add_signal(
            signals,
            "WHALE_ACTIVITY_SPIKE",
            min(100, onchain.btc_large_transfer_count * 18),
            "OBSERVED",
            f"{onchain.btc_large_transfer_count} large BTC transfers observed.",
        )

    if miner_z is not None and miner_z >= 2.5:
        _add_signal(
            signals,
            "MINER_TO_EXCHANGE_SPIKE",
            min(100, miner_z * 28),
            "CALCULATED",
            f"Miner-to-exchange flow z-score: {miner_z:.2f}",
        )

    return signals


def _onchain_regime(signal_names):
    if {"EXCHANGE_OUTFLOW_EXTREME", "EXCHANGE_RESERVES_FALLING"} <= signal_names:
        return "ACCUMULATION"
    if {"EXCHANGE_INFLOW_EXTREME", "EXCHANGE_RESERVES_RISING"} <= signal_names:
        return "DISTRIBUTION"
    if signal_names:
        return "NEUTRAL"
    return "UNKNOWN"


def _analyze_sentiment_signals(sentiment, snapshot, etf_flows, onchain):
    if sentiment is None:
        return None, []

    sentiment, sentiment_signals = analyze_sentiment_positioning(
        sentiment,
        snapshot,
        etf_flows,
        onchain,
    )

    signals = []
    for signal in sentiment_signals:
        _add_signal(
            signals,
            signal.name,
            signal.strength,
            signal.certainty,
            signal.evidence,
            signal.timestamp,
            signal.source,
        )

    return sentiment, signals


def _analyze_liquidity_structure_signals(liquidity_structure):
    if liquidity_structure is None:
        return []

    signals = []
    for signal in analyze_liquidity_structure(liquidity_structure):
        _add_signal(
            signals,
            signal.name,
            signal.strength,
            signal.certainty,
            signal.evidence,
            signal.timestamp,
            signal.source,
        )

    return signals


def analyze_btc_market_state(snapshot, etf_flows=None, onchain=None, sentiment=None, liquidity_structure=None):
    signals = []

    if snapshot.open_interest_change is not None:
        if snapshot.open_interest_change >= 8:
            _add_signal(
                signals,
                "OI_RISING_FAST",
                min(100, snapshot.open_interest_change * 8),
                "CALCULATED",
                f"Open interest change vs recent baseline: {snapshot.open_interest_change:.2f}%",
            )
        elif snapshot.open_interest_change <= -8:
            _add_signal(
                signals,
                "OI_FALLING_FAST",
                min(100, abs(snapshot.open_interest_change) * 8),
                "CALCULATED",
                f"Open interest change vs recent baseline: {snapshot.open_interest_change:.2f}%",
            )

    if snapshot.funding_rate is not None:
        if snapshot.funding_extreme == "POSITIVE" or snapshot.funding_rate >= 0.001:
            _add_signal(
                signals,
                "FUNDING_EXTREME_POSITIVE",
                min(100, abs(snapshot.funding_rate) * 100000),
                "OBSERVED",
                f"Funding rate: {snapshot.funding_rate:.6f}",
            )
        elif snapshot.funding_extreme == "NEGATIVE" or snapshot.funding_rate <= -0.001:
            _add_signal(
                signals,
                "FUNDING_EXTREME_NEGATIVE",
                min(100, abs(snapshot.funding_rate) * 100000),
                "OBSERVED",
                f"Funding rate: {snapshot.funding_rate:.6f}",
            )

    if snapshot.volume_zscore is not None and snapshot.volume_zscore >= 2.5:
        _add_signal(
            signals,
            "VOLUME_SPIKE",
            min(100, snapshot.volume_zscore * 25),
            "CALCULATED",
            f"Volume z-score vs recent hourly baseline: {snapshot.volume_zscore:.2f}",
        )

    if snapshot.volatility_zscore is not None and snapshot.volatility_zscore >= 2.5:
        _add_signal(
            signals,
            "VOLATILITY_EXPANSION",
            min(100, snapshot.volatility_zscore * 25),
            "CALCULATED",
            f"Volatility z-score vs recent hourly baseline: {snapshot.volatility_zscore:.2f}",
        )

    long_liq = (
        snapshot.liquidations_long_1h
        if snapshot.liquidations_long_1h is not None
        else snapshot.liquidations_long
        or 0
    )
    short_liq = (
        snapshot.liquidations_short_1h
        if snapshot.liquidations_short_1h is not None
        else snapshot.liquidations_short
        or 0
    )
    if long_liq >= 50_000_000:
        _add_signal(
            signals,
            "LONG_LIQUIDATION_SPIKE",
            min(100, long_liq / 1_000_000),
            "OBSERVED",
            f"Long liquidations notional: {long_liq:,.0f} USDT",
        )
    if short_liq >= 50_000_000:
        _add_signal(
            signals,
            "SHORT_LIQUIDATION_SPIKE",
            min(100, short_liq / 1_000_000),
            "OBSERVED",
            f"Short liquidations notional: {short_liq:,.0f} USDT",
        )

    signal_names = {signal.name for signal in signals}

    etf_signals = _analyze_etf_flow_signals(etf_flows)
    signals.extend(etf_signals)
    onchain_signals = _analyze_onchain_signals(onchain)
    signals.extend(onchain_signals)
    sentiment, sentiment_signals = _analyze_sentiment_signals(
        sentiment,
        snapshot,
        etf_flows,
        onchain,
    )
    signals.extend(sentiment_signals)
    liquidity_structure_signals = _analyze_liquidity_structure_signals(liquidity_structure)
    signals.extend(liquidity_structure_signals)
    signal_names = {signal.name for signal in signals}

    if {"OI_RISING_FAST", "FUNDING_EXTREME_POSITIVE", "VOLUME_SPIKE"} <= signal_names:
        _add_signal(
            signals,
            "LEVERAGE_BUILDUP",
            85,
            "INFERRED",
            "OI, funding and volume are rising together.",
        )

    if (
        {"ETF_INFLOW_STRONG", "VOLUME_SPIKE"} <= signal_names
        or {"ETF_INFLOW_EXTREME", "OI_RISING_FAST"} <= signal_names
        or {"ETF_POSITIVE_REGIME", "OI_RISING_FAST"} <= signal_names
    ):
        _add_signal(
            signals,
            "INSTITUTIONAL_DEMAND_CONFLUENCE",
            78,
            "INFERRED",
            "ETF flow strength is aligned with market participation signals.",
        )

    if (
        {"ETF_OUTFLOW_STRONG", "FUNDING_EXTREME_POSITIVE"} <= signal_names
        or {"ETF_NEGATIVE_REGIME", "OI_RISING_FAST"} <= signal_names
    ):
        _add_signal(
            signals,
            "DISTRIBUTION_RISK_CONFLUENCE",
            78,
            "INFERRED",
            "ETF outflows are aligned with elevated leverage or positioning risk.",
        )

    if (
        {"ETF_INFLOW_STRONG", "EXCHANGE_OUTFLOW_EXTREME"} <= signal_names
        or {"ETF_POSITIVE_REGIME", "EXCHANGE_RESERVES_FALLING"} <= signal_names
    ):
        _add_signal(
            signals,
            "CUSTODY_SUPPLY_CONFLUENCE",
            82,
            "INFERRED",
            "ETF flow strength and exchange outflow/reserve signals align.",
        )

    if (
        {"EXCHANGE_INFLOW_EXTREME", "EXCHANGE_RESERVES_RISING", "OI_RISING_FAST"} <= signal_names
        or {"EXCHANGE_INFLOW_EXTREME", "FUNDING_EXTREME_POSITIVE"} <= signal_names
    ):
        _add_signal(
            signals,
            "ONCHAIN_DISTRIBUTION_RISK_CONFLUENCE",
            84,
            "INFERRED",
            "Exchange inflow/reserve pressure aligns with leverage or positioning risk.",
        )

    if (
        {"CROWDED_LONG", "OI_RISING_FAST", "FUNDING_EXTREME_POSITIVE"} <= signal_names
        or {"CROWDED_SHORT", "OI_RISING_FAST", "FUNDING_EXTREME_NEGATIVE"} <= signal_names
    ):
        _add_signal(
            signals,
            "CROWDING_RISK_CONFLUENCE",
            78,
            "INFERRED",
            "Retail sentiment and derivatives point to crowded positioning; this is context, not a trading signal.",
        )

    if (
        "POSITIVE_FLOW_NEGATIVE_RETAIL_DIVERGENCE" in signal_names
        and (
            "ETF_INFLOW_STRONG" in signal_names
            or "ETF_INFLOW_EXTREME" in signal_names
            or "EXCHANGE_OUTFLOW_EXTREME" in signal_names
            or "EXCHANGE_RESERVES_FALLING" in signal_names
        )
    ):
        _add_signal(
            signals,
            "SENTIMENT_FLOW_DIVERGENCE_CONFLUENCE",
            80,
            "INFERRED",
            "Negative retail sentiment diverges from stronger ETF/on-chain flow proxies.",
        )

    if (
        "NEGATIVE_FLOW_POSITIVE_RETAIL_DIVERGENCE" in signal_names
        and (
            "ETF_OUTFLOW_STRONG" in signal_names
            or "ETF_OUTFLOW_EXTREME" in signal_names
            or "EXCHANGE_INFLOW_EXTREME" in signal_names
            or "EXCHANGE_RESERVES_RISING" in signal_names
        )
    ):
        _add_signal(
            signals,
            "SENTIMENT_DISTRIBUTION_RISK_CONFLUENCE",
            80,
            "INFERRED",
            "Positive retail sentiment diverges from weaker ETF/on-chain flow proxies.",
        )

    if (
        {"CROWDED_LONG", "FUNDING_EXTREME_POSITIVE"} <= signal_names
        and (
            "LIQUIDITY_VACUUM_BELOW" in signal_names
            or "FAILED_BREAKOUT" in signal_names
            or "LIQUIDITY_SWEEP_ABOVE" in signal_names
        )
    ):
        _add_signal(
            signals,
            "STRUCTURE_CROWDING_RISK_CONFLUENCE",
            78,
            "INFERRED",
            "Crowded long positioning aligns with weaker structure/liquidity context; this is risk context, not a price forecast.",
        )

    if (
        (
            "ETF_INFLOW_STRONG" in signal_names
            or "ETF_INFLOW_EXTREME" in signal_names
            or "CUSTODY_SUPPLY_CONFLUENCE" in signal_names
        )
        and (
            "BULLISH_BREAK_OF_STRUCTURE" in signal_names
            or "BID_LIQUIDITY_EXTREME" in signal_names
            or "ORDERBOOK_IMBALANCE_BID" in signal_names
        )
        and "FUNDING_EXTREME_POSITIVE" not in signal_names
    ):
        _add_signal(
            signals,
            "CONSTRUCTIVE_STRUCTURE_FLOW_CONFLUENCE",
            76,
            "INFERRED",
            "Positive flow proxies align with supportive book/structure context without implying a directional trading signal.",
        )

    if (
        "OI_FALLING_FAST" in signal_names
        and "VOLATILITY_EXPANSION" in signal_names
        and (
            "LONG_LIQUIDATION_SPIKE" in signal_names
            or "SHORT_LIQUIDATION_SPIKE" in signal_names
        )
    ):
        _add_signal(
            signals,
            "DELEVERAGING",
            90,
            "INFERRED",
            "OI collapse, liquidation spike and volatility expansion are present together.",
        )

    confluence_score = sum(signal.strength for signal in signals) // 3
    confluence_score = max(0, min(100, confluence_score))

    signal_names = {signal.name for signal in signals}

    if "DELEVERAGING" in signal_names:
        confluence = "HIGH"
        regime = "DELEVERAGING"
        summary = "BTC derivatives show a deleveraging candidate."
    elif "LEVERAGE_BUILDUP" in signal_names:
        confluence = "HIGH"
        regime = "LEVERAGED"
        summary = "BTC positioning shows leverage buildup; risk of disorderly deleveraging is elevated."
    elif "INSTITUTIONAL_DEMAND_CONFLUENCE" in signal_names:
        confluence = "HIGH"
        regime = "INSTITUTIONAL_FLOW_POSITIVE"
        summary = "BTC ETF flows and market participation show positive institutional-flow confluence."
    elif "DISTRIBUTION_RISK_CONFLUENCE" in signal_names:
        confluence = "HIGH"
        regime = "DISTRIBUTION_RISK"
        summary = "BTC ETF outflows and positioning show elevated distribution/deleveraging risk."
    elif "CUSTODY_SUPPLY_CONFLUENCE" in signal_names:
        confluence = "HIGH"
        regime = "ACCUMULATION_CONSISTENT"
        summary = "BTC ETF and on-chain flows are consistent with reduced exchange supply, without proving accumulation."
    elif "ONCHAIN_DISTRIBUTION_RISK_CONFLUENCE" in signal_names:
        confluence = "HIGH"
        regime = "DISTRIBUTION_RISK"
        summary = "BTC on-chain exchange inflows and positioning show elevated distribution-risk confluence."
    elif "CROWDING_RISK_CONFLUENCE" in signal_names:
        confluence = "HIGH"
        regime = "CROWDED_POSITIONING"
        summary = "BTC sentiment and derivatives show crowded positioning risk; Radar does not infer direction deterministically."
    elif "SENTIMENT_FLOW_DIVERGENCE_CONFLUENCE" in signal_names:
        confluence = "HIGH"
        regime = "FLOW_SENTIMENT_DIVERGENCE"
        summary = "BTC flow proxies strengthen while retail sentiment is negative; this is a divergence, not a price signal."
    elif "SENTIMENT_DISTRIBUTION_RISK_CONFLUENCE" in signal_names:
        confluence = "HIGH"
        regime = "DISTRIBUTION_RISK"
        summary = "BTC retail optimism diverges from weaker flow proxies, raising crowding/distribution-risk context."
    elif "STRUCTURE_CROWDING_RISK_CONFLUENCE" in signal_names:
        confluence = "HIGH"
        regime = "STRUCTURE_CROWDING_RISK"
        summary = "BTC crowded positioning aligns with weaker liquidity/structure context; Radar treats this as risk context only."
    elif "CONSTRUCTIVE_STRUCTURE_FLOW_CONFLUENCE" in signal_names:
        confluence = "HIGH"
        regime = "CONSTRUCTIVE_FLOW_STRUCTURE"
        summary = "BTC flow proxies and market structure are constructively aligned without producing a trading recommendation."
    elif confluence_score >= 45 and len(signals) >= 2:
        confluence = "MEDIUM"
        regime = "HIGH_VOLATILITY"
        summary = "BTC market state shows notable but incomplete confluence."
    else:
        confluence = "LOW"
        regime = "NEUTRAL"
        summary = "NO MATERIAL BTC MARKET ANOMALY"

    return BtcMarketState(
        snapshot=snapshot,
        etf_flows=etf_flows,
        onchain=onchain,
        sentiment=sentiment,
        liquidity_structure=liquidity_structure,
        signals=signals,
        confluence=confluence,
        confluence_score=confluence_score,
        market_regime=regime,
        onchain_regime=_onchain_regime(signal_names),
        summary=summary,
    )


def market_state_to_news_item(state):
    if state.confluence != "HIGH":
        return None

    signal_names = [signal.name for signal in state.signals]

    title = "BTC market state anomaly"
    if "DELEVERAGING" in signal_names:
        title = "BTC derivatives show deleveraging stress"
    elif "LEVERAGE_BUILDUP" in signal_names:
        title = "BTC leverage buildup raises deleveraging risk"
    elif "CROWDING_RISK_CONFLUENCE" in signal_names:
        title = "BTC positioning shows crowding risk"
    elif "SENTIMENT_FLOW_DIVERGENCE_CONFLUENCE" in signal_names:
        title = "BTC flows diverge from retail sentiment"
    elif "STRUCTURE_CROWDING_RISK_CONFLUENCE" in signal_names:
        title = "BTC liquidity and crowding risk align"
    elif "CONSTRUCTIVE_STRUCTURE_FLOW_CONFLUENCE" in signal_names:
        title = "BTC flows and structure show confluence"

    content = "\n".join(
        [
            state.summary,
            "Signals:",
            *[
                f"- {signal.name}: {signal.evidence}"
                for signal in state.signals
            ],
        ]
    )

    item = NewsItem(
        title=title,
        summary=state.summary,
        content=content,
        link=f"market-state:btc:{state.snapshot.timestamp}",
        published=state.snapshot.timestamp,
        source="MARKET_STATE",
        category="Market State",
        event_type="CRYPTO_MARKET_STRUCTURE",
        affected_assets=["BTC"],
        asset_class="CRYPTO",
        market_impact=78 if state.confluence == "HIGH" else 0,
        score=78 if state.confluence == "HIGH" else 0,
        materiality="HIGH" if state.confluence == "HIGH" else "LOW",
        confidence="Media",
        verification_status="PRELIMINARY",
        crypto_asset="BTC",
        mechanism="positioning/liquidity -> volatility risk -> BTC",
        market_signals=signal_names,
        confluence_score=state.confluence_score,
        evidence_level="CALCULATED",
    )

    return item


def fetch_btc_market_state(
    fetcher=fetch_btc_market_snapshot,
    etf_fetcher=fetch_btc_etf_flow_snapshot,
    onchain_fetcher=fetch_btc_onchain_snapshot,
    sentiment_fetcher=fetch_btc_sentiment_snapshot,
    liquidity_fetcher=fetch_btc_liquidity_structure_snapshot,
):
    try:
        snapshot = fetcher()
    except Exception as exc:
        snapshot = BtcMarketSnapshot(
            errors=[f"market_data:{type(exc).__name__}"]
        )

    try:
        etf_flows = etf_fetcher()
    except Exception as exc:
        etf_flows = BtcEtfFlowSnapshot(
            errors=[f"etf_flows:{type(exc).__name__}"]
        )

    try:
        onchain = onchain_fetcher()
    except Exception as exc:
        onchain = BtcOnchainSnapshot(
            errors=[f"onchain:{type(exc).__name__}"]
        )

    try:
        sentiment = sentiment_fetcher()
    except Exception as exc:
        sentiment = BtcSentimentSnapshot(
            errors=[f"sentiment:{type(exc).__name__}"]
        )

    try:
        liquidity_structure = liquidity_fetcher()
    except Exception as exc:
        liquidity_structure = BtcLiquidityStructureSnapshot(
            errors=[f"liquidity_structure:{type(exc).__name__}"]
        )

    return analyze_btc_market_state(
        snapshot,
        etf_flows,
        onchain,
        sentiment,
        liquidity_structure,
    )
