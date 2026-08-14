from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser

from models import NewsItem
from sources_registry import apply_source_metadata


TRUTH_SOCIAL_STATUS = "UNAVAILABLE_FREE_SOURCE"
TRUTH_SOCIAL_ACCOUNTS = ["realDonaldTrump"]

MARKET_SENSITIVE_TERMS = [
    "tariff",
    "tariffs",
    "fed",
    "interest rates",
    "china",
    "sanctions",
    "oil",
    "iran",
    "strait of hormuz",
    "hormuz",
    "war",
    "nato",
    "russia",
    "ukraine",
    "taiwan",
    "treasury",
    "dollar",
    "bitcoin",
    "crypto regulation",
    "crypto",
    "sec",
    "taxes",
    "trade policy",
    "semiconductors",
    "energy",
    "fiscal policy",
]


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        return " ".join(part.strip() for part in self.parts if part.strip())


@dataclass
class TruthSocialPost:
    account: str
    text: str
    url: str = ""
    created_at: str = ""
    post_id: str = ""
    raw_status: str = "UNKNOWN"


@dataclass
class TruthSocialStatus:
    status: str = TRUTH_SOCIAL_STATUS
    posts_read: int = 0
    market_sensitive_posts: int = 0
    latest_relevant_declaration: str = ""
    errors: list[str] = field(default_factory=list)


def html_to_text(value):
    parser = _HTMLTextExtractor()
    parser.feed(value or "")
    return parser.text()


def is_market_sensitive(text):
    text = (text or "").lower()
    return any(term in text for term in MARKET_SENSITIVE_TERMS)


def classify_declaration_status(text):
    text = (text or "").lower()

    if any(term in text for term in ["deny", "denied", "not true", "fake news"]):
        return "DENIED"
    if any(term in text for term in ["effective immediately", "has been implemented", "implemented", "signed into law"]):
        return "IMPLEMENTED"
    if any(term in text for term in ["if ", "unless", "may impose", "could impose", "threaten", "threatens"]):
        return "THREATENED"
    if any(term in text for term in ["will impose", "will put", "will announce", "i am announcing", "we are announcing"]):
        return "ANNOUNCED"
    if any(term in text for term in ["propose", "proposal", "considering", "studying"]):
        return "PROPOSED"

    return "UNKNOWN"


def normalize_truth_social_status(raw, account="realDonaldTrump"):
    content = raw.get("content") or raw.get("text") or ""
    text = html_to_text(content) if "<" in content and ">" in content else content.strip()

    return TruthSocialPost(
        account=account,
        text=text,
        url=raw.get("url") or raw.get("uri") or "",
        created_at=raw.get("created_at") or "",
        post_id=str(raw.get("id") or ""),
        raw_status=classify_declaration_status(text),
    )


def truth_post_to_news_item(post):
    item = NewsItem(
        title=post.text[:220],
        summary=post.text[:500],
        content=post.text,
        link=post.url or f"truthsocial://{post.account}/{post.post_id}",
        published=post.created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source=f"Truth Social @{post.account}",
        category="Truth Social",
    )
    item.declaration_status = post.raw_status
    item.verification_status = post.raw_status if post.raw_status != "UNKNOWN" else "PRELIMINARY"
    item.is_rumor = post.raw_status in {"THREATENED", "PROPOSED", "UNKNOWN"}
    item.confidence = "Media" if post.raw_status in {"ANNOUNCED", "THREATENED", "PROPOSED"} else "Baja"
    item.primary_source = item.source
    item.intelligence_summary["truth_social"] = {
        "account": post.account,
        "declaration_status": post.raw_status,
        "confirmed_declaration": True,
        "policy_implemented": post.raw_status == "IMPLEMENTED",
    }
    return apply_source_metadata(item)


def get_truth_social_news():
    status = TruthSocialStatus(
        status=TRUTH_SOCIAL_STATUS,
        errors=["Truth Social has no free stable public API configured for Radar."],
    )
    return [], status


def summarize_truth_posts(posts):
    relevant = [post for post in posts if is_market_sensitive(post.text)]
    latest = relevant[0].text[:180] if relevant else ""
    return TruthSocialStatus(
        status="OK",
        posts_read=len(posts),
        market_sensitive_posts=len(relevant),
        latest_relevant_declaration=latest,
    )
