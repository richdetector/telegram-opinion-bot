import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from config import MARKET_DATA_TIMEOUT_SECONDS, SANTIMENT_API_KEY


SANTIMENT_API_URL = "https://api.santiment.net/graphql"


@dataclass
class SentimentSignal:
    name: str
    strength: int
    certainty: str
    evidence: str
    timestamp: str = ""
    source: str = "SENTIMENT_ENGINE"


@dataclass
class BtcSentimentSnapshot:
    retail_sentiment: str = "UNKNOWN"
    retail_sentiment_score: float | None = None
    retail_attention: str = "UNKNOWN"
    retail_attention_score: float | None = None
    market_sentiment: str = "UNKNOWN"
    crowding_state: str = "UNKNOWN"
    positioning_bias: str = "UNKNOWN"
    institutional_flow_proxy: str = "UNKNOWN"
    narrative_state: str = "UNKNOWN"
    sentiment_divergence: str = "UNKNOWN"
    sentiment_timestamp: str = ""
    provider: str = "Sentiment/positioning engine"
    errors: list[str] = field(default_factory=list)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clamp_strength(value):
    return max(0, min(100, int(value)))


def _add_signal(signals, name, strength, certainty, evidence, timestamp="", source="SENTIMENT_ENGINE"):
    signals.append(
        SentimentSignal(
            name=name,
            strength=_clamp_strength(strength),
            certainty=certainty,
            evidence=evidence,
            timestamp=timestamp,
            source=source,
        )
    )


def _names(signals):
    return {signal.name for signal in signals}


def _has_any(signal_names, candidates):
    return bool(signal_names.intersection(candidates))


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
    return sum(values) / len(values)


class SantimentSentimentClient:
    """Optional Santiment social metrics client.

    Santiment is GraphQL-only. This first layer treats Santiment as an
    optional source and degrades to UNKNOWN if metric access is unavailable.
    """

    def __init__(
        self,
        api_key=SANTIMENT_API_KEY,
        url=SANTIMENT_API_URL,
        timeout=MARKET_DATA_TIMEOUT_SECONDS,
    ):
        self.api_key = api_key
        self.url = url
        self.timeout = timeout

    def query(self, query):
        if not self.api_key:
            raise RuntimeError("SANTIMENT_API_KEY missing")

        body = json.dumps({"query": query}).encode("utf-8")
        request = Request(
            self.url,
            data=body,
            headers={
                "Authorization": f"Apikey {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "RadarMarketIntelligence/1.0",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if payload.get("errors"):
            raise RuntimeError("Santiment GraphQL error")

        return payload.get("data", {})

    def btc_social_volume(self):
        data = self.query(
            """
            {
              getMetric(metric: "social_volume_total") {
                timeseriesDataJson(
                  slug: "bitcoin"
                  from: "utc_now-14d"
                  to: "utc_now"
                  interval: "1d"
                )
              }
            }
            """
        )
        metric = data.get("getMetric") or {}
        return metric.get("timeseriesDataJson") or []


def fetch_btc_sentiment_snapshot(client=None):
    snapshot = BtcSentimentSnapshot(sentiment_timestamp=_now())
    client = client or SantimentSentimentClient()

    if isinstance(client, BtcSentimentSnapshot):
        return client

    try:
        rows = client.btc_social_volume()
        values = []
        for row in rows or []:
            if isinstance(row, dict):
                values.append(_safe_float(row.get("value") or row.get("v")))
        values = [value for value in values if value is not None]

        if not values:
            snapshot.errors.append("sentiment:NO_DATA")
            return snapshot

        latest = values[-1]
        baseline = _mean(values[:-1])
        snapshot.retail_attention_score = latest
        if baseline and latest >= baseline * 2.5:
            snapshot.retail_attention = "SPIKE"
        elif baseline:
            snapshot.retail_attention = "NORMAL"

    except Exception as exc:
        snapshot.errors.append(f"sentiment:{type(exc).__name__}")

    return snapshot


def sentiment_from_reddit_status(status):
    snapshot = BtcSentimentSnapshot(
        sentiment_timestamp=_now(),
        provider="Reddit Data API",
    )

    if status is None:
        snapshot.errors.append("reddit:UNKNOWN")
        return snapshot

    if status.status != "OK":
        snapshot.errors.append(f"reddit:{status.status}")

    attention = (status.attention or "UNKNOWN").upper()
    sentiment = (status.sentiment or "UNKNOWN").upper()

    if attention in {"LOW", "ELEVATED", "EXTREME"}:
        snapshot.retail_attention = "SPIKE" if attention in {"ELEVATED", "EXTREME"} else "NORMAL"
        snapshot.retail_attention_score = {
            "LOW": 30,
            "ELEVATED": 65,
            "EXTREME": 90,
        }[attention]

    if sentiment in {"BULLISH", "BEARISH", "EUPHORIC", "PANIC"}:
        snapshot.retail_sentiment = "EUPHORIA" if sentiment == "EUPHORIC" else sentiment
        snapshot.retail_sentiment_score = {
            "BULLISH": 65,
            "BEARISH": 35,
            "EUPHORIC": 90,
            "PANIC": 10,
        }[sentiment]
    elif status.posts_accepted:
        snapshot.retail_sentiment = "UNKNOWN"

    if status.top_narratives:
        snapshot.narrative_state = ", ".join(status.top_narratives[:3])

    return snapshot


def _retail_signal(snapshot, signals):
    sentiment = (snapshot.retail_sentiment or "UNKNOWN").upper()
    score = snapshot.retail_sentiment_score
    timestamp = snapshot.sentiment_timestamp

    if sentiment in {"EUPHORIA", "EXTREME_BULLISH"} or (score is not None and score >= 85):
        _add_signal(
            signals,
            "RETAIL_EUPHORIA",
            score if score is not None else 75,
            "OBSERVED",
            "Retail sentiment is euphoric across aggregated inputs.",
            timestamp,
        )
    elif sentiment in {"PANIC", "CAPITULATION", "EXTREME_BEARISH"} or (score is not None and score <= 15):
        _add_signal(
            signals,
            "RETAIL_PANIC",
            100 - score if score is not None else 75,
            "OBSERVED",
            "Retail sentiment is panicked across aggregated inputs.",
            timestamp,
        )
    elif sentiment in {"BULLISH", "BEARISH"}:
        _add_signal(
            signals,
            f"RETAIL_{sentiment}",
            45,
            "OBSERVED",
            f"Retail sentiment is {sentiment.lower()} but not extreme.",
            timestamp,
        )

    attention = (snapshot.retail_attention or "UNKNOWN").upper()
    attention_score = snapshot.retail_attention_score
    if attention == "SPIKE":
        signal_name = "REDDIT_ATTENTION_EXTREME" if (
            snapshot.provider == "Reddit Data API"
            and attention_score is not None
            and attention_score >= 85
        ) else "REDDIT_ATTENTION_ELEVATED" if snapshot.provider == "Reddit Data API" else "RETAIL_ATTENTION_SPIKE"
        _add_signal(
            signals,
            signal_name,
            attention_score if attention_score is not None and attention_score <= 100 else 65,
            "CALCULATED",
            "Retail/social attention is elevated versus its recent baseline.",
            timestamp,
        )
    elif attention == "NORMAL" and snapshot.provider == "Reddit Data API":
        _add_signal(
            signals,
            "REDDIT_ATTENTION_LOW",
            25,
            "CALCULATED",
            "Reddit attention is present but not elevated across accepted posts.",
            timestamp,
        )


def _derive_positioning(snapshot, market_snapshot, signals):
    timestamp = snapshot.sentiment_timestamp

    funding_positive = market_snapshot and (
        market_snapshot.funding_extreme == "POSITIVE"
        or (
            market_snapshot.funding_rate is not None
            and market_snapshot.funding_rate >= 0.001
        )
    )
    funding_negative = market_snapshot and (
        market_snapshot.funding_extreme == "NEGATIVE"
        or (
            market_snapshot.funding_rate is not None
            and market_snapshot.funding_rate <= -0.001
        )
    )
    oi_rising = market_snapshot and market_snapshot.open_interest_change is not None and market_snapshot.open_interest_change >= 8
    oi_falling = market_snapshot and market_snapshot.open_interest_change is not None and market_snapshot.open_interest_change <= -8
    price_rising = market_snapshot and market_snapshot.price_change_24h is not None and market_snapshot.price_change_24h > 2
    price_falling = market_snapshot and market_snapshot.price_change_24h is not None and market_snapshot.price_change_24h < -2

    retail = (snapshot.retail_sentiment or "UNKNOWN").upper()

    if oi_rising and funding_positive:
        snapshot.positioning_bias = "LONG_BIASED"
        _add_signal(
            signals,
            "POSITIONING_LONG_BIASED",
            62,
            "INFERRED",
            "Open interest is rising while funding is extremely positive; positioning appears long-biased.",
            timestamp,
        )
    elif oi_rising and funding_negative:
        snapshot.positioning_bias = "SHORT_BIASED"
        _add_signal(
            signals,
            "POSITIONING_SHORT_BIASED",
            62,
            "INFERRED",
            "Open interest is rising while funding is extremely negative; positioning appears short-biased.",
            timestamp,
        )
    elif oi_falling:
        snapshot.positioning_bias = "DELEVERAGING"

    if oi_rising and funding_positive and retail in {"BULLISH", "EUPHORIA", "EXTREME_BULLISH"}:
        snapshot.crowding_state = "CROWDED_LONG"
        _add_signal(
            signals,
            "CROWDED_LONG",
            78,
            "INFERRED",
            "Long-biased derivatives positioning aligns with elevated retail optimism.",
            timestamp,
        )
    elif oi_rising and funding_negative and retail in {"BEARISH", "PANIC", "CAPITULATION", "EXTREME_BEARISH"}:
        snapshot.crowding_state = "CROWDED_SHORT"
        _add_signal(
            signals,
            "CROWDED_SHORT",
            78,
            "INFERRED",
            "Short-biased derivatives positioning aligns with elevated retail pessimism.",
            timestamp,
        )
    elif snapshot.positioning_bias != "UNKNOWN" or price_rising or price_falling:
        snapshot.crowding_state = "BALANCED"

    if retail in {"EUPHORIA", "EXTREME_BULLISH"} and not oi_rising and not funding_positive:
        _add_signal(
            signals,
            "COMPLACENCY",
            55,
            "INFERRED",
            "Retail optimism is elevated without matching derivatives confirmation.",
            timestamp,
        )
    elif retail in {"PANIC", "CAPITULATION", "EXTREME_BEARISH"} and funding_negative:
        _add_signal(
            signals,
            "CAPITULATION",
            60,
            "INFERRED",
            "Retail panic aligns with negative funding pressure.",
            timestamp,
        )


def _derive_flow_and_divergence(snapshot, etf_flows, onchain, signals):
    timestamp = snapshot.sentiment_timestamp
    retail = (snapshot.retail_sentiment or "UNKNOWN").upper()

    etf_positive = etf_flows and (
        etf_flows.btc_etf_flow_regime == "POSITIVE"
        or (
            etf_flows.btc_etf_net_flow is not None
            and etf_flows.btc_etf_net_flow > 0
            and etf_flows.btc_etf_flow_zscore is not None
            and etf_flows.btc_etf_flow_zscore >= 2
        )
    )
    etf_negative = etf_flows and (
        etf_flows.btc_etf_flow_regime == "NEGATIVE"
        or (
            etf_flows.btc_etf_net_flow is not None
            and etf_flows.btc_etf_net_flow < 0
            and etf_flows.btc_etf_flow_zscore is not None
            and etf_flows.btc_etf_flow_zscore <= -2
        )
    )
    exchange_outflows = onchain and (
        onchain.btc_exchange_outflow_zscore is not None
        and onchain.btc_exchange_outflow_zscore >= 2.5
    )
    reserves_falling = onchain and (
        onchain.btc_exchange_reserve_change_7d is not None
        and onchain.btc_exchange_reserve_change_7d < -1
    )
    exchange_inflows = onchain and (
        onchain.btc_exchange_inflow_zscore is not None
        and onchain.btc_exchange_inflow_zscore >= 2.5
    )
    reserves_rising = onchain and (
        onchain.btc_exchange_reserve_change_7d is not None
        and onchain.btc_exchange_reserve_change_7d > 1
    )

    if etf_positive or exchange_outflows or reserves_falling:
        snapshot.institutional_flow_proxy = "INSTITUTIONAL_DEMAND_POSITIVE"
    elif etf_negative or exchange_inflows or reserves_rising:
        snapshot.institutional_flow_proxy = "INSTITUTIONAL_DEMAND_NEGATIVE"
    elif snapshot.institutional_flow_proxy == "UNKNOWN":
        snapshot.institutional_flow_proxy = "NEUTRAL"

    if retail in {"BEARISH", "PANIC", "CAPITULATION", "EXTREME_BEARISH"} and (
        (etf_positive and (exchange_outflows or reserves_falling))
        or (exchange_outflows and reserves_falling)
    ):
        snapshot.sentiment_divergence = "POSITIVE_FLOW_NEGATIVE_RETAIL"
        _add_signal(
            signals,
            "POSITIVE_FLOW_NEGATIVE_RETAIL_DIVERGENCE",
            82,
            "INFERRED",
            "Retail sentiment is negative while ETF/on-chain flow proxies point to demand or custody withdrawal.",
            timestamp,
        )
    elif retail in {"BULLISH", "EUPHORIA", "EXTREME_BULLISH"} and (
        etf_negative or (exchange_inflows and reserves_rising)
    ):
        snapshot.sentiment_divergence = "NEGATIVE_FLOW_POSITIVE_RETAIL"
        _add_signal(
            signals,
            "NEGATIVE_FLOW_POSITIVE_RETAIL_DIVERGENCE",
            82,
            "INFERRED",
            "Retail sentiment is positive while ETF/on-chain flow proxies weaken or point to exchange supply.",
            timestamp,
        )


def _derive_narrative(snapshot, signals):
    narrative = (snapshot.narrative_state or "UNKNOWN").upper()
    if narrative in {"OVERHEATED", "NARRATIVE_OVERHEAT"}:
        _add_signal(
            signals,
            "NARRATIVE_OVERHEAT",
            65,
            "INFERRED",
            "A dominant narrative is unusually popular; this does not validate the narrative.",
            snapshot.sentiment_timestamp,
        )


def analyze_sentiment_positioning(snapshot=None, market_snapshot=None, etf_flows=None, onchain=None):
    snapshot = snapshot or BtcSentimentSnapshot(sentiment_timestamp=_now())
    if not snapshot.sentiment_timestamp:
        snapshot.sentiment_timestamp = _now()

    signals = []
    _retail_signal(snapshot, signals)
    _derive_positioning(snapshot, market_snapshot, signals)
    _derive_flow_and_divergence(snapshot, etf_flows, onchain, signals)
    _derive_narrative(snapshot, signals)

    names = _names(signals)
    if _has_any(names, {"CROWDED_LONG", "CROWDED_SHORT"}) and _has_any(
        names,
        {
            "RETAIL_EUPHORIA",
            "RETAIL_PANIC",
            "POSITIONING_LONG_BIASED",
            "POSITIONING_SHORT_BIASED",
        },
    ):
        _add_signal(
            signals,
            "CROWDING_CONFLUENCE",
            78,
            "INFERRED",
            "Retail sentiment and derivatives positioning point to crowded positioning risk.",
            snapshot.sentiment_timestamp,
        )

    if "RETAIL_EUPHORIA" in names and "RETAIL_ATTENTION_SPIKE" in names:
        _add_signal(
            signals,
            "NARRATIVE_OVERHEAT",
            62,
            "INFERRED",
            "Retail attention and optimism are both elevated; popularity is not validity.",
            snapshot.sentiment_timestamp,
        )

    if snapshot.market_sentiment == "UNKNOWN":
        if snapshot.crowding_state == "CROWDED_LONG":
            snapshot.market_sentiment = "EUPHORIC"
        elif snapshot.crowding_state == "CROWDED_SHORT":
            snapshot.market_sentiment = "FEARFUL"
        elif snapshot.positioning_bias in {"LONG_BIASED", "SHORT_BIASED"}:
            snapshot.market_sentiment = "STRESSED"

    return snapshot, signals
