import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import BLOCKWORKS_API_KEY, GLASSNODE_API_KEY


BINANCE_FAPI_BASE_URL = "https://fapi.binance.com"
BLOCKWORKS_API_BASE_URL = "https://api.blockworks.com"
GLASSNODE_API_BASE_URL = "https://api.glassnode.com"
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
    status: str = "UNKNOWN"
    errors: list[str] = field(default_factory=list)


@dataclass
class LargeBtcTransfer:
    amount_btc: float | None = None
    from_label: str = ""
    to_label: str = ""
    classification: str = "UNKNOWN"
    certainty: str = "OBSERVED"


@dataclass
class BtcOnchainSnapshot:
    btc_exchange_inflow: float | None = None
    btc_exchange_outflow: float | None = None
    btc_exchange_netflow: float | None = None
    btc_exchange_reserves: float | None = None
    btc_exchange_inflow_zscore: float | None = None
    btc_exchange_outflow_zscore: float | None = None
    btc_exchange_netflow_zscore: float | None = None
    btc_exchange_reserve_change_1d: float | None = None
    btc_exchange_reserve_change_7d: float | None = None
    btc_large_transfer_count: int | None = None
    btc_large_transfer_volume: float | None = None
    btc_whale_activity: str = "UNKNOWN"
    btc_miner_to_exchange: float | None = None
    btc_miner_to_exchange_zscore: float | None = None
    btc_onchain_timestamp: str = ""
    provider: str = "Glassnode"
    status: str = "UNKNOWN"
    btc_tx_count: float | None = None
    btc_active_addresses: float | None = None
    btc_hash_rate: float | None = None
    coin_metrics_status: str = "UNKNOWN"
    large_transfers: list[LargeBtcTransfer] = field(default_factory=list)
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

    def depth(self, symbol=BTC_SYMBOL, limit=1000):
        return self.get_json(
            "/fapi/v1/depth",
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


class GlassnodeOnchainClient:

    def __init__(
        self,
        api_key=GLASSNODE_API_KEY,
        base_url=GLASSNODE_API_BASE_URL,
        timeout=10,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

    def metric(self, path, days=30, interval="24h"):
        if not self.api_key:
            raise RuntimeError("GLASSNODE_API_KEY missing")

        request = Request(
            f"{self.base_url}/v1/metrics{path}?{urlencode({'a': 'BTC', 'i': interval, 'api_key': self.api_key})}",
            headers={"User-Agent": "RadarMarketIntelligence/1.0"},
        )

        with urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

        return data[-days:] if days else data


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

    snapshot.liquidations_status = "UNAVAILABLE_FREE_SOURCE"

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


def _latest_metric_value(rows):
    values = [
        _safe_float(row.get("v"))
        for row in rows or []
        if _safe_float(row.get("v")) is not None
    ]
    latest = values[-1] if values else None
    return latest, values


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

    if isinstance(client, BlockworksEtfFlowClient) and not client.api_key:
        return BtcEtfFlowSnapshot(
            btc_etf_flow_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            status="NOT_CONFIGURED",
        )

    try:
        rows = client.btc_etf_flows(limit_days=30)
        snapshot = normalize_btc_etf_flows(rows)
        snapshot.status = "OK" if not snapshot.errors else "API_ERROR"
        return snapshot
    except Exception as exc:
        snapshot = BtcEtfFlowSnapshot(
            btc_etf_flow_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        snapshot.status = "API_ERROR"
        snapshot.errors.append(f"etf_flows:{type(exc).__name__}")
        return snapshot


def classify_large_transfer(transfer):
    from_label = (transfer.from_label or "").lower()
    to_label = (transfer.to_label or "").lower()

    from_exchange = "exchange" in from_label or any(
        name in from_label
        for name in ["binance", "coinbase", "kraken", "okx", "bybit"]
    )
    to_exchange = "exchange" in to_label or any(
        name in to_label
        for name in ["binance", "coinbase", "kraken", "okx", "bybit"]
    )

    if from_exchange and to_exchange:
        return "INTERNAL_TRANSFER"
    if to_exchange:
        return "EXCHANGE_INFLOW"
    if from_exchange:
        return "EXCHANGE_OUTFLOW"
    if "custody" in from_label or "custody" in to_label:
        return "CUSTODY"
    if "miner" in from_label or "miner" in to_label:
        return "MINER"
    if "institution" in from_label or "institution" in to_label:
        return "INSTITUTIONAL"
    if "otc" in from_label or "otc" in to_label:
        return "OTC_POSSIBLE"

    return "UNKNOWN"


def normalize_btc_onchain_snapshot(metrics, large_transfers=None):
    snapshot = BtcOnchainSnapshot(
        btc_onchain_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    inflow, inflows = _latest_metric_value(metrics.get("exchange_inflow"))
    outflow, outflows = _latest_metric_value(metrics.get("exchange_outflow"))
    netflow, netflows = _latest_metric_value(metrics.get("exchange_netflow"))
    reserves, reserves_series = _latest_metric_value(metrics.get("exchange_reserves"))
    miner, miners = _latest_metric_value(metrics.get("miner_to_exchange"))
    whale_in, whale_ins = _latest_metric_value(metrics.get("whale_to_exchange"))
    whale_out, whale_outs = _latest_metric_value(metrics.get("exchange_to_whale"))

    snapshot.btc_exchange_inflow = inflow
    snapshot.btc_exchange_outflow = outflow
    snapshot.btc_exchange_netflow = netflow
    snapshot.btc_exchange_reserves = reserves
    snapshot.btc_exchange_inflow_zscore = _zscore(inflow, inflows[:-1])
    snapshot.btc_exchange_outflow_zscore = _zscore(outflow, outflows[:-1])
    snapshot.btc_exchange_netflow_zscore = _zscore(netflow, netflows[:-1])
    snapshot.btc_miner_to_exchange = miner
    snapshot.btc_miner_to_exchange_zscore = _zscore(miner, miners[:-1])

    if reserves is not None and len(reserves_series) >= 2:
        snapshot.btc_exchange_reserve_change_1d = _pct_change(reserves, reserves_series[-2])
    if reserves is not None and len(reserves_series) >= 8:
        snapshot.btc_exchange_reserve_change_7d = _pct_change(reserves, reserves_series[-8])

    whale_values = [
        value
        for value in [whale_in, whale_out]
        if value is not None
    ]
    if whale_values:
        snapshot.btc_large_transfer_volume = sum(whale_values)
        snapshot.btc_whale_activity = "OBSERVED"

    transfers = large_transfers or []
    for transfer in transfers:
        transfer.classification = classify_large_transfer(transfer)
        snapshot.large_transfers.append(transfer)

    if transfers:
        snapshot.btc_large_transfer_count = len(transfers)
        transfer_volume = sum(
            transfer.amount_btc or 0
            for transfer in transfers
        )
        snapshot.btc_large_transfer_volume = (
            (snapshot.btc_large_transfer_volume or 0)
            + transfer_volume
        )
        snapshot.btc_whale_activity = "OBSERVED"

    if not any(
        value is not None
        for value in [
            inflow,
            outflow,
            netflow,
            reserves,
            miner,
            snapshot.btc_large_transfer_volume,
        ]
    ):
        snapshot.errors.append("onchain:NO_DATA")

    return snapshot


def fetch_btc_onchain_snapshot(client=None):
    client = client or GlassnodeOnchainClient()

    try:
        if isinstance(client, GlassnodeOnchainClient) and not client.api_key:
            snapshot = BtcOnchainSnapshot(
                btc_onchain_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                status="NOT_CONFIGURED",
            )
        else:
            metrics = {
                "exchange_inflow": client.metric("/transactions/transfers_volume_to_exchanges_sum"),
                "exchange_outflow": client.metric("/transactions/transfers_volume_from_exchanges_sum"),
                "exchange_netflow": client.metric("/transactions/transfers_volume_exchanges_net"),
                "exchange_reserves": client.metric("/distribution/balance_exchanges"),
                "miner_to_exchange": client.metric("/transactions/transfers_volume_miners_to_exchanges"),
                "whale_to_exchange": client.metric("/transactions/transfers_volume_whales_to_exchanges_sum"),
                "exchange_to_whale": client.metric("/transactions/transfers_volume_exchanges_to_whales_sum"),
            }
            snapshot = normalize_btc_onchain_snapshot(metrics)
            snapshot.status = "OK" if not snapshot.errors else "API_ERROR"

        coin_metrics = fetch_coin_metrics_context()
        snapshot.btc_tx_count = coin_metrics.get("TxCnt")
        snapshot.btc_active_addresses = coin_metrics.get("AdrActCnt")
        snapshot.btc_hash_rate = coin_metrics.get("HashRate")
        snapshot.coin_metrics_status = coin_metrics.get("status", "UNKNOWN")
        return snapshot
    except Exception as exc:
        snapshot = BtcOnchainSnapshot(
            btc_onchain_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        snapshot.status = "API_ERROR"
        snapshot.errors.append(f"onchain:{type(exc).__name__}")
        return snapshot


class CoinMetricsCommunityClient:

    def __init__(self, base_url="https://community-api.coinmetrics.io/v4", timeout=10):
        self.base_url = base_url
        self.timeout = timeout

    def asset_metrics(self, metrics="TxCnt,AdrActCnt,HashRate", limit_per_asset=2):
        request = Request(
            f"{self.base_url}/timeseries/asset-metrics?{urlencode({'assets': 'btc', 'metrics': metrics, 'frequency': '1d', 'page_size': limit_per_asset})}",
            headers={"User-Agent": "RadarMarketIntelligence/1.0"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def fetch_coin_metrics_context(client=None):
    client = client or CoinMetricsCommunityClient()
    try:
        payload = client.asset_metrics()
        rows = payload.get("data", [])
        latest = rows[-1] if rows else {}
        return {
            "TxCnt": _safe_float(latest.get("TxCnt")),
            "AdrActCnt": _safe_float(latest.get("AdrActCnt")),
            "HashRate": _safe_float(latest.get("HashRate")),
            "status": "OK" if latest else "UNAVAILABLE_FREE_SOURCE",
        }
    except Exception:
        return {"status": "API_ERROR"}
