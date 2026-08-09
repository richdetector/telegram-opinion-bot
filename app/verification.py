from collections import defaultdict


STATUS_RANK = {
    "RUMOR": 0,
    "UNCONFIRMED": 1,
    "PRELIMINARY": 2,
    "CONFIRMED": 3,
    "DENIED": -1,
}


def _topic_key(item):
    assets = "-".join(sorted(item.affected_assets[:4])) or "NOASSET"
    topic = item.editorial_topic or item.event_type or item.category
    title_words = " ".join(item.title.lower().split()[:8])
    return f"{item.event_type}:{assets}:{topic}:{title_words[:80]}"


def verify_news(news):
    groups = defaultdict(list)
    for item in news:
        groups[_topic_key(item)].append(item)

    for related in groups.values():
        source_types = {item.source_type for item in related}
        sources = sorted({item.source for item in related})
        has_primary = "PRIMARY" in source_types
        has_high_reliability = "HIGH_RELIABILITY" in source_types
        independent_sources = len(sources)

        for item in related:
            item.related_sources = [source for source in sources if source != item.source]

            if has_primary:
                item.verification_status = "CONFIRMED"
                item.is_confirmed = True
                item.confidence = "Alta"
                item.primary_source = next(
                    (candidate.source for candidate in related if candidate.source_type == "PRIMARY"),
                    item.primary_source,
                )
            elif has_high_reliability and independent_sources >= 2:
                item.verification_status = "CONFIRMED"
                item.is_confirmed = True
                item.confidence = "Alta"
            elif item.source_type == "HIGH_RELIABILITY":
                item.verification_status = "PRELIMINARY" if item.is_rumor else "CONFIRMED"
                item.is_confirmed = not item.is_rumor
                item.confidence = "Media" if item.is_rumor else "Alta"
            elif independent_sources >= 2 and item.source_type != "COMMUNITY":
                item.verification_status = "PRELIMINARY"
                item.confidence = "Media"
            elif item.is_rumor:
                item.verification_status = "RUMOR"
                item.confidence = "Baja"
            else:
                item.verification_status = "UNCONFIRMED"
                item.confidence = "Baja"

    return news


def passes_publish_safety(item):
    if item.market_impact < 72:
        return False
    if item.materiality not in {"HIGH", "CRITICAL"}:
        return False
    if item.confidence == "Baja" and item.materiality != "CRITICAL":
        return False
    if item.source_type == "COMMUNITY" and item.verification_status != "CONFIRMED":
        return False
    if item.verification_status == "RUMOR" and item.market_impact < 90:
        return False
    return True
