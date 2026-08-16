import base64
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import (
    MARKET_DATA_TIMEOUT_SECONDS,
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_USER_AGENT,
)
from models import NewsItem
from sources_registry import apply_source_metadata


REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API_BASE = "https://oauth.reddit.com"
REDDIT_DISABLED_STATUS = "DISABLED_PENDING_APPROVAL"
REDDIT_SUBREDDITS = [
    "Bitcoin",
    "CryptoCurrency",
    "ethereum",
    "investing",
    "stocks",
    "wallstreetbets",
    "Economics",
    "worldnews",
    "geopolitics",
    "OpenAI",
    "LocalLLaMA",
    "MachineLearning",
    "technology",
]

NOISE_TERMS = [
    "meme",
    "memes",
    "shitpost",
    "shitposting",
    "to the moon",
    "diamond hands",
    "wen moon",
    "giveaway",
    "airdrop",
]


@dataclass
class RedditPost:
    subreddit: str
    title: str
    selftext: str = ""
    permalink: str = ""
    score: int = 0
    num_comments: int = 0
    created_utc: float | None = None
    flair: str = ""
    author: str = ""
    upvote_ratio: float | None = None


@dataclass
class RedditStatus:
    status: str = "UNKNOWN"
    posts_read: int = 0
    posts_accepted: int = 0
    top_narratives: list[str] = field(default_factory=list)
    attention: str = "UNKNOWN"
    sentiment: str = "UNKNOWN"
    errors: list[str] = field(default_factory=list)


class RedditClient:
    def __init__(
        self,
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
        timeout=MARKET_DATA_TIMEOUT_SECONDS,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.timeout = timeout
        self._token = None
        self._token_expires = 0

    def configured(self):
        return bool(self.client_id and self.client_secret and self.user_agent)

    def approved(self):
        return False

    def token(self):
        if not self.configured():
            raise RuntimeError("REDDIT_NOT_CONFIGURED")
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        credentials = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        auth = base64.b64encode(credentials).decode("ascii")
        data = urlencode({"grant_type": "client_credentials"}).encode("utf-8")
        request = Request(
            REDDIT_TOKEN_URL,
            data=data,
            headers={
                "Authorization": f"Basic {auth}",
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self._token = payload["access_token"]
        self._token_expires = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    def subreddit_new(self, subreddit, limit=25):
        token = self.token()
        query = urlencode({"limit": limit, "raw_json": 1})
        request = Request(
            f"{REDDIT_API_BASE}/r/{subreddit}/new?{query}",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": self.user_agent,
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def normalize_reddit_post(raw):
    data = raw.get("data", raw)
    return RedditPost(
        subreddit=data.get("subreddit") or "",
        title=(data.get("title") or "").strip(),
        selftext=(data.get("selftext") or "").strip(),
        permalink=f"https://www.reddit.com{data.get('permalink') or ''}",
        score=int(data.get("score") or 0),
        num_comments=int(data.get("num_comments") or 0),
        created_utc=data.get("created_utc"),
        flair=data.get("link_flair_text") or "",
        author=data.get("author") or "",
        upvote_ratio=data.get("upvote_ratio"),
    )


def _is_deleted(value):
    return value in {"[deleted]", "[removed]"}


def _is_noise(post):
    text = f"{post.title} {post.selftext} {post.flair}".lower()
    if not post.title or _is_deleted(post.title) or _is_deleted(post.selftext):
        return True
    if any(term in text for term in NOISE_TERMS):
        return True
    if len(post.title) < 18:
        return True
    return False


def accept_reddit_post(post, now=None, max_age_hours=12):
    now = now or datetime.now(timezone.utc).timestamp()
    if post.created_utc and now - float(post.created_utc) > max_age_hours * 3600:
        return False
    if _is_noise(post):
        return False

    min_comments = 8
    min_score = 20
    if post.subreddit.lower() in {"wallstreetbets", "cryptocurrency", "worldnews", "technology"}:
        min_comments = 25
        min_score = 50

    return post.score >= min_score or post.num_comments >= min_comments


def post_to_news_item(post):
    content = post.selftext[:2500]
    item = NewsItem(
        title=post.title[:220],
        summary=post.selftext[:500],
        content=content,
        link=post.permalink,
        published=datetime.fromtimestamp(
            float(post.created_utc or time.time()),
            tz=timezone.utc,
        ).isoformat(timespec="seconds"),
        source=f"r/{post.subreddit}",
        category="Reddit",
    )
    item.intelligence_summary["reddit"] = {
        "subreddit": post.subreddit,
        "score": post.score,
        "num_comments": post.num_comments,
        "flair": post.flair,
        "author": post.author,
        "upvote_ratio": post.upvote_ratio,
    }
    item.is_rumor = True
    item.verification_status = "RUMOR"
    item.confidence = "Baja"
    return apply_source_metadata(item)


def _narratives(posts):
    buckets = {
        "BTC": ["bitcoin", "btc", "etf", "reserve"],
        "ETH": ["ethereum", "eth", "staking"],
        "Fed/liquidity": ["fed", "rates", "liquidity", "inflation", "yield"],
        "AI/tech": ["openai", "llm", "nvidia", "ai", "semiconductor"],
        "Geopolitics": ["war", "sanction", "tariff", "oil", "china", "russia", "iran"],
    }
    scores = {}
    for post in posts:
        text = f"{post.title} {post.selftext}".lower()
        for name, terms in buckets.items():
            if any(term in text for term in terms):
                scores[name] = scores.get(name, 0) + 1 + min(post.num_comments, 100) / 100
    return [
        name
        for name, _ in sorted(scores.items(), key=lambda row: row[1], reverse=True)[:5]
    ]


def summarize_reddit(posts, accepted, errors=None, status="OK"):
    errors = errors or []
    total_comments = sum(post.num_comments for post in accepted)
    total_score = sum(max(post.score, 0) for post in accepted)
    subreddit_count = len({post.subreddit for post in accepted})

    if len(accepted) >= 15 and subreddit_count >= 4 and total_comments >= 600:
        attention = "EXTREME"
    elif len(accepted) >= 6 and subreddit_count >= 2 and total_comments >= 150:
        attention = "ELEVATED"
    elif accepted:
        attention = "LOW"
    else:
        attention = "UNKNOWN"

    bullish_terms = ["bullish", "breakout", "etf inflow", "all-time high", "risk-on"]
    bearish_terms = ["bearish", "panic", "crash", "recession", "liquidation", "risk-off"]
    bullish = 0
    bearish = 0
    for post in accepted:
        text = f"{post.title} {post.selftext}".lower()
        bullish += sum(term in text for term in bullish_terms)
        bearish += sum(term in text for term in bearish_terms)

    sentiment = "UNKNOWN"
    if bullish >= bearish + 4 and len(accepted) >= 4:
        sentiment = "EUPHORIC" if attention == "EXTREME" else "BULLISH"
    elif bearish >= bullish + 4 and len(accepted) >= 4:
        sentiment = "PANIC" if attention == "EXTREME" else "BEARISH"

    return RedditStatus(
        status=status,
        posts_read=len(posts),
        posts_accepted=len(accepted),
        top_narratives=_narratives(accepted),
        attention=attention,
        sentiment=sentiment,
        errors=errors,
    )


def get_reddit_news(limit_per_subreddit=12, client=None):
    client = client or RedditClient()
    approved = getattr(client, "approved", lambda: True)
    if not client.configured() or not approved():
        return [], RedditStatus(status=REDDIT_DISABLED_STATUS)

    posts = []
    accepted = []
    errors = []

    for subreddit in REDDIT_SUBREDDITS:
        try:
            payload = client.subreddit_new(subreddit, limit=limit_per_subreddit)
            children = payload.get("data", {}).get("children", [])
            for raw in children:
                post = normalize_reddit_post(raw)
                posts.append(post)
                if accept_reddit_post(post):
                    accepted.append(post)
        except HTTPError as exc:
            code = getattr(exc, "code", "")
            if code == 429:
                errors.append(f"r/{subreddit}:RATE_LIMIT")
                return [
                    post_to_news_item(post)
                    for post in accepted
                ], summarize_reddit(posts, accepted, errors, status="API_ERROR")
            errors.append(f"r/{subreddit}:HTTP_{code}")
        except Exception as exc:
            errors.append(f"r/{subreddit}:{type(exc).__name__}")

    deduped = []
    seen = set()
    for post in accepted:
        key = (post.title.lower(), post.permalink)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(post)

    return [
        post_to_news_item(post)
        for post in deduped
    ], summarize_reddit(posts, deduped, errors, status="OK" if not errors else "API_ERROR")
