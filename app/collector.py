import feedparser
import trafilatura
from socket import timeout as SocketTimeout
from urllib.error import URLError
from urllib.request import Request, urlopen

from config import ARTICLE_TIMEOUT_SECONDS, RSS_TIMEOUT_SECONDS
from feeds_fixed import RSS_FEEDS
from models import NewsItem
from sources_registry import apply_source_metadata


MAX_CONTENT_LENGTH = 3000
FEED_REQUEST_HEADERS = {
    "User-Agent": "RadarMarketIntelligence/1.0 (+https://example.com; RSS health check)"
}


def _is_timeout_exception(exc):
    if isinstance(exc, (TimeoutError, SocketTimeout)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (TimeoutError, SocketTimeout))


def _fetch_bytes(url, timeout, headers=None):
    request = Request(
        url,
        headers=headers or FEED_REQUEST_HEADERS,
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def extract_content(url, diagnostics=None):

    try:

        downloaded = _fetch_bytes(
            url,
            timeout=ARTICLE_TIMEOUT_SECONDS,
            headers=FEED_REQUEST_HEADERS,
        )

        if not downloaded:
            return ""

        text = trafilatura.extract(
            downloaded.decode("utf-8", errors="replace"),
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

    except Exception as exc:
        if diagnostics is not None and _is_timeout_exception(exc):
            diagnostics["article_timeout"] += 1

        return ""


def get_news(limit_per_feed=10, diagnostics=None, seen_cache=None):

    news = []

    seen_links = set()

    for feed_info in RSS_FEEDS:

        try:
            payload = _fetch_bytes(
                feed_info["url"],
                timeout=RSS_TIMEOUT_SECONDS,
                headers=FEED_REQUEST_HEADERS,
            )
            feed = feedparser.parse(payload)
        except Exception as exc:
            if diagnostics is not None and _is_timeout_exception(exc):
                diagnostics["rss_timeout"] += 1
                if seen_cache:
                    seen_cache.increment_source(feed_info["name"], "timeouts")
            elif seen_cache:
                seen_cache.increment_source(feed_info["name"], "errors")
            print(f"⚠️ RSS {feed_info['name']}: {type(exc).__name__}", flush=True)
            continue

        source_state = seen_cache.get_source_state(feed_info["name"]) if seen_cache else {}
        last_seen_entry_id = source_state.get("last_seen_entry_id", "")
        newest_entry_id = ""
        newest_published = ""
        latest_urls = []

        for entry in feed.entries[:limit_per_feed]:

            link = getattr(entry, "link", "").strip()
            entry_id = (getattr(entry, "id", "") or link).strip()

            if not link:
                continue
            if not newest_entry_id:
                newest_entry_id = entry_id
                newest_published = getattr(entry, "published", "").strip()
            latest_urls.append(link)
            if last_seen_entry_id and entry_id == last_seen_entry_id:
                break

            if link in seen_links:
                continue

            seen_links.add(link)

            item = NewsItem(
                title=getattr(entry, "title", "").strip(),
                summary=getattr(entry, "summary", "").strip(),
                content="",
                link=link,
                published=getattr(entry, "published", "").strip(),
                source=feed_info["name"],
            )

            news.append(apply_source_metadata(item))

        if seen_cache and newest_entry_id:
            seen_cache.update_source_state(
                feed_info["name"],
                entry_id=newest_entry_id,
                published=newest_published,
                latest_urls=",".join(latest_urls[:20]),
            )

    return news


def enrich_news(news, diagnostics=None):

    enriched = []

    for item in news:

        content = extract_content(item.link, diagnostics=diagnostics)

        if not content:
            content = item.summary

        item.content = content

        enriched.append(item)

    return enriched
