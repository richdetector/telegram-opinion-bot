from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from history import recent_history
from publication_gate import mechanism_strength


DAILY_NEWS_MIN_RELEVANCE = 76
DAILY_MAX_AGE_HOURS = 36
DAILY_MAX_PER_DAY = 2

DAILY_REJECT_REASONS = [
    "not_daily_news",
    "reviewer_failed",
    "low_daily_relevance",
    "stale_news",
    "untraceable_source",
    "weak_asset_link",
    "weak_mechanism",
    "duplicate",
    "frequency_limit",
]


@dataclass
class DailyGateResult:
    item: object
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _parse_date(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_hours(item):
    published = _parse_date(item.published)
    if published is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - published).total_seconds() / 3600)


def _recent_daily_count(hours=24):
    cutoff = datetime.now() - timedelta(hours=hours)
    count = 0
    for row in recent_history(days=1):
        try:
            when = datetime.strptime(row.get("date", ""), "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if when >= cutoff and row.get("category") in {"BTC Hoy", "Market Daily"}:
            count += 1
    return count


def _has_traceable_source(item):
    return bool(item.source and (item.link or item.primary_source or item.related_sources))


def evaluate_daily_item(item, review_ok=True, duplicate_keys=None):
    duplicate_keys = duplicate_keys or set()
    reasons = []

    if item.daily_news_relevance < DAILY_NEWS_MIN_RELEVANCE:
        reasons.append("low_daily_relevance")

    if item.event_type == "BTC_INTRADAY_MOVE":
        reasons.append("not_daily_news")

    if not review_ok:
        reasons.append("reviewer_failed")

    age = _age_hours(item)
    if age is not None and age > DAILY_MAX_AGE_HOURS:
        reasons.append("stale_news")

    if not _has_traceable_source(item):
        reasons.append("untraceable_source")

    if not item.affected_assets:
        reasons.append("weak_asset_link")

    if mechanism_strength(item) not in {"DIRECT", "STRONG_SECOND_ORDER"}:
        reasons.append("weak_mechanism")

    if item.link in duplicate_keys or item.duplicate:
        reasons.append("duplicate")

    item.final_decision = "PASS" if not reasons else "FAIL"
    item.final_reject_reasons = sorted(set(reasons))
    return DailyGateResult(item=item, passed=not reasons, reasons=item.final_reject_reasons)


def apply_daily_publication_gate(items, review):
    review_ok = bool(review.get("ok"))
    results = [
        evaluate_daily_item(item, review_ok=review_ok)
        for item in items
        if item.daily_news_relevance >= DAILY_NEWS_MIN_RELEVANCE
    ]

    passed = [result.item for result in results if result.passed]
    slots = max(0, DAILY_MAX_PER_DAY - _recent_daily_count(hours=24))
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
