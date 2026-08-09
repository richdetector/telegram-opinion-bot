from collections import Counter

from market_scorer import can_reach_selection
from verification import passes_publish_safety


DISCARD_REASONS = [
    "irrelevant",
    "low_materiality",
    "crypto_noise",
    "duplicate",
    "weak_source",
    "low_confidence",
    "already_discounted",
    "selector_rejected",
    "reviewer_rejected",
]


def empty_discard_counter():
    return Counter({reason: 0 for reason in DISCARD_REASONS})


def market_discard_reason(item):
    if item.asset_class == "UNKNOWN" and item.event_type == "UNKNOWN":
        return "irrelevant"

    if item.materiality == "LOW":
        if item.asset_class == "CRYPTO" or item.crypto_asset:
            return "crypto_noise"
        return "low_materiality"

    if not can_reach_selection(item):
        return "low_materiality"

    if item.source_type == "COMMUNITY" and item.verification_status != "CONFIRMED":
        return "weak_source"

    if item.confidence == "Baja" and item.materiality != "CRITICAL":
        return "low_confidence"

    if item.discountedness == "HIGH" and item.materiality != "CRITICAL":
        return "already_discounted"

    return "irrelevant"


def count_market_discards(news):
    counters = empty_discard_counter()

    for item in news:
        if not can_reach_selection(item):
            counters[market_discard_reason(item)] += 1

    return counters


def count_selector_rejections(candidates, selected):
    selected_links = {item.link for item in selected}

    return sum(
        1
        for item in candidates
        if item.link not in selected_links
        and passes_publish_safety(item)
    )


def format_discard_counters(counters):
    lines = []

    for reason in DISCARD_REASONS:
        lines.append(f"{reason}: {counters.get(reason, 0)}")

    return "\n".join(lines)
