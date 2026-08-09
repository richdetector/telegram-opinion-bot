import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import BLOCKWORKS_API_KEY


BINANCE_FAPI_BASE_URL = "https://fapi.binance.com"
BLOCKWORKS_API_BASE_URL = "https://api.blockworks.com"
BTC_SYMBOL = "BTCUSDT"


@dataclass
class BtcMarketSnapshot:
    price: float | None = None
    price_change_1h: float | None = None
    price_change_24h: float | None = None
    volume_24h: float | None = None
    volume_zscore: float | None = None
    open_interest: float | None = None
    open_interest_change: float | None = None
    funding_rate: float | None = None
    funding_extreme: str = "UNKNOWN"
    liquidations_long: float | None = None
    liquidations_short: float | None = None
    liquidations_total: float | None = None
    liquidations_long_1h: float | None = None
    liquidations_short_1h: float | None = None
    liquidations_total_1h: float | None = None
    liquidations_long_4h: float | None = None
    liquidations_short_4h: float | None = None
    liquidations_total_4h: float | None = None
    liquidations_long_24h: float | None = None
    liquidations_short_24h: float | None = None
    liquidations_total_24h: float | None = None
    liquidations_status: str = "UNKNOWN"
    volatility: float | None = None
    volatility_zscore: float | None = None
    timestamp: str = ""
    provider: str = "Binance USD-M Futures"
    errors: list[str] = field(default_factory=list)


@dataclass
class BtcEtfFlowSnapshot:
    btc_etf_net_flow: float | None = None
    btc_etf_inflow: float | None = None
    btc_etf_outflow: float | None = None
    btc_etf_flow_3d_avg: float | None = None
    btc_etf_flow_5d_avg: float | None = None
    btc_etf_flow_7d_avg: float | None = None
    btc_etf_flow_regime: str = "UNKNOWN"
    btc_etf_flow_zscore: float | None = None
    btc_etf_flow_streak: int | None = None
    btc_etf_flow_timestamp: str = ""
    provider: str = "Blockworks ETF flows"
    errors: list[str] = field(default_factory=list)


def _safe_float(value):
    if value in {None, ""}:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return statistics.fmean(values)


def _stdev(values):
    values = [value for value in values if value is not None]
    if len(values) < 2:
        return None
    return statistics.pstdev(values)


def _zscore(value, values):
    avg = _mean(values)
    sd = _stdev(values)

    if value is None or avg is None or not sd:
        return None

    return (value - avg) / sd


def _pct_change(current, previous):
    if current is None or previous in {None, 0}:
        return None

    return ((current - previous) / previous) * 100


class BinanceMarketDataClient:

    def __init__(self, base_url=BINANCE_FAPI_BASE_URL, timeout=10):
        self.base_url = base_url
        self.timeout = timeout

    def get_json(self, path, params=None):
        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{self.base_url}{path}{query}",
            headers={
                "User-Agent": "RadarMarketIntelligence/1.0",
            },
        )

        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def ticker_24h(self, symbol=BTC_SYMBOL):
        return self.get_json(
            "/fapi/v1/ticker/24hr",
            {"symbol": symbol},
        )

    def klines(self, symbol=BTC_SYMBOL, interval="1h", limit=48):
        return self.get_json(
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            },
        )

    def open_interest_hist(self, symbol=BTC_SYMBOL, period="1h", limit=48):
        return self.get_json(
            "/futures/data/openInterestHist",
            {
                "symbol": symbol,
                "period": period,
                "limit": limit,
            },
        )

    def funding_rate(self, symbol=BTC_SYMBOL, limit=24):
        return self.get_json(
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol,
                "limit": limit,
            },
        )

    def force_orders(self, symbol=BTC_SYMBOL, limit=100):
        return self.get_json(
            "/fapi/v1/allForceOrders",
            {
                "symbol": symbol,
                "limit": limit,
            },
        )


class BlockworksEtfFlowClient:

    def __init__(
        self,
        api_key=BLOCKWORKS_API_KEY,
        base_url=BLOCKWORKS_API_BASE_URL,
        timeout=10,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

    def get_json(self, path, params=None):
        if not self.api_key:
            raise RuntimeError("BLOCKWORKS_API_KEY missing")

        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{self.base_url}{path}{query}",
            headers={
                "User-Agent": "RadarMarketIntelligence/1.0",
                "x-api-key": self.api_key,
            },
        )

        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def btc_etf_flows(self, limit_days=30):
        data = self.get_json(
            "/v1/metrics/etf-flows-total-usd",
            {"project": "bitcoin"},
        )

        rows = data.get("bitcoin", [])
        return rows[-limit_days:] if limit_days else rows


def _kline_close(kline):
    return _safe_float(kline[4])


def _kline_volume(kline):
    return _safe_float(kline[5])


def _kline_volatility(kline):
    high = _safe_float(kline[2])
    low = _safe_float(kline[3])
    close = _safe_float(kline[4])

    if high is None or low is None or close in {None, 0}:
        return None

    return ((high - low) / close) * 100


def fetch_btc_market_snapshot(client=None):
    client = client or BinanceMarketDataClient()
    snapshot = BtcMarketSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    try:
        ticker = client.ticker_24h()
        snapshot.price = _safe_float(ticker.get("lastPrice"))
        snapshot.price_change_24h = _safe_float(ticker.get("priceChangePercent"))
        snapshot.volume_24h = _safe_float(ticker.get("quoteVolume"))
    except Exception as exc:
        snapshot.errors.append(f"ticker_24h:{type(exc).__name__}")

    try:
        klines = client.klines(limit=48)
        closes = [_kline_close(kline) for kline in klines]
        volumes = [_kline_volume(kline) for kline in klines]
        volatilities = [_kline_volatility(kline) for kline in klines]

        if len(closes) >= 2:
            snapshot.price_change_1h = _pct_change(closes[-1], closes[-2])

        if volumes:
            snapshot.volume_zscore = _zscore(volumes[-1], volumes[:-1])

        if volatilities:
            snapshot.volatility = volatilities[-1]
            snapshot.volatility_zscore = _zscore(volatilities[-1], volatilities[:-1])
    except Exception as exc:
        snapshot.errors.append(f"klines:{type(exc).__name__}")

    try:
        oi_history = client.open_interest_hist(limit=48)
        oi_values = [
            _safe_float(row.get("sumOpenInterestValue") or row.get("sumOpenInterest"))
            for row in oi_history
        ]
        if oi_values:
            snapshot.open_interest = oi_values[-1]
        if len(oi_values) >= 7:
            baseline = _mean(oi_values[-7:-1])
            snapshot.open_interest_change = _pct_change(oi_values[-1], baseline)
    except Exception as exc:
        snapshot.errors.append(f"open_interest:{type(exc).__name__}")

    try:
        funding = client.funding_rate(limit=24)
        funding_values = [_safe_float(row.get("fundingRate")) for row in funding]
        if funding_values:
            snapshot.funding_rate = funding_values[-1]
            zscore = _zscore(funding_values[-1], funding_values[:-1])
            if zscore is not None and zscore >= 2:
                snapshot.funding_extreme = "POSITIVE"
            elif zscore is not None and zscore <= -2:
                snapshot.funding_extreme = "NEGATIVE"
            else:
                snapshot.funding_extreme = "NORMAL"
    except Exception as exc:
        snapshot.errors.append(f"funding:{type(exc).__name__}")

    snapshot.liquidations_status = "UNAVAILABLE_PUBLIC_REST"

    return snapshot


def _flow_streak(values):
    if not values:
        return None

    latest_sign = 1 if values[-1] > 0 else -1 if values[-1] < 0 else 0
    if latest_sign == 0:
        return 0

    streak = 0
    for value in reversed(values):
        sign = 1 if value > 0 else -1 if value < 0 else 0
        if sign != latest_sign:
            break
        streak += latest_sign

    return streak


def normalize_btc_etf_flows(rows):
    snapshot = BtcEtfFlowSnapshot(
        btc_etf_flow_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    values = [
        _safe_float(row.get("value"))
        for row in rows or []
        if _safe_float(row.get("value")) is not None
    ]

    if not values:
        snapshot.errors.append("etf_flows:NO_DATA")
        return snapshot

    latest = values[-1]
    snapshot.btc_etf_net_flow = latest
    snapshot.btc_etf_inflow = latest if latest > 0 else 0.0
    snapshot.btc_etf_outflow = abs(latest) if latest < 0 else 0.0
    snapshot.btc_etf_flow_3d_avg = _mean(values[-3:])
    snapshot.btc_etf_flow_5d_avg = _mean(values[-5:])
    snapshot.btc_etf_flow_7d_avg = _mean(values[-7:])
    snapshot.btc_etf_flow_zscore = _zscore(latest, values[:-1])
    snapshot.btc_etf_flow_streak = _flow_streak(values)

    if snapshot.btc_etf_flow_streak is not None and snapshot.btc_etf_flow_streak >= 5:
        snapshot.btc_etf_flow_regime = "POSITIVE"
    elif snapshot.btc_etf_flow_streak is not None and snapshot.btc_etf_flow_streak <= -5:
        snapshot.btc_etf_flow_regime = "NEGATIVE"
    else:
        snapshot.btc_etf_flow_regime = "NEUTRAL"

    return snapshot


def fetch_btc_etf_flow_snapshot(client=None):
    client = client or BlockworksEtfFlowClient()

    try:
        rows = client.btc_etf_flows(limit_days=30)
        return normalize_btc_etf_flows(rows)
    except Exception as exc:
        snapshot = BtcEtfFlowSnapshot(
            btc_etf_flow_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        snapshot.errors.append(f"etf_flows:{type(exc).__name__}")
        return snapshot
