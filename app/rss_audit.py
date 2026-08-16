import argparse
from dataclasses import dataclass

from feeds_fixed import RSS_FEEDS
from seen_cache import SeenCache
from source_health import check_rss_sources


SOURCE_TIER_DEFAULTS = {
    "macro": "PRIMARY",
    "rates": "PRIMARY",
    "liquidity": "PRIMARY",
    "regulation": "PRIMARY",
    "energy": "PRIMARY",
    "markets": "HIGH_RELIABILITY",
    "crypto": "BACKGROUND",
    "geopolitics": "BACKGROUND",
    "world": "BACKGROUND",
    "systemic_company": "PRIMARY",
    "technology": "BACKGROUND",
}

SOURCE_PRIORITY_DEFAULTS = {
    "macro": "HIGH",
    "rates": "HIGH",
    "liquidity": "HIGH",
    "regulation": "HIGH",
    "energy": "HIGH",
    "markets": "NORMAL",
    "crypto": "NORMAL",
    "geopolitics": "NORMAL",
    "world": "LOW",
    "systemic_company": "NORMAL",
    "technology": "LOW",
}

ALWAYS_KEEP_PATTERNS = (
    "Federal Reserve",
    "BLS",
    "BEA",
    "SEC",
    "TreasuryDirect",
    "Banco Central Europeo",
    "ECB",
    "Eurostat",
    "EIA",
    "CFTC",
)


@dataclass
class SourceAuditRow:
    source: str
    tier: str
    priority: str
    status: str
    last_success: str
    new_24h: int
    new_7d: int
    duplicate_rate: float
    signal_rate: float
    error_rate: float
    errors: str
    recommendation: str


def feed_tier(feed):
    return feed.get("tier") or SOURCE_TIER_DEFAULTS.get(feed.get("category"), "BACKGROUND")


def feed_priority(feed):
    return feed.get("priority") or SOURCE_PRIORITY_DEFAULTS.get(feed.get("category"), "NORMAL")


def _by_source(rows):
    return {row.get("source"): row for row in rows or []}


def _rate(row, numerator):
    seen = row.get("items_seen") or 0
    if not seen:
        return 0.0
    return (row.get(numerator) or 0) / seen


def _is_critical_primary(feed):
    name = feed.get("name", "")
    if feed_tier(feed) == "PRIMARY" and feed_priority(feed) in {"CRITICAL", "HIGH"}:
        return True
    return any(pattern in name for pattern in ALWAYS_KEEP_PATTERNS)


def recommend_source(feed, perf_7d=None, health=None):
    perf_7d = perf_7d or {}
    health = health or {}

    if health.get("error_count"):
        return "FIX"

    if _is_critical_primary(feed):
        return "KEEP"

    seen = perf_7d.get("items_seen") or 0
    if seen < 10:
        return "WATCH"

    duplicate_rate = _rate(perf_7d, "duplicates")
    signal_rate = _rate(perf_7d, "precandidates") + _rate(perf_7d, "material_updates")
    error_rate = _rate(perf_7d, "errors") + _rate(perf_7d, "timeouts")

    if error_rate >= 0.5:
        return "DISABLE"
    if duplicate_rate >= 0.8 and signal_rate < 0.02:
        return "DOWNGRADE"
    if signal_rate >= 0.05:
        return "KEEP"
    if feed_priority(feed) == "LOW" and signal_rate == 0:
        return "DOWNGRADE"
    return "WATCH"


def audit_rss_sources(feeds=None, cache=None, check_live=False, limit=None):
    feeds = feeds or RSS_FEEDS
    cache = cache or SeenCache()
    selected_feeds = feeds[:limit] if limit else feeds

    perf_24h = _by_source(cache.source_performance_window(hours=24))
    perf_7d = _by_source(cache.source_performance_window(hours=24 * 7))
    aggregate = _by_source(cache.source_performance())
    health_by_source = {}

    if check_live:
        health = check_rss_sources(selected_feeds)
        health_by_source = _by_source(health)

    rows = []
    for feed in selected_feeds:
        name = feed["name"]
        p24 = perf_24h.get(name, {})
        p7 = perf_7d.get(name, aggregate.get(name, {}))
        aggregate_row = aggregate.get(name, {})
        health = health_by_source.get(name, {})
        status = "UNKNOWN"
        errors = ""

        if check_live:
            if health.get("error_count"):
                status = "UNHEALTHY"
                errors = health.get("last_error", "")
            elif health.get("entries", 0) > 0:
                status = "HEALTHY"
            else:
                status = "NO_ENTRIES"
                errors = health.get("last_error", "")
        elif aggregate_row:
            status = "MEASURED"

        last_success = health.get("last_success") or aggregate_row.get("last_success") or ""
        rows.append(
            SourceAuditRow(
                source=name,
                tier=feed_tier(feed),
                priority=feed_priority(feed),
                status=status,
                last_success=last_success,
                new_24h=p24.get("items_new") or 0,
                new_7d=p7.get("items_new") or 0,
                duplicate_rate=_rate(p7, "duplicates"),
                signal_rate=_rate(p7, "precandidates") + _rate(p7, "material_updates"),
                error_rate=_rate(p7, "errors") + _rate(p7, "timeouts"),
                errors=errors,
                recommendation=recommend_source(feed, perf_7d=p7, health=health),
            )
        )

    return rows


def format_rss_audit(rows):
    lines = [
        "RSS SOURCE AUDIT",
        "Source | Tier | Priority | Status | Last success | 24h new | 7d new | Duplicate rate | Signal rate | Errors | Recommendation",
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    row.source,
                    row.tier,
                    row.priority,
                    row.status,
                    row.last_success or "",
                    str(row.new_24h),
                    str(row.new_7d),
                    f"{row.duplicate_rate:.2f}",
                    f"{row.signal_rate:.2f}",
                    row.errors or f"{row.error_rate:.2f}",
                    row.recommendation,
                ]
            )
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Print Radar RSS source audit.")
    parser.add_argument("--live", action="store_true", help="Fetch feeds and include current health.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of feeds checked.")
    args = parser.parse_args()
    rows = audit_rss_sources(check_live=args.live, limit=args.limit)
    print(format_rss_audit(rows))


if __name__ == "__main__":
    main()
