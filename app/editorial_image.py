from dataclasses import dataclass


@dataclass
class EditorialImageBrief:
    eligible: bool
    brief: str = ""
    reason: str = ""
    reuse_key: str = ""


def _text(item):
    return f"{item.title} {item.summary} {item.content}".lower()


def image_reuse_key(item):
    assets = "-".join(sorted(item.affected_assets or [])) or "NOASSET"
    topic = item.editorial_topic or item.event_type or item.category
    words = "-".join((item.title or "").lower().split()[:8])
    return f"{topic}:{assets}:{words}"


def is_image_eligible(item):
    text = _text(item)
    if item.category == "Market Note":
        return False
    if item.event_type == "BTC_DAILY_RECAP":
        return item.daily_news_relevance >= 76
    if item.event_type == "BTC_INTRADAY_MOVE":
        return item.confluence_score >= 58
    if any(term in text for term in ["trump", "clarity act", "white house", "sec", "cftc"]):
        return True
    if item.event_type in {"CENTRAL_BANK", "MACRO_DATA", "GEOPOLITICAL_MARKET", "CRYPTO_REGULATION"}:
        return getattr(item, "daily_news_relevance", 0) >= 76 or item.market_impact >= 65
    if item.event_type == "CRYPTO_MARKET_STRUCTURE" and "BTC" in item.affected_assets:
        return item.confluence_score >= 60
    return False


def build_image_brief(item):
    if not is_image_eligible(item):
        return EditorialImageBrief(False, reason="not_image_eligible")

    text = _text(item)
    base_style = (
        "Dark premium RADAR BTC editorial illustration, clean black financial-news visual, "
        "green market accents and orange Bitcoin highlights, modern, uncluttered, not a fake documentary photo."
    )

    if "trump" in text:
        brief = (
            "Editorial poster illustration of Donald Trump as a political market catalyst, "
            "Bitcoin-themed reflections in sunglasses, US Capitol silhouette, subtle BTC motifs, "
            "clearly illustrative rather than photorealistic documentary. "
            + base_style
        )
    elif "clarity act" in text or item.event_type == "CRYPTO_REGULATION":
        brief = (
            "Editorial illustration of US crypto regulation, Capitol silhouette, legal documents, "
            "Bitcoin symbol and market radar lines, no fake official document. "
            + base_style
        )
    elif item.event_type == "BTC_INTRADAY_MOVE":
        brief = (
            "Stylized Bitcoin radar visualization with candlesticks, liquidity zones, volume bars "
            "and momentum arrows, explicitly abstract market-data illustration. "
            + base_style
        )
    elif item.event_type == "BTC_DAILY_RECAP":
        brief = (
            "Stylized Bitcoin daily recap visual with a large BTC symbol, +24h move annotation, "
            "radar sweep, candlesticks, liquidity zones and clean market dashboard elements. "
            + base_style
        )
    elif item.event_type in {"CENTRAL_BANK", "MACRO_DATA"}:
        brief = (
            "Editorial macro-finance illustration with central bank building silhouette, yields, dollar, "
            "Bitcoin and risk-asset radar lines. "
            + base_style
        )
    else:
        brief = "Editorial market intelligence illustration. " + base_style

    return EditorialImageBrief(True, brief=brief, reason="eligible", reuse_key=image_reuse_key(item))


def generate_editorial_image(brief):
    return None


def prepare_editorial_image(item, generator=generate_editorial_image):
    brief = build_image_brief(item)
    item.image_eligible = brief.eligible
    item.image_brief = brief.brief
    if not brief.eligible:
        return None
    try:
        path = generator(brief.brief)
    except Exception:
        item.image_path = ""
        return None
    item.image_path = path or ""
    return path
