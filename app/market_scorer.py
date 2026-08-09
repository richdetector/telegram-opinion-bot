from market_taxonomy import (
    LOW_VALUE_CRYPTO,
    SMALL_PRICE_MOVE_PATTERNS,
    asset_class_for_assets,
    detect_assets,
    detect_event_type,
    text_blob,
)
from sources_registry import apply_source_metadata


MATERIALITY_RANK = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


def _contains_any(text, words):
    return any(word in text for word in words)


def _base_event_score(event_type):
    return {
        "CENTRAL_BANK": 35,
        "MACRO_DATA": 30,
        "LIQUIDITY": 32,
        "FISCAL_TRADE": 28,
        "GEOPOLITICAL_MARKET": 26,
        "CRYPTO_REGULATION": 36,
        "CRYPTO_MARKET_STRUCTURE": 24,
        "SYSTEMIC_COMPANY": 28,
        "UNKNOWN": 0,
    }.get(event_type, 0)


def _asset_relevance(assets):
    score = 0
    systemic = {
        "SP500",
        "NASDAQ",
        "TREASURIES",
        "EURUSD",
        "USDJPY",
        "OIL",
        "BTC",
        "ETH",
        "NVIDIA",
        "APPLE",
        "MICROSOFT",
        "AMAZON",
        "META",
        "ALPHABET",
        "TESLA",
        "TSMC",
        "ASML",
        "BROADCOM",
    }
    for asset in set(assets):
        score += 12 if asset in systemic else 6
    return min(score, 28)


def _macro_transmission(text, item):
    signals = []
    score = 0

    if _contains_any(text, ["fed", "fomc", "ecb", "bce", "boj", "pboc", "rate", "rates", "yields"]):
        signals.append("rates/liquidity transmission")
        score += 12
        if "BTC" not in item.affected_assets:
            item.affected_assets.append("BTC")
        item.macro_driver = "RATES_LIQUIDITY"

    if _contains_any(text, ["dollar", "usd", "yield", "yields", "financial conditions"]):
        signals.append("dollar/yields channel")
        score += 8

    if _contains_any(text, ["liquidity", "repo", "credit", "bank", "stablecoin", "etf flows"]):
        signals.append("liquidity channel")
        score += 10

    return score, signals


def _market_state_signals(text):
    signals = []
    score = 0

    signal_words = {
        "open interest": "OI shift",
        "funding": "funding stress",
        "liquidation": "liquidation cluster",
        "liquidations": "liquidation cluster",
        "basis": "basis shift",
        "options": "options positioning",
        "put/call": "options sentiment",
        "etf flow": "ETF flow",
        "etf flows": "ETF flow",
        "exchange inflow": "exchange inflow",
        "exchange outflow": "exchange outflow",
        "whale": "whale activity",
        "miner": "miner flow",
        "stablecoin": "stablecoin liquidity",
    }

    for word, label in signal_words.items():
        if word in text and label not in signals:
            signals.append(label)
            score += 6

    if len(signals) >= 3:
        score += 12

    return min(score, 30), signals


def _confirmation_score(item):
    if item.source_type == "PRIMARY":
        return 20
    if item.source_type == "HIGH_RELIABILITY":
        return 16
    if item.source_type == "FAST":
        return 6
    if item.source_type == "COMMUNITY":
        return -12
    return 0


def _source_score(item):
    return int((item.source_reliability * 0.18) + (item.source_speed * 0.06))


def _infer_materiality(score):
    if score >= 92:
        return "CRITICAL"
    if score >= 72:
        return "HIGH"
    if score >= 52:
        return "MEDIUM"
    return "LOW"


def _crypto_penalty(text, item):
    if item.asset_class != "CRYPTO" and not item.crypto_asset:
        return 0

    penalty = 0
    if _contains_any(text, LOW_VALUE_CRYPTO):
        penalty -= 45

    if _contains_any(text, SMALL_PRICE_MOVE_PATTERNS) and not _contains_any(
        text,
        [
            "sec",
            "etf",
            "regulation",
            "stablecoin",
            "custody",
            "open interest",
            "funding",
            "liquidation",
            "exchange inflow",
            "exchange outflow",
            "whale",
            "fed",
        ],
    ):
        penalty -= 35

    if item.crypto_asset == "ETH" and item.event_type not in {
        "CRYPTO_REGULATION",
        "CRYPTO_MARKET_STRUCTURE",
        "LIQUIDITY",
        "CENTRAL_BANK",
    }:
        penalty -= 15

    return penalty


def score_market_item(item):
    apply_source_metadata(item)

    text = text_blob(item)
    item.affected_assets = detect_assets(text)
    item.event_type = detect_event_type(text)
    item.asset_class = asset_class_for_assets(item.affected_assets, item.event_type)

    if "BTC" in item.affected_assets:
        item.crypto_asset = "BTC"
    elif "ETH" in item.affected_assets:
        item.crypto_asset = "ETH"

    score = 0
    score += _base_event_score(item.event_type)
    score += _asset_relevance(item.affected_assets)
    score += _source_score(item)
    score += _confirmation_score(item)

    macro_score, macro_signals = _macro_transmission(text, item)
    state_score, state_signals = _market_state_signals(text)
    score += macro_score + state_score
    item.market_signals = macro_signals + state_signals
    item.confluence_score = min(100, len(set(item.market_signals)) * 15)

    if _contains_any(text, ["unexpected", "surprise", "above expectations", "below expectations", "hotter than expected", "weaker than expected"]):
        score += 15
        item.surprise = "KNOWN"

    if _contains_any(text, ["rumor", "unconfirmed", "reportedly", "sources say", "may approve", "could approve"]):
        item.is_rumor = True
        item.verification_status = "RUMOR"
        score -= 8

    if item.source_type in {"FAST", "COMMUNITY"} and not item.is_confirmed:
        item.verification_status = "RUMOR" if item.is_rumor else "PRELIMINARY"

    score += _crypto_penalty(text, item)

    if item.event_type == "UNKNOWN" and not item.affected_assets and not item.market_signals:
        score = min(score, 25)

    item.market_impact = max(0, min(100, int(score)))
    item.score = item.market_impact
    item.materiality = _infer_materiality(item.market_impact)
    item.impact_horizon = "INTRADAY" if item.source_speed >= 80 else "DAYS_WEEKS"
    item.geographic_scope = "GLOBAL" if item.asset_class in {"MACRO", "CRYPTO", "RATES", "FX"} else "REGIONAL"

    if item.market_impact >= 80 and item.verification_status == "CONFIRMED":
        item.confidence = "Alta"
    elif item.market_impact >= 65 and item.verification_status in {"CONFIRMED", "PRELIMINARY"}:
        item.confidence = "Media"
    else:
        item.confidence = "Baja"

    item.mechanism = _mechanism_for(item)
    item.intelligence_summary = build_intelligence_summary(item)

    return item


def _mechanism_for(item):
    if item.event_type == "CENTRAL_BANK":
        return "rates -> dollar/yields -> financial conditions -> risk assets/BTC"
    if item.event_type == "MACRO_DATA":
        return "macro surprise -> policy expectations -> rates/USD -> risk assets"
    if item.event_type == "CRYPTO_REGULATION":
        return "regulation/access -> institutional demand/liquidity -> BTC/ETH"
    if item.event_type == "CRYPTO_MARKET_STRUCTURE":
        return "positioning/liquidity -> volatility risk -> BTC/ETH"
    if item.event_type == "SYSTEMIC_COMPANY":
        return "guidance/capex/demand -> sector expectations -> indices"
    if item.event_type == "GEOPOLITICAL_MARKET":
        return "geopolitical shock -> commodities/supply chains -> inflation/risk"
    return "market expectations channel"


def build_intelligence_summary(item):
    return {
        "MACRO": "Unknown" if not item.macro_driver else "Relevant",
        "LIQUIDITY": "Unknown",
        "INSTITUTIONAL_FLOW": "Unknown",
        "ON_CHAIN": "Unknown",
        "DERIVATIVES": "Unknown",
        "RETAIL": "Unknown",
        "MARKET_STRUCTURE": "Unknown",
        "CONFLUENCE": (
            "High"
            if item.confluence_score >= 60
            else "Medium"
            if item.confluence_score >= 30
            else "Low"
        ),
    }


def score_market_news(news):
    return [score_market_item(item) for item in news]


def can_reach_selection(item):
    if item.materiality in {"HIGH", "CRITICAL"}:
        return True

    if item.materiality == "MEDIUM":
        return (
            item.source_reliability >= 80
            and item.event_type in {"CENTRAL_BANK", "MACRO_DATA", "CRYPTO_REGULATION", "LIQUIDITY"}
            and item.market_impact >= 62
        )

    return False
