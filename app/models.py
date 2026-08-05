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