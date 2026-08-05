import feedparser
import trafilatura

from feeds_fixed import RSS_FEEDS
from models import NewsItem


MAX_CONTENT_LENGTH = 3000


def extract_content(url):

    try:

        downloaded = trafilatura.fetch_url(url)

        if not downloaded:
            return ""

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
        )

        if not text:
            return ""

        text = text.strip()

        if len(text) > MAX_CONTENT_LENGTH:

            text = text[:MAX_CONTENT_LENGTH]

            last_dot = text.rfind(".")

            if last_dot > 1000:
                text = text[:last_dot + 1]

        return text

    except Exception:

        return ""


def get_news(limit_per_feed=10):

    news = []

    seen_links = set()

    for feed_info in RSS_FEEDS:

        feed = feedparser.parse(feed_info["url"])

        for entry in feed.entries[:limit_per_feed]:

            link = getattr(entry, "link", "").strip()

            if not link:
                continue

            if link in seen_links:
                continue

            seen_links.add(link)

            news.append(
                NewsItem(
                    title=getattr(entry, "title", "").strip(),
                    summary=getattr(entry, "summary", "").strip(),
                    content="",
                    link=link,
                    published=getattr(entry, "published", "").strip(),
                    source=feed_info["name"],
                )
            )

    return news


def enrich_news(news):

    enriched = []

    for item in news:

        content = extract_content(item.link)

        if not content:
            content = item.summary

        item.content = content

        enriched.append(item)

    return enriched