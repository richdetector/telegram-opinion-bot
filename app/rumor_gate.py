from dataclasses import dataclass, field

from publication_gate import mechanism_strength


RELEVANT_DECLARATION_SOURCES = {
    "Truth Social @realDonaldTrump",
    "Federal Reserve - Monetary Policy",
    "Federal Reserve - All Press Releases",
    "SEC - Press Releases",
    "TreasuryDirect - Auction Announcements",
    "Banco Central Europeo",
}

RUMOR_STATES = {
    "RUMOR",
    "UNCONFIRMED",
    "PRELIMINARY",
    "ANNOUNCED",
    "THREATENED",
    "PROPOSED",
}


@dataclass
class RumorGateConfig:
    min_market_impact: int = 85
    min_materiality: str = "HIGH"
    allow_critical_single_relevant_source: bool = True


@dataclass
class RumorGateResult:
    item: object
    passed: bool
    reasons: list[str] = field(default_factory=list)
    rumor_score: int = 0


def _materiality_ok(item):
    return item.materiality in {"HIGH", "CRITICAL"}


def _source_relevance(item):
    if item.source in RELEVANT_DECLARATION_SOURCES:
        return 35
    if item.source_type == "PRIMARY":
        return 30
    if item.source_type == "HIGH_RELIABILITY":
        return 24
    if item.source_type == "FAST":
        return 16
    return 5


def _traceability(item):
    if item.link and item.source:
        if item.link.startswith("truthsocial://") or item.link.startswith("http"):
            return 18
    return 0


def _independent_sources(item):
    sources = {item.source}
    sources.update(item.related_sources or [])
    return len([source for source in sources if source])


def rumor_score(item):
    score = 0
    score += _source_relevance(item)
    score += _traceability(item)
    score += min(20, max(0, item.market_impact - 65))

    if item.materiality == "CRITICAL":
        score += 12
    elif item.materiality == "HIGH":
        score += 8

    if item.declaration_status in {"ANNOUNCED", "THREATENED", "PROPOSED"}:
        score += 12
    elif item.verification_status in {"RUMOR", "PRELIMINARY", "UNCONFIRMED"}:
        score += 4

    independent = _independent_sources(item)
    if independent >= 2:
        score += min(12, independent * 4)

    if item.market_signals:
        score += 6

    if item.verification_status == "DENIED" or item.declaration_status == "DENIED":
        score -= 50

    return max(0, min(100, int(score)))


def evaluate_rumor_item(item, review_ok=True, config=None):
    config = config or RumorGateConfig()
    reasons = []
    score = rumor_score(item)
    mechanism = mechanism_strength(item)

    if not review_ok:
        reasons.append("reviewer_failed")
    if item.market_impact < config.min_market_impact:
        reasons.append("low_market_impact")
    if not _materiality_ok(item):
        reasons.append("low_materiality")
    if item.verification_status not in RUMOR_STATES and item.declaration_status not in RUMOR_STATES:
        reasons.append("not_rumor_or_declaration")
    if item.verification_status == "DENIED" or item.declaration_status == "DENIED":
        reasons.append("denied")
    if _traceability(item) == 0:
        reasons.append("no_traceability")
    if mechanism not in {"DIRECT", "STRONG_SECOND_ORDER"}:
        reasons.append("weak_mechanism")
    if not item.affected_assets:
        reasons.append("weak_asset_link")
    if _source_relevance(item) < 16:
        reasons.append("weak_source")
    if score < 70:
        reasons.append("low_rumor_score")

    if (
        item.materiality == "CRITICAL"
        and item.source in RELEVANT_DECLARATION_SOURCES
        and config.allow_critical_single_relevant_source
    ):
        reasons = [
            reason
            for reason in reasons
            if reason not in {"low_rumor_score", "not_rumor_or_declaration"}
        ]

    item.rumor_score = score
    if reasons:
        item.final_decision = "FAIL"
        item.final_reject_reasons = sorted(set(item.final_reject_reasons + reasons))
    else:
        item.final_decision = "RUMOR_PASS"
        item.final_reject_reasons = []

    return RumorGateResult(
        item=item,
        passed=not reasons,
        reasons=sorted(set(reasons)),
        rumor_score=score,
    )


def apply_rumor_gate(items, review):
    review_ok = bool(review.get("ok"))
    results = [
        evaluate_rumor_item(item, review_ok=review_ok)
        for item in items
    ]
    return [result.item for result in results if result.passed], results


def event_update_type(previous_status, current_status):
    if previous_status == current_status:
        return None
    if previous_status in {"THREATENED", "ANNOUNCED"} and current_status == "IMPLEMENTED":
        return "IMPLEMENTED"
    if current_status == "DENIED":
        return "DENIED"
    if previous_status in {"RUMOR", "UNCONFIRMED", "PRELIMINARY", "THREATENED", "PROPOSED"} and current_status in {"CONFIRMED", "CONFIRMED_POLICY", "IMPLEMENTED"}:
        return "CONFIRMED"
    return "STATUS_CHANGED"
