from market_scorer import accepted_by_paths


NEWS_MARKET_REACTION_TERMS = [
    "clarity act",
    "crypto regulation",
    "bitcoin",
    "btc",
    "sec",
    "cftc",
    "trump",
    "white house",
    "treasury",
    "etf",
    "fed",
]


def _relevant_news(item):
    text = f"{item.title} {item.summary} {item.content}".lower()
    return any(term in text for term in NEWS_MARKET_REACTION_TERMS)


def _fmt(value, suffix=""):
    if value is None:
        return "UNKNOWN"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def attach_market_reaction_to_news(news, intraday_state):
    if intraday_state is None or intraday_state.decision not in {"INTRADAY_NOTE", "INTRADAY_ALERT"}:
        return news

    snapshot = intraday_state.snapshot
    reaction = (
        "Reaccion de mercado observable: "
        f"BTC 1h={_fmt(snapshot.price_change_1h, '%')}, "
        f"4h={_fmt(snapshot.price_change_4h, '%')}, "
        f"24h={_fmt(snapshot.price_change_24h, '%')}, "
        f"volumen 4h={_fmt(snapshot.volume_ratio_4h)}x, "
        f"OI 4h={_fmt(snapshot.oi_change_4h, '%')}. "
        "Esto coincide temporalmente con la noticia; no demuestra causalidad por si solo."
    )

    for item in news:
        if not _relevant_news(item):
            continue
        if "BTC" not in item.affected_assets and ("bitcoin" in item.title.lower() or "btc" in item.title.lower() or item.event_type == "CRYPTO_REGULATION"):
            item.affected_assets.append("BTC")
        item.content = "\n".join(part for part in [item.content, reaction] if part)
        if "TEMPORAL_MARKET_REACTION" not in item.market_signals:
            item.market_signals.append("TEMPORAL_MARKET_REACTION")
        item.daily_news_relevance = min(100, max(item.daily_news_relevance, 82))
        item.intraday_news_relevance = min(100, max(item.intraday_news_relevance, 84))
        item.confluence_score = min(100, max(item.confluence_score, intraday_state.intraday_confluence_score))
        item.impact_horizon = "INTRADAY_DAILY"
        item.accepted_by = accepted_by_paths(item)
        if "COMBINED_STORY" not in item.accepted_by:
            item.accepted_by.append("COMBINED_STORY")

    return news
