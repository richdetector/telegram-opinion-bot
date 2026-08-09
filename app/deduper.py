from collections import defaultdict


def story_key(item):
    assets = "-".join(sorted(item.affected_assets[:4])) or "NOASSET"
    event = item.event_type or "UNKNOWN"
    topic = item.editorial_topic or item.macro_driver or item.category

    if assets != "NOASSET" and event != "UNKNOWN":
        return f"{event}:{assets}:{topic}"

    words = [
        word
        for word in item.title.lower().split()
        if len(word) > 3
        and word
        not in {"says", "said", "after", "with", "from", "that", "this", "will"}
    ]
    return f"{event}:{assets}:{'-'.join(words[:8])}"


def dedupe_news(news):
    groups = defaultdict(list)
    for item in news:
        groups[story_key(item)].append(item)

    deduped = []

    for related in groups.values():
        related.sort(
            key=lambda item: (
                item.market_impact,
                item.source_reliability,
                item.source_speed,
            ),
            reverse=True,
        )

        winner = related[0]
        sources = sorted({item.source for item in related})
        winner.related_sources = [source for source in sources if source != winner.source]

        if len(related) > 1:
            winner.market_impact = min(100, winner.market_impact + min(8, len(related) * 2))
            winner.score = winner.market_impact

        deduped.append(winner)

    return deduped
