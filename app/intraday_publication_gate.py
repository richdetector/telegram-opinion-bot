from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config import (
    INTRADAY_ALERT_MIN_CONFLUENCE,
    INTRADAY_MAX_DATA_AGE_MINUTES,
    INTRADAY_MAX_PER_4H,
    INTRADAY_NOTE_MIN_CONFLUENCE,
)
from history import recent_history


INTRADAY_REJECT_REASONS = [
    "not_intraday",
    "reviewer_failed",
    "low_intraday_confluence",
    "low_intraday_materiality",
    "weak_intraday_note",
    "stale_market_data",
    "insufficient_independent_signals",
    "duplicate",
    "frequency_limit",
    "forbidden_trading_language",
]


@dataclass
class IntradayGateResult:
    item: object
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _parse_date(value):
    try:
        return datetime.strptime(value or "", "%Y-%m-%d %H:%M")
    except Exception:
        try:
            return datetime.fromisoformat(value or "")
        except Exception:
            return None


def _recent_intraday_count(hours=4):
    cutoff = datetime.now() - timedelta(hours=hours)
    count = 0
    for row in recent_history(days=1):
        when = _parse_date(row.get("date"))
        if when is None or when < cutoff:
            continue
        if row.get("category") in {"BTC Intraday", "BTC Intraday Update"}:
            count += 1
    return count


def _independent_signal_count(item):
    names = set(item.market_signals or [])
    groups = {
        "price": any(name.startswith("PRICE_ACCELERATION") for name in names),
        "volume": any(name.startswith("VOLUME") for name in names),
        "volatility": "VOLATILITY_EXPANSION" in names,
        "oi": any(
            name in names
            for name in {
                "MOMENTUM_WITH_LEVERAGE_BUILDUP",
                "POSSIBLE_SHORT_COVERING",
                "DELEVERAGING_STYLE_MOVE",
                "NEW_BEARISH_POSITIONING",
                "LEVERAGE_BUILDING_COMPRESSION",
            }
        ),
        "structure": any("BREAKOUT" in name or "BREAK_OF_STRUCTURE" in name or "SWEEP" in name for name in names),
        "liquidity": any(name.startswith("LIQUIDITY_CLUSTER") or name.startswith("EQUAL_") for name in names),
    }
    return sum(1 for active in groups.values() if active)


def _has_trading_language(item):
    text = f"{item.title} {item.summary} {item.content}".lower()
    forbidden = [
        "buy",
        "sell",
        "long now",
        "short now",
        "take profit",
        "stop loss",
        "entrada",
        "compra ahora",
        "vende ahora",
    ]
    return any(term in text for term in forbidden)


def evaluate_intraday_item(item, review_ok=True, duplicate_keys=None):
    duplicate_keys = duplicate_keys or set()
    reasons = []

    if item.event_type != "BTC_INTRADAY_MOVE":
        reasons.append("not_intraday")

    if not review_ok:
        reasons.append("reviewer_failed")

    decision = item.intelligence_summary.get("INTRADAY_DECISION") if item.intelligence_summary else ""
    is_note = decision == "INTRADAY_NOTE" or item.category == "BTC Intraday Note"
    min_confluence = INTRADAY_NOTE_MIN_CONFLUENCE if is_note else INTRADAY_ALERT_MIN_CONFLUENCE

    if item.confluence_score < min_confluence:
        reasons.append("low_intraday_confluence")

    if is_note:
        if item.materiality not in {"MEDIUM", "HIGH", "CRITICAL"}:
            reasons.append("low_intraday_materiality")
    elif item.materiality not in {"HIGH", "CRITICAL"}:
        reasons.append("low_intraday_materiality")

    age = item.intelligence_summary.get("MARKET_DATA_AGE_MINUTES") if item.intelligence_summary else None
    if age is not None and age > INTRADAY_MAX_DATA_AGE_MINUTES:
        reasons.append("stale_market_data")

    if _independent_signal_count(item) < 2 and item.confluence_score < 90:
        reasons.append("insufficient_independent_signals")
    if is_note and _independent_signal_count(item) < 3 and item.confluence_score < INTRADAY_ALERT_MIN_CONFLUENCE:
        reasons.append("weak_intraday_note")

    if item.link in duplicate_keys or item.duplicate:
        reasons.append("duplicate")

    if _has_trading_language(item):
        reasons.append("forbidden_trading_language")

    item.final_decision = "PASS" if not reasons else "FAIL"
    item.final_reject_reasons = sorted(set(reasons))
    return IntradayGateResult(item=item, passed=not reasons, reasons=item.final_reject_reasons)


def apply_intraday_publication_gate(items, review):
    review_ok = bool(review.get("ok"))
    duplicate_keys = set()
    results = [
        evaluate_intraday_item(item, review_ok=review_ok, duplicate_keys=duplicate_keys)
        for item in items
        if item.event_type == "BTC_INTRADAY_MOVE"
    ]

    passed = [result.item for result in results if result.passed]
    slots = max(0, INTRADAY_MAX_PER_4H - _recent_intraday_count(hours=4))
    selected = passed[:slots]
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
