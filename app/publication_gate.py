from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config import (
    AUTO_PUBLISH_ALLOW_CRITICAL_RUMORS,
    AUTO_PUBLISH_ALLOW_MEDIUM,
    AUTO_PUBLISH_DUPLICATE_WINDOW_HOURS,
    AUTO_PUBLISH_MAX_PER_CYCLE,
    AUTO_PUBLISH_MAX_PER_DAY,
)
from history import recent_history
from market_scorer import _cap_for_routine_content
from market_taxonomy import SMALL_PRICE_MOVE_PATTERNS, keyword_in_text, text_blob


MATERIALITY_RANK = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}

CONFIDENCE_RANK = {
    "Baja": 0,
    "Media": 1,
    "Alta": 2,
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
}

FINAL_REJECT_REASONS = [
    "low_materiality",
    "weak_mechanism",
    "low_confidence",
    "unverified",
    "routine_content",
    "duplicate",
    "already_discounted",
    "crypto_noise",
    "reviewer_failed",
    "weak_asset_link",
    "frequency_limit",
]


@dataclass
class PublicationGateConfig:
    min_market_impact: int = 65
    min_materiality: str = "HIGH"
    min_confidence: str = "Media"
    allow_medium: bool = AUTO_PUBLISH_ALLOW_MEDIUM
    allow_critical_rumor: bool = AUTO_PUBLISH_ALLOW_CRITICAL_RUMORS
    max_per_cycle: int = AUTO_PUBLISH_MAX_PER_CYCLE
    max_per_day: int = AUTO_PUBLISH_MAX_PER_DAY
    duplicate_window_hours: int = AUTO_PUBLISH_DUPLICATE_WINDOW_HOURS
    allowed_verification: set[str] = field(
        default_factory=lambda: {"CONFIRMED", "PRELIMINARY"}
    )


@dataclass
class GateResult:
    item: object
    passed: bool
    reasons: list[str] = field(default_factory=list)
    mechanism_strength: str = "UNKNOWN"
    editorial_quality: int = 0


def _has_any(text, terms):
    return any(keyword_in_text(term, text) for term in terms)


def _materiality_rank(value):
    return MATERIALITY_RANK.get(value or "LOW", 0)


def _confidence_rank(value):
    return CONFIDENCE_RANK.get(value or "Baja", 0)


def topic_key(item):
    assets = "-".join(sorted(item.affected_assets or [])) or "NOASSET"
    topic = item.editorial_topic or item.event_type or item.category or "UNKNOWN"
    title_words = " ".join((item.title or "").lower().split()[:10])
    return f"{item.event_type}:{assets}:{topic}:{title_words[:100]}"


def mechanism_strength(item):
    text = text_blob(item)
    mechanism = (item.mechanism or "").lower()

    if not item.mechanism or "no clear material market transmission" in mechanism:
        return "UNKNOWN"

    direct_events = {
        "CRYPTO_REGULATION",
        "CRYPTO_MARKET_STRUCTURE",
        "SYSTEMIC_COMPANY",
        "BTC_DAILY_RECAP",
        "COMBINED_MARKET_STORY",
    }
    strong_second_order_events = {
        "CENTRAL_BANK",
        "MACRO_DATA",
        "LIQUIDITY",
        "GEOPOLITICAL_MARKET",
        "FISCAL_TRADE",
    }

    has_direct_btc = "BTC" in item.affected_assets and _has_any(
        text,
        [
            "bitcoin",
            "btc",
            "spot bitcoin etf",
            "bitcoin etf",
            "etf inflow",
            "etf outflow",
            "funding",
            "open interest",
            "liquidation",
            "clarity act",
            "crypto regulation",
            "digital asset market clarity",
            "stablecoin legislation",
            "cftc crypto",
            "sec crypto",
            "white house crypto",
            "24h price action",
            "open interest",
            "structure",
        ],
    )
    has_systemic_company = item.event_type == "SYSTEMIC_COMPANY" and _has_any(
        text,
        ["guidance", "capex", "revenue", "demand", "profit warning", "export restriction"],
    )
    has_macro_channel = item.event_type in strong_second_order_events and _has_any(
        text,
        ["rates", "yields", "dollar", "usd", "inflation", "payrolls", "gdp", "pmi", "financial conditions", "oil", "sanctions", "tariffs"],
    )

    if item.event_type in direct_events and (has_direct_btc or has_systemic_company):
        return "DIRECT"

    if has_macro_channel:
        return "STRONG_SECOND_ORDER"

    if "risk assets" in mechanism or "btc" in mechanism:
        return "WEAK_INDIRECT"

    return "UNKNOWN"


def editorial_quality_score(item, mechanism_level=None):
    mechanism_level = mechanism_level or mechanism_strength(item)
    score = 0

    if item.surprise == "KNOWN" or _has_any(text_blob(item), ["unexpected", "surprise", "above expectations", "below expectations"]):
        score += 20
    elif item.discountedness != "HIGH":
        score += 8

    if mechanism_level == "DIRECT":
        score += 20
    elif mechanism_level == "STRONG_SECOND_ORDER":
        score += 16

    if item.verification_status == "CONFIRMED":
        score += 18
    elif item.verification_status == "PRELIMINARY":
        score += 10
    elif item.verification_status == "RUMOR" and item.materiality == "CRITICAL":
        score += 4

    if item.impact_horizon in {"INTRADAY", "DAYS_WEEKS"}:
        score += 12

    if item.confluence_score >= 60:
        score += 15
    elif item.confluence_score >= 30:
        score += 8

    if _materiality_rank(item.materiality) >= MATERIALITY_RANK["HIGH"]:
        score += 10

    if item.market_impact >= 82:
        score += 5

    return max(0, min(100, int(score)))


def _is_crypto_noise(item):
    text = text_blob(item)
    if item.materiality == "LOW" and (item.crypto_asset or item.asset_class == "CRYPTO"):
        return True
    return _has_any(text, SMALL_PRICE_MOVE_PATTERNS) and not _has_any(
        text,
        [
            "etf",
            "sec",
            "regulation",
            "open interest",
            "funding",
            "liquidation",
            "exchange inflow",
            "exchange outflow",
        ],
    )


def _history_datetime(row):
    try:
        return datetime.strptime(row.get("date", ""), "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _recent_duplicate_topics(items, config):
    cutoff = datetime.now() - timedelta(hours=config.duplicate_window_hours)
    keys = set()
    for row in recent_history(days=max(1, config.duplicate_window_hours // 24 + 1)):
        row_date = _history_datetime(row)
        if row_date is None or row_date < cutoff:
            continue
        title = row.get("title", "")
        topic = row.get("editorial_topic", "") or row.get("category", "")
        category = row.get("category", "")
        pseudo = type(
            "HistoryItem",
            (),
            {
                "affected_assets": [],
                "editorial_topic": topic,
                "event_type": category,
                "category": category,
                "title": title,
            },
        )
        keys.add(topic_key(pseudo))

    return keys


def _published_today_count():
    today = datetime.now().date()
    count = 0
    for row in recent_history(days=1):
        row_date = _history_datetime(row)
        if row_date and row_date.date() == today and row.get("status") == "published":
            count += 1
    return count


def evaluate_item(item, review_ok=True, config=None, duplicate_keys=None):
    config = config or PublicationGateConfig()
    duplicate_keys = duplicate_keys or set()
    reasons = []
    text = text_blob(item)
    mechanism_level = mechanism_strength(item)
    quality = editorial_quality_score(item, mechanism_level)

    if not review_ok:
        reasons.append("reviewer_failed")

    if item.market_impact < config.min_market_impact:
        reasons.append("low_materiality")

    min_materiality = config.min_materiality
    if config.allow_medium:
        min_materiality = "MEDIUM"
    if _materiality_rank(item.materiality) < _materiality_rank(min_materiality):
        reasons.append("low_materiality")

    if _confidence_rank(item.confidence) < _confidence_rank(config.min_confidence):
        reasons.append("low_confidence")

    if item.verification_status not in config.allowed_verification:
        rumor_allowed = (
            item.verification_status == "RUMOR"
            and item.materiality == "CRITICAL"
            and item.market_impact >= 90
            and config.allow_critical_rumor
        )
        if not rumor_allowed:
            reasons.append("unverified")

    if item.duplicate or item.link in duplicate_keys or topic_key(item) in duplicate_keys:
        reasons.append("duplicate")

    cap = _cap_for_routine_content(text)
    if cap is not None and item.market_impact > cap:
        reasons.append("routine_content")

    if _is_crypto_noise(item):
        reasons.append("crypto_noise")

    if item.affected_assets == [] and item.event_type not in {"UNKNOWN"}:
        reasons.append("weak_asset_link")

    if mechanism_level not in {"DIRECT", "STRONG_SECOND_ORDER"}:
        reasons.append("weak_mechanism")

    if "BTC" in item.affected_assets and mechanism_level == "WEAK_INDIRECT":
        reasons.append("weak_asset_link")

    if item.discountedness == "HIGH" and item.surprise not in {"KNOWN", "MATERIAL"}:
        reasons.append("already_discounted")

    if quality < 55:
        reasons.append("weak_mechanism")

    item.mechanism_of_impact = mechanism_level
    item.editorial_quality = quality
    item.final_reject_reasons = sorted(set(reasons))
    item.final_decision = "PASS" if not reasons else "FAIL"

    return GateResult(
        item=item,
        passed=not reasons,
        reasons=item.final_reject_reasons,
        mechanism_strength=mechanism_level,
        editorial_quality=quality,
    )


def apply_publication_gate(items, review, config=None):
    config = config or PublicationGateConfig()
    review_ok = bool(review.get("ok"))
    duplicate_keys = _recent_duplicate_topics(items, config)

    results = [
        evaluate_item(
            item,
            review_ok=review_ok,
            config=config,
            duplicate_keys=duplicate_keys,
        )
        for item in items
    ]

    passed = [result.item for result in results if result.passed]
    normal = [item for item in passed if item.materiality != "CRITICAL"]
    critical = [item for item in passed if item.materiality == "CRITICAL"]

    daily_remaining = max(0, config.max_per_day - _published_today_count())
    selected = []
    if daily_remaining:
        selected.extend(normal[: min(config.max_per_cycle, daily_remaining)])

    normal_links = {item.link for item in selected}
    for item in critical:
        if item.link not in normal_links:
            selected.append(item)

    selected_links = {item.link for item in selected}
    for result in results:
        if result.passed and result.item.link not in selected_links:
            result.reasons.append("frequency_limit")
            result.item.final_reject_reasons = sorted(set(result.reasons))
            result.item.final_decision = "FAIL"
            result.passed = False

    counters = Counter()
    for result in results:
        for reason in result.reasons:
            counters[reason] += 1

    return selected, results, counters
