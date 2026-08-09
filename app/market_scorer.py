from market_taxonomy import (
    LOW_VALUE_CRYPTO,
    SMALL_PRICE_MOVE_PATTERNS,
    asset_class_for_assets,
    detect_assets,
    detect_event_type,
    keyword_in_text,
    text_blob,
)
from sources_registry import apply_source_metadata


MATERIALITY_RANK = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}

ROUTINE_TERMS = [
    "consolidated banking data",
    "statistical release",
    "statistics",
    "end-march",
    "end-march 2026",
    "routine",
    "committee meeting",
    "meeting minutes of non-monetary",
]

ADMIN_TERMS = [
    "enforcement action",
    "enforcement actions",
    "request for comment",
    "proposal",
    "proposes",
    "extension of credit",
    "bank insiders",
    "administrative",
    "technical amendment",
]

MARKETING_TERMS = [
    "blog",
    "omniverse",
    "retrospective",
    "customer story",
    "case study",
    "webinar",
    "developer preview",
    "security update",
    "datacenter",
    "data center",
    "generic ai",
]

MATERIAL_POLICY_TERMS = [
    "50bp",
    "50 bp",
    "25bp surprise",
    "rate hike",
    "rate cut",
    "raises rates",
    "cuts rates",
    "unexpectedly holds",
    "unexpectedly hikes",
    "unexpectedly cuts",
    "unexpected",
    "hawkish",
    "dovish",
    "dot plot",
    "balance sheet runoff",
    "quantitative tightening",
    "quantitative easing",
]

MATERIAL_MACRO_TERMS = [
    "above expectations",
    "below expectations",
    "hotter than expected",
    "weaker than expected",
    "surprise",
    "unexpected",
    "recession",
    "financial conditions",
    "credit crunch",
]

MATERIAL_COMPANY_TERMS = [
    "cuts guidance",
    "raises guidance",
    "revenue guidance",
    "profit warning",
    "materially cuts",
    "materially raises",
    "25%",
    "capex cut",
    "capex increase",
    "demand collapse",
    "supply shortage",
    "export restriction",
    "antitrust",
]

MATERIAL_CRYPTO_TERMS = [
    "spot bitcoin etf",
    "bitcoin etf",
    "etf inflows",
    "etf outflows",
    "exceptionally large",
    "multiple sessions",
    "sec approves",
    "sec rejects",
    "sec decision",
    "custody",
    "stablecoin",
    "strategic bitcoin reserve",
    "institutional access",
    "exchange inflow",
    "exchange outflow",
    "open interest",
    "funding",
    "liquidation cascade",
]

MATERIAL_GEOPOLITICAL_TERMS = [
    "oil supply",
    "shipping route",
    "strait",
    "sanctions",
    "tariffs",
    "export controls",
    "taiwan semiconductor",
    "red sea",
    "suez",
]


def _contains_any(text, words):
    return any(keyword_in_text(word, text) for word in words)


def _cap_for_routine_content(text):
    if _contains_any(text, ADMIN_TERMS):
        return 25
    if _contains_any(text, MARKETING_TERMS):
        return 25
    if _contains_any(text, ROUTINE_TERMS):
        return 40
    return None


def _has_material_policy_event(text):
    return _contains_any(text, MATERIAL_POLICY_TERMS)


def _has_material_macro_event(text):
    return _contains_any(text, MATERIAL_MACRO_TERMS)


def _has_material_company_event(text):
    return _contains_any(text, MATERIAL_COMPANY_TERMS)


def _has_material_crypto_event(text):
    return _contains_any(text, MATERIAL_CRYPTO_TERMS)


def _has_material_geopolitical_event(text):
    return _contains_any(text, MATERIAL_GEOPOLITICAL_TERMS)


def _material_event_gate(text, item):
    if item.event_type == "CENTRAL_BANK":
        return _has_material_policy_event(text)
    if item.event_type == "MACRO_DATA":
        return _has_material_macro_event(text)
    if item.event_type == "LIQUIDITY":
        return _has_material_macro_event(text) or _contains_any(
            text,
            ["liquidity shock", "funding stress", "credit crunch", "repo spike"],
        )
    if item.event_type == "CRYPTO_REGULATION":
        return _has_material_crypto_event(text)
    if item.event_type == "CRYPTO_MARKET_STRUCTURE":
        return _contains_any(
            text,
            [
                "exceptionally large",
                "multiple sessions",
                "liquidation cascade",
                "funding extreme",
                "open interest surge",
            ],
        )
    if item.event_type == "SYSTEMIC_COMPANY":
        return _has_material_company_event(text)
    if item.event_type in {"GEOPOLITICAL_MARKET", "FISCAL_TRADE"}:
        return _has_material_geopolitical_event(text)
    return False


def _event_materiality_score(text, item):
    if not _material_event_gate(text, item):
        return 0

    return {
        "CENTRAL_BANK": 30,
        "MACRO_DATA": 26,
        "LIQUIDITY": 28,
        "FISCAL_TRADE": 22,
        "GEOPOLITICAL_MARKET": 22,
        "CRYPTO_REGULATION": 30,
        "CRYPTO_MARKET_STRUCTURE": 24,
        "SYSTEMIC_COMPANY": 24,
    }.get(item.event_type, 0)


def _surprise_novelty_score(text):
    if _contains_any(
        text,
        [
            "unexpected",
            "unexpectedly",
            "surprise",
            "above expectations",
            "below expectations",
            "hotter than expected",
            "weaker than expected",
            "not priced",
        ],
    ):
        return 18

    return 0


def _expectation_change_score(text, item):
    if item.event_type == "CENTRAL_BANK" and _contains_any(
        text,
        ["hawkish", "dovish", "dot plot", "rate guidance", "higher rates", "lower rates"],
    ):
        return 18

    if item.event_type == "SYSTEMIC_COMPANY" and _contains_any(
        text,
        ["guidance", "profit warning", "materially cuts", "materially raises"],
    ):
        return 16

    if item.event_type == "CRYPTO_REGULATION" and _contains_any(
        text,
        ["approves", "rejects", "decision", "custody", "institutional access"],
    ):
        return 18

    if item.event_type == "CRYPTO_MARKET_STRUCTURE" and _contains_any(
        text,
        ["multiple sessions", "exceptionally large", "surge", "extreme"],
    ):
        return 14

    if item.event_type == "CRYPTO_REGULATION" and _contains_any(
        text,
        ["etf inflows", "etf outflows", "multiple sessions", "exceptionally large"],
    ):
        return 14

    return 0


def _systemic_reach_score(text, item):
    score = 0

    if item.event_type in {"CENTRAL_BANK", "MACRO_DATA", "LIQUIDITY"}:
        score += 12
    if _contains_any(text, ["global", "systemic", "financial conditions", "risk assets"]):
        score += 8
    if any(asset in item.affected_assets for asset in {"SP500", "NASDAQ", "TREASURIES", "EURUSD", "BTC"}):
        score += 5

    return min(score, 15)


def _direct_transmission_score(text, item):
    if item.event_type == "CENTRAL_BANK" and _contains_any(
        text,
        ["rates", "yields", "dollar", "financial conditions", "balance sheet"],
    ):
        return 10

    if item.event_type == "MACRO_DATA" and _contains_any(
        text,
        ["inflation", "payrolls", "gdp", "pmi", "rates", "yields"],
    ):
        return 8

    if item.event_type == "CRYPTO_REGULATION" and _contains_any(
        text,
        ["bitcoin", "btc", "etf", "custody", "institutional access"],
    ):
        return 10

    if item.event_type == "SYSTEMIC_COMPANY" and _contains_any(
        text,
        ["guidance", "nasdaq", "semiconductor", "capex", "revenue"],
    ):
        return 8

    if item.event_type == "CRYPTO_MARKET_STRUCTURE" and _contains_any(
        text,
        ["etf inflows", "etf outflows", "open interest", "funding", "liquidation"],
    ):
        return 8

    return 0


def _source_quality_score(item):
    if item.source_type == "PRIMARY":
        return 5
    if item.source_type == "HIGH_RELIABILITY":
        return 4
    if item.source_type == "FAST":
        return 2
    if item.source_type == "COMMUNITY":
        return -5
    return 0


def _filter_assets_for_transmission(text, item, raw_assets):
    assets = [
        asset
        for asset in raw_assets
        if asset not in {"BTC", "ETH"}
    ]

    has_btc_direct = _contains_any(text, ["bitcoin", "btc", "spot bitcoin etf", "bitcoin etf"])
    has_eth_direct = _contains_any(text, ["ethereum", "ether", "spot eth etf", "eth etf"])

    strong_macro_btc = (
        item.event_type in {"CENTRAL_BANK", "MACRO_DATA", "LIQUIDITY"}
        and _material_event_gate(text, item)
        and _contains_any(
            text,
            [
                "rates",
                "real yields",
                "dollar",
                "usd",
                "global liquidity",
                "financial conditions",
                "risk assets",
            ],
        )
    )

    if has_btc_direct or strong_macro_btc:
        assets.append("BTC")

    if has_eth_direct and (
        item.event_type in {"CRYPTO_REGULATION", "CRYPTO_MARKET_STRUCTURE"}
        or _contains_any(text, ["staking", "ethereum protocol", "eth etf"])
    ):
        assets.append("ETH")

    if item.event_type == "CENTRAL_BANK" and _material_event_gate(text, item):
        if _contains_any(text, ["rates", "yields", "50bp", "50 bp", "rate hike", "rate cut"]):
            assets.extend(["TREASURIES", "EURUSD"])
        if _contains_any(text, ["risk assets", "equities", "financial conditions"]):
            assets.extend(["SP500", "NASDAQ"])

    if item.event_type == "SYSTEMIC_COMPANY" and "NVIDIA" in assets:
        if _has_material_company_event(text):
            assets.append("NASDAQ")

    deduped = []
    for asset in assets:
        if asset not in deduped:
            deduped.append(asset)

    return deduped


def _asset_relevance_score(item):
    if not item.affected_assets:
        return 0

    score = 0
    for asset in item.affected_assets:
        if asset in {"SP500", "NASDAQ", "TREASURIES", "EURUSD", "BTC", "NVIDIA"}:
            score += 3
        else:
            score += 1

    return min(score, 5)


def _market_state_signals(text):
    signals = []

    signal_words = {
        "open interest": "OI shift",
        "funding": "funding stress",
        "liquidation": "liquidation cluster",
        "liquidations": "liquidation cluster",
        "basis": "basis shift",
        "options": "options positioning",
        "put/call": "options sentiment",
        "etf inflows": "ETF inflows",
        "etf outflows": "ETF outflows",
        "exchange inflow": "exchange inflow",
        "exchange outflow": "exchange outflow",
        "whale": "whale activity",
        "miner": "miner flow",
        "stablecoin": "stablecoin liquidity",
    }

    for word, label in signal_words.items():
        if keyword_in_text(word, text) and label not in signals:
            signals.append(label)

    return signals


def _crypto_penalty(text, item):
    if item.asset_class != "CRYPTO" and not item.crypto_asset:
        return 0

    penalty = 0
    if _contains_any(text, LOW_VALUE_CRYPTO):
        penalty -= 45

    if _contains_any(text, SMALL_PRICE_MOVE_PATTERNS) and not _has_material_crypto_event(text):
        penalty -= 35

    if item.crypto_asset == "ETH" and not _contains_any(
        text,
        ["ethereum", "ether", "spot eth etf", "eth etf", "staking"],
    ):
        penalty -= 25

    return penalty


def _infer_materiality(score, has_material_gate):
    if not has_material_gate:
        return "LOW" if score < 45 else "MEDIUM"
    if score >= 82:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 45:
        return "MEDIUM"
    return "LOW"


def _apply_caps(score, cap):
    if cap is None:
        return score
    return min(score, cap)


def score_market_item(item):
    if item.source == "MARKET_STATE":
        item.score = item.market_impact
        return item

    apply_source_metadata(item)

    text = text_blob(item)
    item.event_type = detect_event_type(text)
    if _contains_any(text, ["bitcoin etf", "spot bitcoin etf", "etf inflows", "etf outflows"]):
        item.event_type = "CRYPTO_REGULATION"
    elif _contains_any(text, ["open interest", "funding", "liquidation", "liquidations"]):
        item.event_type = "CRYPTO_MARKET_STRUCTURE"

    raw_assets = detect_assets(text)
    item.affected_assets = _filter_assets_for_transmission(text, item, raw_assets)
    item.asset_class = asset_class_for_assets(item.affected_assets, item.event_type)

    if "BTC" in item.affected_assets:
        item.crypto_asset = "BTC"
    elif "ETH" in item.affected_assets:
        item.crypto_asset = "ETH"
    else:
        item.crypto_asset = ""

    has_material_gate = _material_event_gate(text, item)
    routine_cap = _cap_for_routine_content(text)

    event_materiality = _event_materiality_score(text, item)
    surprise_novelty = _surprise_novelty_score(text)
    expectation_change = _expectation_change_score(text, item)
    systemic_reach = _systemic_reach_score(text, item)
    direct_transmission = _direct_transmission_score(text, item)
    asset_relevance = _asset_relevance_score(item)
    source_quality = _source_quality_score(item)

    score = (
        event_materiality
        + surprise_novelty
        + expectation_change
        + systemic_reach
        + direct_transmission
        + asset_relevance
        + source_quality
    )

    item.market_signals = _market_state_signals(text)

    if item.event_type == "CENTRAL_BANK" and has_material_gate:
        item.market_signals.append("rates/yields transmission")
        item.macro_driver = "RATES_LIQUIDITY"
    elif item.event_type == "MACRO_DATA" and has_material_gate:
        item.market_signals.append("macro surprise")
        item.macro_driver = "MACRO_EXPECTATIONS"
    elif item.event_type == "LIQUIDITY" and has_material_gate:
        item.market_signals.append("liquidity channel")
        item.macro_driver = "LIQUIDITY"

    if surprise_novelty:
        item.surprise = "KNOWN"

    if _contains_any(text, ["rumor", "unconfirmed", "reportedly", "sources say", "may approve", "could approve"]):
        item.is_rumor = True
        item.verification_status = "RUMOR"
        score -= 8

    if item.source_type in {"FAST", "COMMUNITY"} and not item.is_confirmed:
        item.verification_status = "RUMOR" if item.is_rumor else "PRELIMINARY"

    if _contains_any(text, ["confirmed"]) and item.source_type in {"PRIMARY", "HIGH_RELIABILITY"}:
        item.verification_status = "CONFIRMED"
        item.is_confirmed = True

    score += _crypto_penalty(text, item)

    if not has_material_gate:
        score = min(score, 44)

    score = _apply_caps(score, routine_cap)

    item.market_impact = max(0, min(100, int(score)))
    item.score = item.market_impact
    item.materiality = _infer_materiality(item.market_impact, has_material_gate)
    item.impact_horizon = "INTRADAY" if item.source_speed >= 80 and has_material_gate else "DAYS_WEEKS"
    item.geographic_scope = "GLOBAL" if item.asset_class in {"MACRO", "CRYPTO", "RATES", "FX"} else "REGIONAL"
    item.confluence_score = min(100, len(set(item.market_signals)) * 15)

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
    if item.event_type == "CENTRAL_BANK" and item.materiality in {"HIGH", "CRITICAL"}:
        return "rates/yields/USD -> financial conditions -> risk assets"
    if item.event_type == "MACRO_DATA" and item.materiality in {"HIGH", "CRITICAL"}:
        return "macro surprise -> policy expectations -> rates/USD -> risk assets"
    if item.event_type == "CRYPTO_REGULATION":
        return "regulation/access -> institutional demand/liquidity -> BTC/ETH"
    if item.event_type == "CRYPTO_MARKET_STRUCTURE":
        return "positioning/liquidity -> volatility risk -> BTC/ETH"
    if item.event_type == "SYSTEMIC_COMPANY":
        return "guidance/capex/demand -> sector expectations -> indices"
    if item.event_type == "GEOPOLITICAL_MARKET":
        return "geopolitical shock -> commodities/supply chains -> inflation/risk"
    return "no clear material market transmission"


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
            and item.market_impact >= 55
            and item.mechanism != "no clear material market transmission"
        )

    return False
