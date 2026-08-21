from dataclasses import dataclass, field


LANE_PRIORITY = {
    "STRUCTURAL": 100,
    "INTRADAY_ALERT": 90,
    "DAILY_NEWS": 80,
    "COMBINED_STORY": 78,
    "RUMOR": 72,
    "DAILY_MARKET_RECAP": 65,
    "INTRADAY_NOTE": 60,
    "QUIET_MARKET": 10,
}

DIRECT_LANES = {
    "INTRADAY_ALERT",
    "INTRADAY_NOTE",
    "DAILY_MARKET_RECAP",
    "DAILY_NEWS",
    "RUMOR",
    "COMBINED_STORY",
    "QUIET_MARKET",
}

MARKET_STATE_LANES = {
    "INTRADAY_ALERT",
    "INTRADAY_NOTE",
    "DAILY_MARKET_RECAP",
    "QUIET_MARKET",
}


@dataclass
class EditorialCandidate:
    item: object
    lane: str
    priority: int
    candidate_id: str = ""
    headline_seed: str = ""
    source_items: list = field(default_factory=list)
    dedupe_key: str = ""
    publication_policy: str = ""


def intraday_decision(item):
    return (getattr(item, "intelligence_summary", {}) or {}).get("INTRADAY_DECISION", "")


def lane_for_item(item):
    if getattr(item, "category", "") == "Quiet Market Note" or getattr(item, "event_type", "") == "QUIET_MARKET_STATE":
        return "QUIET_MARKET"
    if getattr(item, "event_type", "") == "BTC_INTRADAY_MOVE":
        decision = intraday_decision(item)
        if decision == "INTRADAY_ALERT":
            return "INTRADAY_ALERT"
        if decision == "INTRADAY_NOTE":
            return "INTRADAY_NOTE"
    if getattr(item, "event_type", "") == "BTC_DAILY_RECAP":
        return "DAILY_MARKET_RECAP"
    if getattr(item, "event_type", "") == "COMBINED_MARKET_STORY":
        return "COMBINED_STORY"
    if (
        getattr(item, "verification_status", "") == "RUMOR"
        or getattr(item, "is_rumor", False)
        or getattr(item, "declaration_status", "") in {"THREATENED", "PROPOSED", "ANNOUNCED"}
    ):
        return "RUMOR"
    if getattr(item, "daily_news_relevance", 0) >= 76:
        return "DAILY_NEWS"
    return "STRUCTURAL"


def lane_priority(item):
    lane = lane_for_item(item)
    if getattr(item, "materiality", "") == "CRITICAL":
        return max(100, LANE_PRIORITY.get(lane, 50))
    return LANE_PRIORITY.get(lane, 50)


def is_market_state_candidate(item):
    return lane_for_item(item) in MARKET_STATE_LANES or str(getattr(item, "link", "")).startswith("market-state:")


def needs_article_download(item):
    link = str(getattr(item, "link", "") or "")
    if is_market_state_candidate(item):
        return False
    return link.startswith("http://") or link.startswith("https://")


def needs_ai_enrichment(item):
    return not is_market_state_candidate(item)


def selector_required(item):
    return lane_for_item(item) == "STRUCTURAL"


def direct_lane_item(item):
    return lane_for_item(item) in DIRECT_LANES


def candidate_from_item(item):
    lane = lane_for_item(item)
    return EditorialCandidate(
        item=item,
        lane=lane,
        priority=lane_priority(item),
        candidate_id=str(getattr(item, "link", "") or getattr(item, "title", "")),
        headline_seed=getattr(item, "title", ""),
        source_items=[item],
        dedupe_key=str(getattr(item, "link", "") or getattr(item, "title", "")),
        publication_policy=lane,
    )


def sort_for_publication(items):
    return sorted(
        items,
        key=lambda item: (
            lane_priority(item),
            max(
                getattr(item, "market_impact", 0),
                getattr(item, "daily_news_relevance", 0),
                getattr(item, "intraday_news_relevance", 0),
                getattr(item, "rumor_relevance", 0),
                getattr(item, "confluence_score", 0),
            ),
            getattr(item, "source_reliability", 0),
        ),
        reverse=True,
    )


def split_selector_lanes(items):
    structural = [item for item in items if selector_required(item)]
    direct = [item for item in items if not selector_required(item)]
    return structural, direct
