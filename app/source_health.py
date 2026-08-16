from datetime import datetime
from urllib.request import Request, urlopen

import feedparser

from config import RSS_TIMEOUT_SECONDS


FEED_REQUEST_HEADERS = {
    "User-Agent": "RadarMarketIntelligence/1.0 (+https://example.com; RSS health check)"
}


def _fetch_feed(url):
    request = Request(url, headers=FEED_REQUEST_HEADERS)
    with urlopen(request, timeout=RSS_TIMEOUT_SECONDS) as response:
        return response.read()


def check_rss_sources(feeds, limit=None):
    results = []
    selected_feeds = feeds[:limit] if limit else feeds

    for feed_info in selected_feeds:
        result = {
            "source": feed_info["name"],
            "url": feed_info["url"],
            "status": None,
            "last_success": None,
            "last_error": "",
            "entries": 0,
            "error_count": 0,
        }

        try:
            parsed = feedparser.parse(_fetch_feed(feed_info["url"]))
            result["status"] = getattr(parsed, "status", None)
            result["entries"] = len(getattr(parsed, "entries", []) or [])

            exception = getattr(parsed, "bozo_exception", None)
            if result["entries"] > 0:
                result["last_success"] = datetime.utcnow().isoformat(timespec="seconds")
                result["last_error"] = type(exception).__name__ if exception else ""
            else:
                result["last_error"] = type(exception).__name__ if exception else "NO_ENTRIES"
                result["error_count"] = 1

        except Exception as exc:
            result["last_error"] = type(exc).__name__
            result["error_count"] = 1

        results.append(result)

    return results
