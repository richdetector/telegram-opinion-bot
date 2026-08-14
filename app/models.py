from dataclasses import dataclass, field


@dataclass
class NewsItem:
    title: str
    summary: str
    content: str
    link: str
    published: str
    source: str

    score: int = 0
    category: str = "General"

    keywords: list[str] = field(default_factory=list)

    editorial_topic: str = ""
    why_high_score: str = ""

    impact_spain: int = 0
    language: str = ""
    duplicate: bool = False

    event_type: str = "UNKNOWN"
    affected_assets: list[str] = field(default_factory=list)
    asset_class: str = "UNKNOWN"
    market_impact: int = 0
    impact_horizon: str = "UNKNOWN"
    source_type: str = "BACKGROUND"
    source_reliability: int = 40
    source_speed: int = 40
    is_rumor: bool = False
    is_confirmed: bool = False
    confidence: str = "Baja"
    verification_status: str = "UNCONFIRMED"
    primary_source: str = ""
    related_sources: list[str] = field(default_factory=list)
    geographic_scope: str = "UNKNOWN"
    macro_driver: str = ""
    crypto_asset: str = ""
    materiality: str = "LOW"
    mechanism: str = ""
    market_signals: list[str] = field(default_factory=list)
    intelligence_summary: dict = field(default_factory=dict)
    discountedness: str = "UNKNOWN"
    expected: str = ""
    actual: str = ""
    surprise: str = "UNKNOWN"
    confluence_score: int = 0
    evidence_level: str = "OBSERVED"
    mechanism_of_impact: str = "UNKNOWN"
    editorial_quality: int = 0
    final_decision: str = "PENDING"
    final_reject_reasons: list[str] = field(default_factory=list)
    declaration_status: str = "UNKNOWN"
    rumor_score: int = 0
    update_of: str = ""


@dataclass
class NewsAnalysis:
    id: int
    title: str
    key: str
    what_happened: str
    why_it_matters: str
    impact_spain: str
    what_to_watch: str
    opinion: str
    confidence: str


@dataclass
class EditorialReport:
    analyses: list[NewsAnalysis] = field(default_factory=list)
