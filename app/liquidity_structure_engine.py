from dataclasses import dataclass, field
from datetime import datetime, timezone

from market_data import BinanceMarketDataClient, _safe_float, _zscore


@dataclass
class LiquidityCluster:
    price: float | None = None
    notional: float | None = None
    distance_pct: float | None = None


@dataclass
class LiquidityStructureSignal:
    name: str
    strength: int
    certainty: str
    evidence: str
    timestamp: str = ""
    source: str = "LIQUIDITY_STRUCTURE"


@dataclass
class BtcLiquidityStructureSnapshot:
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    spread_pct: float | None = None
    bid_depth_0_5pct: float | None = None
    ask_depth_0_5pct: float | None = None
    bid_depth_1pct: float | None = None
    ask_depth_1pct: float | None = None
    bid_depth_2pct: float | None = None
    ask_depth_2pct: float | None = None
    book_imbalance: float | None = None
    largest_bid_cluster: LiquidityCluster | None = None
    largest_ask_cluster: LiquidityCluster | None = None
    liquidity_above: str = "UNKNOWN"
    liquidity_below: str = "UNKNOWN"
    structure: str = "UNKNOWN"
    breakout_state: str = "UNKNOWN"
    liquidity_sweep: str = "UNKNOWN"
    smc_signals: list[str] = field(default_factory=list)
    interpretation: str = "UNKNOWN"
    timestamp: str = ""
    provider: str = "Binance USD-M Futures order book"
    errors: list[str] = field(default_factory=list)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clamp_strength(value):
    return max(0, min(100, int(value)))


def _add_signal(signals, name, strength, certainty, evidence, timestamp="", source="LIQUIDITY_STRUCTURE"):
    signals.append(
        LiquidityStructureSignal(
            name=name,
            strength=_clamp_strength(strength),
            certainty=certainty,
            evidence=evidence,
            timestamp=timestamp,
            source=source,
        )
    )


def _levels(rows):
    levels = []
    for row in rows or []:
        if len(row) < 2:
            continue
        price = _safe_float(row[0])
        qty = _safe_float(row[1])
        if price is None or qty is None:
            continue
        levels.append((price, qty, price * qty))
    return levels


def _depth_within(levels, mid, pct, side):
    if mid in {None, 0}:
        return None
    if side == "bid":
        floor = mid * (1 - pct)
        return sum(notional for price, _, notional in levels if price >= floor)
    ceiling = mid * (1 + pct)
    return sum(notional for price, _, notional in levels if price <= ceiling)


def _largest_cluster(levels, mid, side):
    if not levels or mid in {None, 0}:
        return None

    if side == "bid":
        candidates = [
            (price, notional)
            for price, _, notional in levels
            if price >= mid * 0.98
        ]
    else:
        candidates = [
            (price, notional)
            for price, _, notional in levels
            if price <= mid * 1.02
        ]

    if not candidates:
        return None

    price, notional = max(candidates, key=lambda row: row[1])
    return LiquidityCluster(
        price=price,
        notional=notional,
        distance_pct=((price - mid) / mid) * 100,
    )


def normalize_order_book(depth):
    snapshot = BtcLiquidityStructureSnapshot(timestamp=_now())
    bids = _levels(depth.get("bids"))
    asks = _levels(depth.get("asks"))

    if not bids or not asks:
        snapshot.errors.append("order_book:NO_DATA")
        return snapshot

    bids = sorted(bids, key=lambda row: row[0], reverse=True)
    asks = sorted(asks, key=lambda row: row[0])
    snapshot.best_bid = bids[0][0]
    snapshot.best_ask = asks[0][0]
    mid = (snapshot.best_bid + snapshot.best_ask) / 2
    snapshot.spread = snapshot.best_ask - snapshot.best_bid
    snapshot.spread_pct = (snapshot.spread / mid) * 100 if mid else None

    snapshot.bid_depth_0_5pct = _depth_within(bids, mid, 0.005, "bid")
    snapshot.ask_depth_0_5pct = _depth_within(asks, mid, 0.005, "ask")
    snapshot.bid_depth_1pct = _depth_within(bids, mid, 0.01, "bid")
    snapshot.ask_depth_1pct = _depth_within(asks, mid, 0.01, "ask")
    snapshot.bid_depth_2pct = _depth_within(bids, mid, 0.02, "bid")
    snapshot.ask_depth_2pct = _depth_within(asks, mid, 0.02, "ask")
    snapshot.largest_bid_cluster = _largest_cluster(bids, mid, "bid")
    snapshot.largest_ask_cluster = _largest_cluster(asks, mid, "ask")

    bid_1 = snapshot.bid_depth_1pct or 0
    ask_1 = snapshot.ask_depth_1pct or 0
    if bid_1 + ask_1:
        snapshot.book_imbalance = (bid_1 - ask_1) / (bid_1 + ask_1)

    if snapshot.largest_ask_cluster and snapshot.largest_ask_cluster.notional:
        snapshot.liquidity_above = "OBSERVED"
    if snapshot.largest_bid_cluster and snapshot.largest_bid_cluster.notional:
        snapshot.liquidity_below = "OBSERVED"

    return snapshot


def _kline_parts(kline):
    return {
        "open": _safe_float(kline[1]),
        "high": _safe_float(kline[2]),
        "low": _safe_float(kline[3]),
        "close": _safe_float(kline[4]),
        "volume": _safe_float(kline[5]),
    }


def add_market_structure(snapshot, klines):
    candles = [_kline_parts(kline) for kline in klines or []]
    candles = [
        candle
        for candle in candles
        if all(candle[key] is not None for key in ["open", "high", "low", "close"])
    ]

    if len(candles) < 12:
        if not snapshot.errors:
            snapshot.errors.append("structure:INSUFFICIENT_DATA")
        return snapshot

    latest = candles[-1]
    previous = candles[-2]
    context = candles[-13:-1] if len(candles) >= 13 else candles[:-1]
    range_high = max(candle["high"] for candle in context)
    range_low = min(candle["low"] for candle in context)
    recent_closes = [candle["close"] for candle in candles[-6:]]
    older_closes = [candle["close"] for candle in candles[-12:-6]]
    volume_values = [candle["volume"] for candle in candles if candle["volume"] is not None]
    volume_z = _zscore(latest["volume"], volume_values[:-1])

    latest_close = latest["close"]
    recent_avg = sum(recent_closes) / len(recent_closes)
    older_avg = sum(older_closes) / len(older_closes) if older_closes else recent_avg

    if latest_close > range_high:
        snapshot.structure = "BULLISH"
        snapshot.breakout_state = "BREAKOUT_UP"
    elif latest_close < range_low:
        snapshot.structure = "BEARISH"
        snapshot.breakout_state = "BREAKOUT_DOWN"
    elif latest["high"] > range_high and latest_close < range_high:
        snapshot.structure = "RANGE"
        snapshot.breakout_state = "FAILED_BREAKOUT_UP"
        snapshot.liquidity_sweep = "ABOVE"
    elif latest["low"] < range_low and latest_close > range_low:
        snapshot.structure = "RANGE"
        snapshot.breakout_state = "FAILED_BREAKOUT_DOWN"
        snapshot.liquidity_sweep = "BELOW"
    elif abs(recent_avg - older_avg) / latest_close < 0.01:
        snapshot.structure = "RANGE"
    elif recent_avg > older_avg:
        snapshot.structure = "BULLISH"
    elif recent_avg < older_avg:
        snapshot.structure = "BEARISH"
    else:
        snapshot.structure = "TRANSITION"

    candle_change = ((latest_close - latest["open"]) / latest["open"]) * 100
    if volume_z is not None and volume_z >= 2 and candle_change > 1.5:
        snapshot.smc_signals.append("DISPLACEMENT_UP")
    elif volume_z is not None and volume_z >= 2 and candle_change < -1.5:
        snapshot.smc_signals.append("DISPLACEMENT_DOWN")

    if len(candles) >= 3:
        two_back = candles[-3]
        if latest["low"] > two_back["high"]:
            snapshot.smc_signals.append("FVG_BELOW")
        elif latest["high"] < two_back["low"]:
            snapshot.smc_signals.append("FVG_ABOVE")

    if snapshot.liquidity_sweep == "ABOVE":
        snapshot.smc_signals.append("LIQUIDITY_SWEEP_ABOVE")
    elif snapshot.liquidity_sweep == "BELOW":
        snapshot.smc_signals.append("LIQUIDITY_SWEEP_BELOW")

    if previous["close"] < range_high < latest_close:
        snapshot.smc_signals.append("BULLISH_BREAK_OF_STRUCTURE")
    elif previous["close"] > range_low > latest_close:
        snapshot.smc_signals.append("BEARISH_BREAK_OF_STRUCTURE")

    if snapshot.breakout_state.startswith("FAILED_BREAKOUT"):
        snapshot.smc_signals.append("FAILED_BREAKOUT")

    snapshot.interpretation = (
        "Technical structure is a contextual signal and does not prove intentional stop hunting or institutional activity."
    )
    return snapshot


def fetch_btc_liquidity_structure_snapshot(client=None):
    client = client or BinanceMarketDataClient()
    snapshot = BtcLiquidityStructureSnapshot(timestamp=_now())

    try:
        snapshot = normalize_order_book(client.depth(limit=1000))
    except Exception as exc:
        snapshot.errors.append(f"order_book:{type(exc).__name__}")

    try:
        add_market_structure(snapshot, client.klines(interval="1h", limit=72))
    except Exception as exc:
        snapshot.errors.append(f"structure:{type(exc).__name__}")

    return snapshot


def analyze_liquidity_structure(snapshot):
    if snapshot is None:
        return []

    signals = []
    timestamp = snapshot.timestamp
    bid_1 = snapshot.bid_depth_1pct
    ask_1 = snapshot.ask_depth_1pct
    bid_2 = snapshot.bid_depth_2pct
    ask_2 = snapshot.ask_depth_2pct

    if bid_1 is not None and ask_1 not in {None, 0} and bid_1 >= ask_1 * 2.5:
        _add_signal(
            signals,
            "BID_LIQUIDITY_EXTREME",
            min(100, (bid_1 / ask_1) * 25),
            "CALCULATED",
            f"Bid depth within 1% is {bid_1 / ask_1:.2f}x ask depth on Binance futures.",
            timestamp,
        )
    if ask_1 is not None and bid_1 not in {None, 0} and ask_1 >= bid_1 * 2.5:
        _add_signal(
            signals,
            "ASK_LIQUIDITY_EXTREME",
            min(100, (ask_1 / bid_1) * 25),
            "CALCULATED",
            f"Ask depth within 1% is {ask_1 / bid_1:.2f}x bid depth on Binance futures.",
            timestamp,
        )

    if snapshot.book_imbalance is not None:
        if snapshot.book_imbalance >= 0.45:
            _add_signal(
                signals,
                "ORDERBOOK_IMBALANCE_BID",
                min(100, abs(snapshot.book_imbalance) * 140),
                "CALCULATED",
                f"Order book imbalance within 1% favors bids: {snapshot.book_imbalance:.2f}.",
                timestamp,
            )
        elif snapshot.book_imbalance <= -0.45:
            _add_signal(
                signals,
                "ORDERBOOK_IMBALANCE_ASK",
                min(100, abs(snapshot.book_imbalance) * 140),
                "CALCULATED",
                f"Order book imbalance within 1% favors asks: {snapshot.book_imbalance:.2f}.",
                timestamp,
            )

    if bid_2 is not None and ask_2 not in {None, 0} and bid_2 <= ask_2 * 0.25:
        _add_signal(
            signals,
            "LIQUIDITY_VACUUM_BELOW",
            65,
            "INFERRED",
            "Visible bid depth within 2% is thin relative to ask depth.",
            timestamp,
        )
    if ask_2 is not None and bid_2 not in {None, 0} and ask_2 <= bid_2 * 0.25:
        _add_signal(
            signals,
            "LIQUIDITY_VACUUM_ABOVE",
            65,
            "INFERRED",
            "Visible ask depth within 2% is thin relative to bid depth.",
            timestamp,
        )

    for name in snapshot.smc_signals:
        if name in {
            "BULLISH_BREAK_OF_STRUCTURE",
            "BEARISH_BREAK_OF_STRUCTURE",
            "DISPLACEMENT_UP",
            "DISPLACEMENT_DOWN",
        }:
            strength = 60
        elif name.startswith("LIQUIDITY_SWEEP") or name == "FAILED_BREAKOUT":
            strength = 58
        else:
            strength = 42
        _add_signal(
            signals,
            name,
            strength,
            "INFERRED",
            "Technical market-structure heuristic; not evidence of intentional institutional activity.",
            timestamp,
        )

    return signals
