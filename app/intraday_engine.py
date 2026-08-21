from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import INTRADAY_MAX_DATA_AGE_MINUTES, INTRADAY_MIN_CONFLUENCE
from market_data import BinanceMarketDataClient, _mean, _pct_change, _safe_float, _stdev
from models import NewsItem
from sources_registry import apply_source_metadata


@dataclass
class IntradaySignal:
    name: str
    timeframe: str
    strength: int
    certainty: str
    evidence: str
    source: str = "BINANCE_KLINES"


@dataclass
class IntradayLiquidityMap:
    visible_above: str = "UNKNOWN"
    visible_below: str = "UNKNOWN"
    inferred_above: str = "UNKNOWN"
    inferred_below: str = "UNKNOWN"
    nearest_visible_above: float | None = None
    nearest_visible_below: float | None = None
    nearest_visible_above_notional: float | None = None
    nearest_visible_below_notional: float | None = None
    equal_highs: float | None = None
    equal_lows: float | None = None
    previous_day_high: float | None = None
    previous_day_low: float | None = None
    previous_week_high: float | None = None
    previous_week_low: float | None = None
    liquidity_vacuum: str = "UNKNOWN"
    liquidity_imbalance: str = "UNKNOWN"


@dataclass
class BtcIntradaySnapshot:
    price: float | None = None
    price_change_5m: float | None = None
    price_change_15m: float | None = None
    price_change_30m: float | None = None
    price_change_1h: float | None = None
    price_change_4h: float | None = None
    price_change_24h: float | None = None
    volume_15m: float | None = None
    volume_1h: float | None = None
    volume_4h: float | None = None
    volume_ratio_15m: float | None = None
    volume_ratio_1h: float | None = None
    volume_ratio_4h: float | None = None
    realized_volatility_15m: float | None = None
    realized_volatility_1h: float | None = None
    realized_volatility_4h: float | None = None
    volatility_ratio_15m: float | None = None
    volatility_ratio_1h: float | None = None
    volatility_ratio_4h: float | None = None
    open_interest: float | None = None
    oi_change_15m: float | None = None
    oi_change_1h: float | None = None
    oi_change_4h: float | None = None
    funding_rate: float | None = None
    funding_change: float | None = None
    funding_regime: str = "UNKNOWN"
    structure_15m: str = "UNKNOWN"
    structure_1h: str = "UNKNOWN"
    structure_4h: str = "UNKNOWN"
    structure_1d: str = "UNKNOWN"
    liquidity: IntradayLiquidityMap = field(default_factory=IntradayLiquidityMap)
    market_data_age_minutes: float | None = None
    status: str = "UNKNOWN"
    data_available: dict[str, bool] = field(default_factory=dict)
    timestamp: str = ""
    provider: str = "Binance USD-M Futures"
    errors: list[str] = field(default_factory=list)


@dataclass
class BtcIntradayState:
    snapshot: BtcIntradaySnapshot
    signals: list[IntradaySignal] = field(default_factory=list)
    move_abnormality_score: int = 0
    liquidity_importance_score: int = 0
    smc_confluence_score: int = 0
    intraday_news_relevance: int = 0
    intraday_confluence_score: int = 0
    intraday_materiality: str = "INTRADAY_LOW"
    catalyst_status: str = "NO_CLEAR_CATALYST"
    catalyst_source: str = ""
    catalyst_confidence: str = "Baja"
    decision: str = "NO_INTRADAY_ALERT"
    time_horizon: str = "1-4H"
    reading: str = ""
    invalidation: str = ""
    status: str = "UNKNOWN"
    data_available: dict[str, bool] = field(default_factory=dict)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clamp(value):
    return max(0, min(100, int(value)))


def _add_signal(signals, name, timeframe, strength, certainty, evidence, source="BINANCE_KLINES"):
    signals.append(
        IntradaySignal(
            name=name,
            timeframe=timeframe,
            strength=_clamp(strength),
            certainty=certainty,
            evidence=evidence,
            source=source,
        )
    )


def _kline(kline):
    return {
        "open_time": kline[0] if len(kline) > 0 else None,
        "open": _safe_float(kline[1]) if len(kline) > 1 else None,
        "high": _safe_float(kline[2]) if len(kline) > 2 else None,
        "low": _safe_float(kline[3]) if len(kline) > 3 else None,
        "close": _safe_float(kline[4]) if len(kline) > 4 else None,
        "volume": _safe_float(kline[5]) if len(kline) > 5 else None,
    }


def _valid_candles(klines):
    candles = [_kline(kline) for kline in klines or []]
    return [
        candle
        for candle in candles
        if all(candle.get(key) is not None for key in ["open", "high", "low", "close", "volume"])
    ]


def _change_from_bars(candles, bars):
    if not candles or len(candles) <= bars:
        return None
    return _pct_change(candles[-1]["close"], candles[-1 - bars]["close"])


def _volume_sum(candles, bars):
    if not candles or len(candles) < bars:
        return None
    return sum(candle["volume"] for candle in candles[-bars:])


def _window_sums(values, size):
    if len(values) < size:
        return []
    return [sum(values[i : i + size]) for i in range(0, len(values) - size + 1, size)]


def _volume_ratio(candles, bars):
    if not candles or len(candles) < bars * 4:
        return None
    values = [candle["volume"] for candle in candles]
    current = sum(values[-bars:])
    prior = values[: -bars]
    baseline = _mean(_window_sums(prior, bars)[-12:])
    if baseline in {None, 0}:
        return None
    return current / baseline


def _range_volatility(candles, bars):
    if not candles or len(candles) < bars:
        return None
    window = candles[-bars:]
    high = max(candle["high"] for candle in window)
    low = min(candle["low"] for candle in window)
    close = window[-1]["close"]
    if close in {None, 0}:
        return None
    return ((high - low) / close) * 100


def _volatility_ratio(candles, bars):
    if not candles or len(candles) < bars * 4:
        return None
    current = _range_volatility(candles, bars)
    prior = candles[:-bars]
    windows = []
    for idx in range(0, len(prior) - bars + 1, bars):
        value = _range_volatility(prior[idx : idx + bars], bars)
        if value is not None:
            windows.append(value)
    baseline = _mean(windows[-12:])
    if current is None or baseline in {None, 0}:
        return None
    return current / baseline


def _movement_baseline(candles, bars):
    if not candles or len(candles) < bars * 10:
        return None
    moves = []
    for idx in range(bars, len(candles) - bars):
        previous = candles[idx - bars]["close"]
        current = candles[idx]["close"]
        change = _pct_change(current, previous)
        if change is not None:
            moves.append(abs(change))
    return _mean(moves[-48:])


def _structure(candles):
    if not candles or len(candles) < 20:
        return "UNKNOWN"
    latest = candles[-1]
    previous = candles[-2]
    context = candles[-21:-1]
    high = max(candle["high"] for candle in context)
    low = min(candle["low"] for candle in context)
    recent = _mean([candle["close"] for candle in candles[-6:]])
    older = _mean([candle["close"] for candle in candles[-18:-6]])
    if latest["close"] > high:
        return "BULLISH_BREAKOUT"
    if latest["close"] < low:
        return "BEARISH_BREAKOUT"
    if latest["high"] > high and latest["close"] < high:
        return "FAILED_BREAKOUT_UP"
    if latest["low"] < low and latest["close"] > low:
        return "FAILED_BREAKOUT_DOWN"
    if recent is None or older is None:
        return "UNKNOWN"
    if abs(recent - older) / latest["close"] < 0.005:
        return "RANGE"
    return "BULLISH" if recent > older else "BEARISH"


def _equal_level(candles, side):
    if not candles or len(candles) < 12:
        return None
    values = [candle["high"] if side == "high" else candle["low"] for candle in candles[-40:]]
    tolerance = (values[-1] if values else 0) * 0.001
    if not tolerance:
        return None
    for idx, value in enumerate(values):
        nearby = [other for other in values[idx + 1 :] if abs(other - value) <= tolerance]
        if len(nearby) >= 1:
            return _mean([value] + nearby)
    return None


def _oi_change(rows, lookback=1):
    values = [
        _safe_float(row.get("sumOpenInterestValue") or row.get("sumOpenInterest"))
        for row in rows or []
    ]
    values = [value for value in values if value is not None]
    if len(values) <= lookback:
        return None, values[-1] if values else None
    return _pct_change(values[-1], values[-1 - lookback]), values[-1]


def _funding_regime(values):
    values = [value for value in values if value is not None]
    if not values:
        return "UNKNOWN", None
    latest = values[-1]
    avg = _mean(values[:-1])
    sd = _stdev(values[:-1])
    if sd and latest >= avg + 2 * sd:
        return "POSITIVE_EXTREME", latest
    if sd and latest <= avg - 2 * sd:
        return "NEGATIVE_EXTREME", latest
    if latest > 0:
        return "POSITIVE", latest
    if latest < 0:
        return "NEGATIVE", latest
    return "NEUTRAL", latest


def _fetch_optional(snapshot, name, func):
    try:
        return func()
    except Exception as exc:
        snapshot.errors.append(f"{name}:{type(exc).__name__}")
        return None


def _liquidity_map(liquidity_structure, candles_5m, daily_candles):
    liquidity = IntradayLiquidityMap()
    if liquidity_structure:
        bid = liquidity_structure.largest_bid_cluster
        ask = liquidity_structure.largest_ask_cluster
        if ask and ask.price is not None:
            liquidity.visible_above = "ORDER_BOOK_VISIBLE"
            liquidity.nearest_visible_above = ask.price
            liquidity.nearest_visible_above_notional = ask.notional
        if bid and bid.price is not None:
            liquidity.visible_below = "ORDER_BOOK_VISIBLE"
            liquidity.nearest_visible_below = bid.price
            liquidity.nearest_visible_below_notional = bid.notional
        if liquidity_structure.book_imbalance is not None:
            if liquidity_structure.book_imbalance >= 0.35:
                liquidity.liquidity_imbalance = "BID_IMBALANCE"
            elif liquidity_structure.book_imbalance <= -0.35:
                liquidity.liquidity_imbalance = "ASK_IMBALANCE"

    eq_high = _equal_level(candles_5m, "high")
    eq_low = _equal_level(candles_5m, "low")
    if eq_high is not None:
        liquidity.equal_highs = eq_high
        liquidity.inferred_above = "STRUCTURE_INFERRED"
    if eq_low is not None:
        liquidity.equal_lows = eq_low
        liquidity.inferred_below = "STRUCTURE_INFERRED"

    if len(daily_candles) >= 2:
        previous_day = daily_candles[-2]
        liquidity.previous_day_high = previous_day["high"]
        liquidity.previous_day_low = previous_day["low"]
    if len(daily_candles) >= 8:
        previous_week = daily_candles[-8:-1]
        liquidity.previous_week_high = max(candle["high"] for candle in previous_week)
        liquidity.previous_week_low = min(candle["low"] for candle in previous_week)

    return liquidity


def fetch_btc_intraday_snapshot(client=None, liquidity_structure=None):
    client = client or BinanceMarketDataClient()
    snapshot = BtcIntradaySnapshot(timestamp=_now())
    snapshot.market_data_age_minutes = 0.0
    snapshot.data_available = {
        "price": False,
        "klines": False,
        "volume": False,
        "open_interest": False,
        "funding": False,
        "order_book": False,
    }

    candles_5m = _valid_candles(
        _fetch_optional(snapshot, "klines_5m", lambda: client.klines(interval="5m", limit=288))
    )
    candles_15m = []
    candles_1h = []
    candles_4h = []
    daily_candles = []
    if candles_5m:
        candles_15m = _valid_candles(
            _fetch_optional(snapshot, "klines_15m", lambda: client.klines(interval="15m", limit=160))
        )
        candles_1h = _valid_candles(
            _fetch_optional(snapshot, "klines_1h", lambda: client.klines(interval="1h", limit=120))
        )
        candles_4h = _valid_candles(
            _fetch_optional(snapshot, "klines_4h", lambda: client.klines(interval="4h", limit=90))
        )
        daily_candles = _valid_candles(
            _fetch_optional(snapshot, "klines_1d", lambda: client.klines(interval="1d", limit=14))
        )

    if candles_5m:
        snapshot.price = candles_5m[-1]["close"]
    snapshot.price_change_5m = _change_from_bars(candles_5m, 1)
    snapshot.price_change_15m = _change_from_bars(candles_5m, 3)
    snapshot.price_change_30m = _change_from_bars(candles_5m, 6)
    snapshot.price_change_1h = _change_from_bars(candles_5m, 12)
    snapshot.price_change_4h = _change_from_bars(candles_5m, 48)
    snapshot.price_change_24h = _change_from_bars(candles_5m, 288 - 1)
    snapshot.volume_15m = _volume_sum(candles_5m, 3)
    snapshot.volume_1h = _volume_sum(candles_5m, 12)
    snapshot.volume_4h = _volume_sum(candles_5m, 48)
    snapshot.volume_ratio_15m = _volume_ratio(candles_5m, 3)
    snapshot.volume_ratio_1h = _volume_ratio(candles_5m, 12)
    snapshot.volume_ratio_4h = _volume_ratio(candles_5m, 48)
    snapshot.realized_volatility_15m = _range_volatility(candles_5m, 3)
    snapshot.realized_volatility_1h = _range_volatility(candles_5m, 12)
    snapshot.realized_volatility_4h = _range_volatility(candles_5m, 48)
    snapshot.volatility_ratio_15m = _volatility_ratio(candles_5m, 3)
    snapshot.volatility_ratio_1h = _volatility_ratio(candles_5m, 12)
    snapshot.volatility_ratio_4h = _volatility_ratio(candles_5m, 48)
    snapshot.structure_15m = _structure(candles_15m)
    snapshot.structure_1h = _structure(candles_1h)
    snapshot.structure_4h = _structure(candles_4h)
    snapshot.structure_1d = _structure(daily_candles)
    snapshot.liquidity = _liquidity_map(liquidity_structure, candles_5m, daily_candles)
    snapshot.data_available["price"] = snapshot.price is not None
    snapshot.data_available["klines"] = bool(candles_5m and candles_15m and candles_1h and candles_4h)
    snapshot.data_available["volume"] = snapshot.volume_1h is not None

    if candles_5m:
        try:
            oi_15m, latest_oi = _oi_change(client.open_interest_hist(period="5m", limit=64), lookback=3)
            oi_1h, latest_oi_1h = _oi_change(client.open_interest_hist(period="5m", limit=80), lookback=12)
            oi_4h, latest_oi_4h = _oi_change(client.open_interest_hist(period="15m", limit=80), lookback=16)
            snapshot.oi_change_15m = oi_15m
            snapshot.oi_change_1h = oi_1h
            snapshot.oi_change_4h = oi_4h
            snapshot.open_interest = latest_oi_1h or latest_oi_4h or latest_oi
            snapshot.data_available["open_interest"] = snapshot.open_interest is not None
        except Exception as exc:
            snapshot.errors.append(f"open_interest:{type(exc).__name__}")

        try:
            funding = client.funding_rate(limit=24)
            funding_values = [_safe_float(row.get("fundingRate")) for row in funding]
            snapshot.funding_regime, snapshot.funding_rate = _funding_regime(funding_values)
            if len(funding_values) >= 2:
                snapshot.funding_change = funding_values[-1] - funding_values[-2]
            snapshot.data_available["funding"] = snapshot.funding_rate is not None
        except Exception as exc:
            snapshot.errors.append(f"funding:{type(exc).__name__}")

    snapshot.data_available["order_book"] = bool(
        liquidity_structure
        and (
            getattr(liquidity_structure, "best_bid", None) is not None
            or getattr(liquidity_structure, "best_ask", None) is not None
            or getattr(liquidity_structure, "book_imbalance", None) is not None
        )
    )

    core_available = (
        snapshot.data_available["price"]
        and snapshot.data_available["klines"]
        and snapshot.data_available["volume"]
    )
    important_available = (
        snapshot.data_available["open_interest"]
        and snapshot.data_available["funding"]
        and snapshot.data_available["order_book"]
    )
    if not core_available:
        snapshot.status = "INSUFFICIENT"
    elif important_available and not snapshot.errors:
        snapshot.status = "FULL"
    else:
        snapshot.status = "DEGRADED"

    return snapshot


def _score_move(snapshot):
    scores = []
    inputs = [
        (snapshot.price_change_15m, 3.0, 26),
        (snapshot.price_change_30m, 2.2, 22),
        (snapshot.price_change_1h, 1.6, 20),
        (snapshot.price_change_4h, 1.0, 14),
    ]
    for change, multiplier, weight in inputs:
        if change is not None:
            scores.append(min(100, abs(change) * multiplier * weight))
    base = max(scores) if scores else 0
    if snapshot.volume_ratio_1h is not None and snapshot.volume_ratio_1h >= 1.8:
        base += 12
    if snapshot.volatility_ratio_1h is not None and snapshot.volatility_ratio_1h >= 1.8:
        base += 12
    return _clamp(base)


def _score_liquidity(snapshot):
    score = 0
    liquidity = snapshot.liquidity
    price = snapshot.price

    def near(level, max_distance):
        if price in {None, 0} or level is None:
            return False
        return abs(level - price) / price * 100 <= max_distance

    if near(liquidity.nearest_visible_above, 0.8):
        score += 22
    if near(liquidity.nearest_visible_below, 0.8):
        score += 22
    if near(liquidity.equal_highs, 1.0):
        score += 16
    if near(liquidity.equal_lows, 1.0):
        score += 16
    if near(liquidity.previous_day_high, 1.5):
        score += 12
    if near(liquidity.previous_day_low, 1.5):
        score += 12
    if liquidity.liquidity_imbalance != "UNKNOWN":
        score += 16
    return _clamp(score)


def _score_smc(snapshot, signals):
    smc_names = {
        signal.name
        for signal in signals
        if signal.source in {"STRUCTURE_INFERRED", "LIQUIDITY_STRUCTURE"}
    }
    score = len(smc_names) * 18
    if any("BREAK_OF_STRUCTURE" in name or "BREAKOUT" in name for name in smc_names):
        score += 18
    if any("SWEEP" in name for name in smc_names):
        score += 16
    if snapshot.volume_ratio_1h is not None and snapshot.volume_ratio_1h >= 1.8:
        score += 12
    if snapshot.oi_change_1h is not None and abs(snapshot.oi_change_1h) >= 2:
        score += 12
    return _clamp(score)


def _materiality(score):
    if score >= 90:
        return "INTRADAY_CRITICAL"
    if score >= 75:
        return "INTRADAY_HIGH"
    if score >= 55:
        return "INTRADAY_MEDIUM"
    return "INTRADAY_LOW"


def _direction(snapshot):
    change = snapshot.price_change_1h
    if change is None:
        change = snapshot.price_change_4h
    if change is None:
        return "FLAT"
    if change >= 0.25:
        return "UP"
    if change <= -0.25:
        return "DOWN"
    return "FLAT"


def _fresh_enough(snapshot):
    if snapshot.market_data_age_minutes is None:
        return True
    return snapshot.market_data_age_minutes <= INTRADAY_MAX_DATA_AGE_MINUTES


def analyze_btc_intraday_state(snapshot, liquidity_structure=None):
    if not snapshot.data_available:
        snapshot.data_available = {
            "price": snapshot.price is not None,
            "klines": any(
                value is not None
                for value in [
                    snapshot.price_change_15m,
                    snapshot.price_change_1h,
                    snapshot.price_change_4h,
                ]
            ),
            "volume": snapshot.volume_1h is not None,
            "open_interest": snapshot.open_interest is not None or snapshot.oi_change_1h is not None,
            "funding": snapshot.funding_rate is not None,
            "order_book": (
                snapshot.liquidity.visible_above == "ORDER_BOOK_VISIBLE"
                or snapshot.liquidity.visible_below == "ORDER_BOOK_VISIBLE"
            ),
        }
    if snapshot.status == "UNKNOWN":
        core_available = (
            snapshot.data_available.get("price")
            and snapshot.data_available.get("klines")
            and snapshot.data_available.get("volume")
        )
        if not core_available:
            snapshot.status = "INSUFFICIENT"
        elif all(
            snapshot.data_available.get(key)
            for key in ["open_interest", "funding", "order_book"]
        ):
            snapshot.status = "FULL"
        else:
            snapshot.status = "DEGRADED"

    if snapshot.status == "INSUFFICIENT":
        return BtcIntradayState(
            snapshot=snapshot,
            intraday_materiality="INTRADAY_LOW",
            decision="INSUFFICIENT_DATA",
            reading="Datos intradía insuficientes para evaluar BTC sin riesgo de falsa conclusión.",
            invalidation="Radar necesita precio, klines y volumen intradía actuales para evaluar esta capa.",
            status="INSUFFICIENT",
            data_available=dict(snapshot.data_available),
        )

    signals = []
    direction = _direction(snapshot)

    move_score = _score_move(snapshot)
    if direction == "UP" and move_score >= 55:
        _add_signal(
            signals,
            "PRICE_ACCELERATION_UP",
            "15m-1h",
            move_score,
            "CALCULATED",
            f"BTC change: 15m={snapshot.price_change_15m}, 1h={snapshot.price_change_1h}, 4h={snapshot.price_change_4h}",
        )
    elif direction == "DOWN" and move_score >= 55:
        _add_signal(
            signals,
            "PRICE_ACCELERATION_DOWN",
            "15m-1h",
            move_score,
            "CALCULATED",
            f"BTC change: 15m={snapshot.price_change_15m}, 1h={snapshot.price_change_1h}, 4h={snapshot.price_change_4h}",
        )

    if snapshot.volume_ratio_1h is not None and snapshot.volume_ratio_1h >= 1.8:
        _add_signal(
            signals,
            "VOLUME_EXPANSION",
            "1h",
            min(100, snapshot.volume_ratio_1h * 28),
            "CALCULATED",
            f"1h volume is {snapshot.volume_ratio_1h:.2f}x recent baseline.",
        )
    if snapshot.volatility_ratio_1h is not None and snapshot.volatility_ratio_1h >= 1.8:
        _add_signal(
            signals,
            "VOLATILITY_EXPANSION",
            "1h",
            min(100, snapshot.volatility_ratio_1h * 28),
            "CALCULATED",
            f"1h realized range is {snapshot.volatility_ratio_1h:.2f}x recent baseline.",
        )

    if snapshot.volume_ratio_1h is not None and snapshot.volume_ratio_1h >= 1.6 and direction in {"UP", "DOWN"}:
        _add_signal(
            signals,
            "VOLUME_CONFIRMATION",
            "1h",
            min(100, snapshot.volume_ratio_1h * 25),
            "CALCULATED",
            "Volume expansion is aligned with the intraday move.",
        )

    for timeframe, structure in [
        ("15m", snapshot.structure_15m),
        ("1h", snapshot.structure_1h),
        ("4h", snapshot.structure_4h),
    ]:
        if structure == "BULLISH_BREAKOUT":
            _add_signal(signals, "BREAKOUT_UP", timeframe, 68, "INFERRED", f"{timeframe} structure closed above recent range.", "STRUCTURE_INFERRED")
            _add_signal(signals, "BULLISH_BREAK_OF_STRUCTURE", timeframe, 62, "INFERRED", "Technical BOS heuristic; not evidence of institutional activity.", "STRUCTURE_INFERRED")
        elif structure == "BEARISH_BREAKOUT":
            _add_signal(signals, "BREAKOUT_DOWN", timeframe, 68, "INFERRED", f"{timeframe} structure closed below recent range.", "STRUCTURE_INFERRED")
            _add_signal(signals, "BEARISH_BREAK_OF_STRUCTURE", timeframe, 62, "INFERRED", "Technical BOS heuristic; not evidence of institutional activity.", "STRUCTURE_INFERRED")
        elif structure == "FAILED_BREAKOUT_UP":
            _add_signal(signals, "FAILED_BREAKOUT_UP", timeframe, 62, "INFERRED", f"{timeframe} moved above range and returned inside.", "STRUCTURE_INFERRED")
            _add_signal(signals, "POSSIBLE_LIQUIDITY_SWEEP_ABOVE", timeframe, 60, "INFERRED", "BTC traversed a likely liquidity area and returned to range.", "STRUCTURE_INFERRED")
        elif structure == "FAILED_BREAKOUT_DOWN":
            _add_signal(signals, "FAILED_BREAKOUT_DOWN", timeframe, 62, "INFERRED", f"{timeframe} moved below range and returned inside.", "STRUCTURE_INFERRED")
            _add_signal(signals, "POSSIBLE_LIQUIDITY_SWEEP_BELOW", timeframe, 60, "INFERRED", "BTC traversed a likely liquidity area and returned to range.", "STRUCTURE_INFERRED")

    if snapshot.liquidity.visible_above == "ORDER_BOOK_VISIBLE":
        _add_signal(signals, "LIQUIDITY_CLUSTER_ABOVE", "live", 55, "OBSERVED", "Visible ask liquidity cluster is present above price.", "ORDER_BOOK_VISIBLE")
    if snapshot.liquidity.visible_below == "ORDER_BOOK_VISIBLE":
        _add_signal(signals, "LIQUIDITY_CLUSTER_BELOW", "live", 55, "OBSERVED", "Visible bid liquidity cluster is present below price.", "ORDER_BOOK_VISIBLE")
    if snapshot.liquidity.equal_highs is not None:
        _add_signal(signals, "EQUAL_HIGHS_LIQUIDITY", "1h", 50, "INFERRED", "Recent equal highs may concentrate liquidity; this is inferred.", "STRUCTURE_INFERRED")
    if snapshot.liquidity.equal_lows is not None:
        _add_signal(signals, "EQUAL_LOWS_LIQUIDITY", "1h", 50, "INFERRED", "Recent equal lows may concentrate liquidity; this is inferred.", "STRUCTURE_INFERRED")

    if direction == "UP" and snapshot.oi_change_1h is not None:
        if snapshot.oi_change_1h >= 2:
            _add_signal(signals, "MOMENTUM_WITH_LEVERAGE_BUILDUP", "1h", 76, "INFERRED", "Price up with OI rising; consistent with new leveraged positioning.", "BINANCE_OI")
        elif snapshot.oi_change_1h <= -2:
            _add_signal(signals, "POSSIBLE_SHORT_COVERING", "1h", 72, "INFERRED", "Price up with OI falling; consistent with short-covering/squeeze dynamics.", "BINANCE_OI")
    elif direction == "DOWN" and snapshot.oi_change_1h is not None:
        if snapshot.oi_change_1h <= -2:
            _add_signal(signals, "DELEVERAGING_STYLE_MOVE", "1h", 78, "INFERRED", "Price down with OI falling; consistent with deleveraging/long liquidation dynamics.", "BINANCE_OI")
        elif snapshot.oi_change_1h >= 2:
            _add_signal(signals, "NEW_BEARISH_POSITIONING", "1h", 70, "INFERRED", "Price down with OI rising; consistent with new bearish positioning.", "BINANCE_OI")
    elif direction == "FLAT" and snapshot.oi_change_1h is not None and snapshot.oi_change_1h >= 3:
        _add_signal(signals, "LEVERAGE_BUILDING_COMPRESSION", "1h", 68, "INFERRED", "OI rises while price remains compressed.", "BINANCE_OI")

    if direction in {"UP", "DOWN"} and snapshot.volume_ratio_1h is not None and snapshot.volume_ratio_1h < 1.2:
        _add_signal(signals, "VOLUME_DIVERGENCE", "1h", 45, "CALCULATED", "Fast price move lacks clear volume expansion.", "BINANCE_KLINES")

    liquidity_score = _score_liquidity(snapshot)
    smc_score = _score_smc(snapshot, signals)
    independent = {
        "price": any(signal.name.startswith("PRICE_ACCELERATION") for signal in signals),
        "volume": any(signal.name.startswith("VOLUME") for signal in signals),
        "volatility": any(signal.name == "VOLATILITY_EXPANSION" for signal in signals),
        "oi": any(signal.source == "BINANCE_OI" for signal in signals),
        "structure": any(signal.source == "STRUCTURE_INFERRED" for signal in signals),
        "liquidity": any(signal.source == "ORDER_BOOK_VISIBLE" for signal in signals),
    }
    independent_count = sum(1 for active in independent.values() if active)

    derivatives_score = max([signal.strength for signal in signals if signal.source == "BINANCE_OI"] or [0])
    volume_score = max([signal.strength for signal in signals if signal.name.startswith("VOLUME")] or [0])
    volatility_score = max([signal.strength for signal in signals if signal.name == "VOLATILITY_EXPANSION"] or [0])
    confluence = (
        move_score * 0.36
        + volume_score * 0.14
        + volatility_score * 0.10
        + derivatives_score * 0.16
        + liquidity_score * 0.10
        + smc_score * 0.08
    )

    if independent["price"] and independent["volume"] and independent["oi"]:
        confluence += 6

    if independent_count < 2 and move_score < 92:
        confluence = min(confluence, 54)
    if independent_count < 3 and move_score < 88:
        confluence = min(confluence, 72)
    if not _fresh_enough(snapshot):
        confluence = min(confluence, 40)
    if snapshot.status == "DEGRADED":
        confluence = min(confluence, 88)

    confluence = _clamp(confluence)
    materiality = _materiality(confluence)
    decision = "INTRADAY_CANDIDATE" if confluence >= INTRADAY_MIN_CONFLUENCE and materiality in {"INTRADAY_HIGH", "INTRADAY_CRITICAL"} else "NO_INTRADAY_ALERT"

    if direction == "UP" and derivatives_score:
        reading = "El movimiento es compatible con momentum de corto plazo y apertura/cierre de apalancamiento, no con una causa demostrada."
    elif direction == "DOWN" and derivatives_score:
        reading = "La combinación es compatible con presión de desapalancamiento de corto plazo, sin probar causalidad única."
    elif move_score >= 70:
        reading = "BTC muestra un movimiento intradía anormal; Radar no identifica todavía un catalizador confirmado."
    else:
        reading = "No hay confluencia intradía suficiente."

    invalidation = "La lectura pierde fuerza si BTC vuelve rápidamente al rango y volumen/OI dejan de confirmar el movimiento."

    return BtcIntradayState(
        snapshot=snapshot,
        signals=signals,
        move_abnormality_score=move_score,
        liquidity_importance_score=liquidity_score,
        smc_confluence_score=smc_score,
        intraday_confluence_score=confluence,
        intraday_materiality=materiality,
        decision=decision,
        reading=reading,
        invalidation=invalidation,
        status=snapshot.status,
        data_available=dict(snapshot.data_available),
    )


def attach_intraday_catalyst(state, news_items):
    if state is None:
        return state

    relevant_terms = [
        "bitcoin",
        "btc",
        "sec",
        "etf",
        "hack",
        "exchange",
        "binance",
        "coinbase",
        "stablecoin",
        "fed",
        "trump",
        "tariff",
        "iran",
        "oil",
        "regulation",
    ]
    for item in news_items or []:
        text = f"{item.title} {item.summary} {item.content}".lower()
        if not any(term in text for term in relevant_terms):
            continue
        item = apply_source_metadata(item)
        if item.source_type in {"PRIMARY", "HIGH_RELIABILITY"}:
            state.catalyst_status = "CONFIRMED_CATALYST"
            state.catalyst_source = item.source
            state.catalyst_confidence = "Media"
            state.intraday_news_relevance = 75
            return state
        if item.source_type in {"FAST", "COMMUNITY"}:
            state.catalyst_status = "POSSIBLE_CATALYST"
            state.catalyst_source = item.source
            state.catalyst_confidence = "Baja"
            state.intraday_news_relevance = max(state.intraday_news_relevance, 45)
            return state
    state.catalyst_status = "NO_CLEAR_CATALYST"
    return state


def _fmt(value, suffix=""):
    if value is None:
        return "UNKNOWN"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def intraday_state_to_news_item(state):
    if state is None or state.decision != "INTRADAY_CANDIDATE":
        return None

    snapshot = state.snapshot
    direction = _direction(snapshot)
    direction_text = "acelera al alza" if direction == "UP" else "cae con fuerza" if direction == "DOWN" else "se mueve con fuerza"
    materiality = "CRITICAL" if state.intraday_materiality == "INTRADAY_CRITICAL" else "HIGH"
    impact = max(INTRADAY_MIN_CONFLUENCE, state.intraday_confluence_score)
    signal_names = [signal.name for signal in state.signals]

    content = "\n".join(
        [
            f"BTC {direction_text} en el horizonte intradía.",
            f"Movimiento: 15m={_fmt(snapshot.price_change_15m, '%')}, 1h={_fmt(snapshot.price_change_1h, '%')}, 4h={_fmt(snapshot.price_change_4h, '%')}.",
            f"Volumen: ratio 1h={_fmt(snapshot.volume_ratio_1h)}; volatilidad 1h={_fmt(snapshot.realized_volatility_1h, '%')}.",
            f"Derivados: OI 1h={_fmt(snapshot.oi_change_1h, '%')}; funding={_fmt(snapshot.funding_rate)} ({snapshot.funding_regime}).",
            f"Estructura: 15m={snapshot.structure_15m}, 1h={snapshot.structure_1h}, 4h={snapshot.structure_4h}, 1d={snapshot.structure_1d}.",
            f"Liquidez visible: above={snapshot.liquidity.visible_above}, below={snapshot.liquidity.visible_below}.",
            f"Catalizador: {state.catalyst_status}; fuente={state.catalyst_source or 'ninguna identificada'}.",
            f"Lectura: {state.reading}",
            "Pregunta clave: ¿la ruptura tendrá continuidad o volverá rápidamente al rango?",
            "Escenario A: si volumen y OI siguen acompañando, la ruptura gana calidad.",
            "Escenario B: si BTC atraviesa la zona de liquidez y vuelve al rango, aumentaría la lectura de posible barrida.",
            "Escenario C: si desaparece el follow-through, el movimiento pierde calidad intradía.",
            f"Invalidación: {state.invalidation}",
            "No es una recomendación operativa ni una predicción de precio.",
            "Signals:",
            *[f"- {signal.name} ({signal.timeframe}, {signal.certainty}): {signal.evidence}" for signal in state.signals[:10]],
        ]
    )

    item = NewsItem(
        title=f"BTC intradía: {direction_text} con confluencia de mercado",
        summary=state.reading,
        content=content,
        link=f"market-state:btc-intraday:{direction}:{snapshot.structure_1h}:{snapshot.timestamp[:13]}",
        published=snapshot.timestamp,
        source="MARKET_STATE",
        category="BTC Intraday",
        event_type="BTC_INTRADAY_MOVE",
        affected_assets=["BTC"],
        asset_class="CRYPTO",
        market_impact=impact,
        score=impact,
        materiality=materiality,
        confidence="Media",
        verification_status="PRELIMINARY",
        crypto_asset="BTC",
        impact_horizon="INTRADAY",
        mechanism="price action/volume/open interest/liquidity -> short-term BTC volatility",
        market_signals=signal_names,
        confluence_score=state.intraday_confluence_score,
        evidence_level="CALCULATED",
        mechanism_of_impact="DIRECT",
        editorial_quality=70,
    )
    item.intelligence_summary = {
        "INTRADAY_CONFLUENCE": state.intraday_confluence_score,
        "MOVE_ABNORMALITY": state.move_abnormality_score,
        "LIQUIDITY": state.liquidity_importance_score,
        "SMC": state.smc_confluence_score,
        "CATALYST": state.catalyst_status,
        "MARKET_DATA_AGE_MINUTES": snapshot.market_data_age_minutes,
    }
    return item
