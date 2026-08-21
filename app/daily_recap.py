from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from config import DAILY_RECAP_MAX_PER_DAY, DAILY_RECAP_MIN_SCORE
from history import recent_history
from models import NewsItem


@dataclass
class DailyMarketContext:
    current_price: float | None = None
    change_24h: float | None = None
    max_abs_move_15m_24h: float | None = None
    max_abs_move_1h_24h: float | None = None
    max_abs_move_4h_24h: float | None = None
    peak_volume_ratio_24h: float | None = None
    peak_volatility_ratio_24h: float | None = None
    oi_change_1h: float | None = None
    oi_change_4h: float | None = None
    oi_daily_context: str = "UNKNOWN"
    funding: float | None = None
    structure_15m: str = "UNKNOWN"
    structure_1h: str = "UNKNOWN"
    structure_4h: str = "UNKNOWN"
    liquidity_context: str = "UNKNOWN"
    recent_relevant_events: list[dict] = field(default_factory=list)
    data_status: str = "INSUFFICIENT"
    trace: dict = field(default_factory=dict)


@dataclass
class DailyMarketRecapDecision:
    eligible: bool
    score: int = 0
    decision: str = "NO_RECAP"
    reason: str = ""
    duplicate: bool = False
    fingerprint: str = ""
    recent_events: list[dict] = field(default_factory=list)
    note: NewsItem | None = None
    published: bool = False
    context: DailyMarketContext | None = None


def _abs(value):
    return abs(value) if value is not None else 0


def _max_abs(values):
    values = [value for value in values if value is not None]
    return max([abs(value) for value in values] or [0])


def _max_value(values):
    values = [value for value in values if value is not None]
    return max(values or [0])


def _parse_history_date(value):
    try:
        return datetime.strptime(value or "", "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _recent_category_count(categories, hours=24):
    cutoff = datetime.now() - timedelta(hours=hours)
    count = 0
    for row in recent_history(days=1):
        when = _parse_history_date(row.get("date"))
        if when is None or when < cutoff:
            continue
        if row.get("status") == "published" and row.get("category") in categories:
            count += 1
    return count


def _recent_intraday_or_daily_covered(hours=6):
    return _recent_category_count(
        {"BTC Intraday", "BTC Intraday Note", "BTC Hoy", "BTC Today"},
        hours=hours,
    ) > 0


def _fmt(value, suffix=""):
    if value is None:
        return "UNKNOWN"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _memory_summary(rows, snapshot):
    rows = rows or []
    return {
        "max_move_15m_24h": _max_abs([row.get("price_change_15m") for row in rows] + [snapshot.price_change_15m]),
        "max_move_1h_24h": _max_abs([row.get("price_change_1h") for row in rows] + [snapshot.price_change_1h]),
        "max_move_4h_24h": _max_abs([row.get("price_change_4h") for row in rows] + [snapshot.price_change_4h]),
        "max_volume_ratio_24h": _max_value([row.get("volume_ratio_1h") for row in rows] + [row.get("volume_ratio_4h") for row in rows] + [snapshot.volume_ratio_1h, snapshot.volume_ratio_4h]),
        "max_volatility_ratio_24h": _max_value([row.get("volatility_ratio_1h") for row in rows] + [row.get("volatility_ratio_4h") for row in rows] + [snapshot.volatility_ratio_1h, snapshot.volatility_ratio_4h]),
        "max_oi_change_24h": _max_abs([row.get("oi_change_1h") for row in rows] + [row.get("oi_change_4h") for row in rows] + [snapshot.oi_change_1h, snapshot.oi_change_4h]),
        "important_structure_events": [
            row.get("structure_4h")
            for row in rows
            if row.get("structure_4h") in {"BULLISH_BREAKOUT", "BEARISH_BREAKOUT", "FAILED_BREAKOUT_UP", "FAILED_BREAKOUT_DOWN"}
        ],
        "intraday_events": [
            row.get("intraday_decision")
            for row in rows
            if row.get("intraday_decision") in {"INTRADAY_ALERT", "INTRADAY_NOTE"}
        ],
    }


def _first_known(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _btc_context_relevance(event):
    title = (event.get("title") or "").lower()
    source = (event.get("source") or "").lower()
    if any(term in title for term in ["kalshi", "prediction", "price target", "traders think"]):
        return 0
    score = 0
    if any(term in title for term in ["bitcoin", "btc"]):
        score += 32
    if any(term in title for term in ["clarity act", "clarity"]):
        score += 36
    if any(term in title for term in ["crypto regulation", "regulación cripto", "stablecoin", "etf"]):
        score += 30
    if any(term in title for term in ["sec", "cftc"]) and any(term in title for term in ["bitcoin", "btc", "crypto", "clarity", "stablecoin", "etf"]):
        score += 26
    if any(term in title for term in ["trump", "white house"]) and any(term in title for term in ["bitcoin", "btc", "crypto", "clarity", "sec", "cftc", "tariff", "fed", "treasury"]):
        score += 30
    if any(term in title for term in ["fed", "treasury", "liquidity", "yield", "dollar", "usd"]) and any(term in title for term in ["bitcoin", "btc", "crypto", "risk", "liquidity", "rates", "dollar", "usd"]):
        score += 18
    if any(term in source for term in ["coindesk", "sec", "cftc", "cnbc", "ultimominuto"]):
        score += 6
    if "committee" in title and not any(term in title for term in ["bitcoin", "btc", "crypto", "stablecoin", "clarity", "etf"]):
        score -= 30
    return max(0, min(100, score))


def _filter_recent_events_for_btc_context(events):
    filtered = []
    for event in events or []:
        relevance = _btc_context_relevance(event)
        if relevance < 40:
            continue
        enriched = dict(event)
        enriched["btc_context_relevance"] = relevance
        filtered.append(enriched)
    return sorted(filtered, key=lambda item: item.get("btc_context_relevance", 0), reverse=True)


def _oi_context(oi_1h, oi_4h):
    if oi_4h is None and oi_1h is None:
        return "UNKNOWN"
    strongest = oi_4h if oi_4h is not None else oi_1h
    if strongest is None:
        return "UNKNOWN"
    if strongest <= -4:
        return "LEVERAGE_RESET"
    if strongest <= -0.25:
        return "OI_COOLING"
    if strongest >= 4:
        return "LEVERAGE_BUILDUP"
    if strongest >= 0.25:
        return "OI_RISING"
    return "STABLE"


def _liquidity_context(snapshot):
    liquidity = getattr(snapshot, "liquidity", None)
    if liquidity is None:
        return "UNKNOWN"
    parts = []
    if getattr(liquidity, "nearest_visible_above", None) is not None:
        parts.append("VISIBLE_LIQUIDITY_ABOVE")
    if getattr(liquidity, "nearest_visible_below", None) is not None:
        parts.append("VISIBLE_LIQUIDITY_BELOW")
    if getattr(liquidity, "liquidity_imbalance", "UNKNOWN") != "UNKNOWN":
        parts.append(getattr(liquidity, "liquidity_imbalance"))
    return ", ".join(parts) if parts else "UNKNOWN"


def build_daily_market_context(btc_market_state, seen_cache=None):
    trace = {
        "market_snapshot_24h": None,
        "intraday_24h": None,
        "resolved_24h": None,
        "rolling_1h_peak": None,
        "rolling_4h_peak": None,
        "rolling_volume_peak": None,
        "oi_raw": None,
        "oi_context": "UNKNOWN",
        "structure_raw": None,
        "structure_resolved": "UNKNOWN",
        "events_before_filter": 0,
        "events_after_filter": 0,
        "daily_score": 0,
        "decision": "NO_RECAP",
    }
    if btc_market_state is None or getattr(btc_market_state, "intraday", None) is None:
        return DailyMarketContext(trace=trace)

    intraday = btc_market_state.intraday
    snapshot = intraday.snapshot
    market_snapshot = getattr(btc_market_state, "snapshot", None)
    if seen_cache:
        seen_cache.remember_btc_intraday_snapshot(intraday)
        memory_rows = seen_cache.btc_daily_memory(hours=24)
        recent_events_raw = seen_cache.get_recent_relevant_events(hours=24)
    else:
        memory_rows = []
        recent_events_raw = []

    memory = _memory_summary(memory_rows, snapshot)
    recent_events = _filter_recent_events_for_btc_context(recent_events_raw)
    market_24h = getattr(market_snapshot, "price_change_24h", None)
    intraday_24h = getattr(snapshot, "price_change_24h", None)
    resolved_24h = _first_known(intraday_24h, market_24h)
    current_price = _first_known(getattr(snapshot, "price", None), getattr(market_snapshot, "price", None))
    max_15m = _first_known(getattr(snapshot, "max_abs_move_15m_24h", None), memory.get("max_move_15m_24h"))
    max_1h = _first_known(getattr(snapshot, "max_abs_move_1h_24h", None), memory.get("max_move_1h_24h"))
    max_4h = _first_known(getattr(snapshot, "max_abs_move_4h_24h", None), memory.get("max_move_4h_24h"))
    peak_volume = _first_known(getattr(snapshot, "peak_volume_ratio_24h", None), memory.get("max_volume_ratio_24h"))
    peak_volatility = _first_known(getattr(snapshot, "peak_volatility_ratio_24h", None), memory.get("max_volatility_ratio_24h"))
    oi_1h = getattr(snapshot, "oi_change_1h", None)
    oi_4h = getattr(snapshot, "oi_change_4h", None)
    oi_context = _oi_context(oi_1h, oi_4h)
    structure_raw = {
        "15m": getattr(snapshot, "structure_15m", "UNKNOWN"),
        "1h": getattr(snapshot, "structure_1h", "UNKNOWN"),
        "4h": getattr(snapshot, "structure_4h", "UNKNOWN"),
    }
    data_status = "FULL" if current_price is not None and resolved_24h is not None else "INSUFFICIENT"
    if data_status == "FULL" and any(value in {None, "UNKNOWN"} for value in [oi_context, structure_raw["1h"], structure_raw["4h"]]):
        data_status = "DEGRADED"

    context = DailyMarketContext(
        current_price=current_price,
        change_24h=resolved_24h,
        max_abs_move_15m_24h=max_15m,
        max_abs_move_1h_24h=max_1h,
        max_abs_move_4h_24h=max_4h,
        peak_volume_ratio_24h=peak_volume,
        peak_volatility_ratio_24h=peak_volatility,
        oi_change_1h=oi_1h,
        oi_change_4h=oi_4h,
        oi_daily_context=oi_context,
        funding=getattr(snapshot, "funding_rate", None),
        structure_15m=structure_raw["15m"],
        structure_1h=structure_raw["1h"],
        structure_4h=structure_raw["4h"],
        liquidity_context=_liquidity_context(snapshot),
        recent_relevant_events=recent_events,
        data_status=data_status,
    )
    context.trace = {
        **trace,
        "market_snapshot_24h": market_24h,
        "intraday_24h": intraday_24h,
        "resolved_24h": resolved_24h,
        "rolling_1h_peak": max_1h,
        "rolling_4h_peak": max_4h,
        "rolling_volume_peak": peak_volume,
        "oi_raw": {"1h": oi_1h, "4h": oi_4h},
        "oi_context": oi_context,
        "structure_raw": structure_raw,
        "structure_resolved": f"15m={context.structure_15m}, 1h={context.structure_1h}, 4h={context.structure_4h}",
        "events_before_filter": len(recent_events_raw or []),
        "events_after_filter": len(recent_events),
    }
    return context


def daily_market_context_score(context):
    if context is None or context.data_status == "INSUFFICIENT":
        return 0, {}

    score = 0

    move_24h = _abs(context.change_24h)
    if move_24h >= 7:
        score += 52
    elif move_24h >= 5:
        score += 36
    elif move_24h >= 3:
        score += 22
    elif move_24h >= 1.5:
        score += 10

    memory = {
        "max_move_15m_24h": context.max_abs_move_15m_24h or 0,
        "max_move_1h_24h": context.max_abs_move_1h_24h or 0,
        "max_move_4h_24h": context.max_abs_move_4h_24h or 0,
        "max_volume_ratio_24h": context.peak_volume_ratio_24h or 0,
        "max_volatility_ratio_24h": context.peak_volatility_ratio_24h or 0,
        "max_oi_change_24h": _max_abs([context.oi_change_1h, context.oi_change_4h]),
    }

    if memory["max_move_1h_24h"] >= 2:
        score += 14
    elif memory["max_move_1h_24h"] >= 1:
        score += 8
    if memory["max_move_4h_24h"] >= 3:
        score += 14
    elif memory["max_move_4h_24h"] >= 1.5:
        score += 8

    if memory["max_volume_ratio_24h"] >= 2.5:
        score += 12
    elif memory["max_volume_ratio_24h"] >= 1.8:
        score += 8
    if memory["max_volatility_ratio_24h"] >= 2:
        score += 8
    elif memory["max_volatility_ratio_24h"] >= 1.5:
        score += 5

    oi_4h = context.oi_change_4h
    if oi_4h is not None and abs(oi_4h) >= 4:
        score += 14
    elif memory["max_oi_change_24h"] >= 3:
        score += 6

    if context.structure_4h in {"BULLISH", "BEARISH", "BULLISH_BREAKOUT", "BEARISH_BREAKOUT"}:
        score += 6
    if move_24h >= 7 and oi_4h is not None and abs(oi_4h) >= 4:
        score += 8
    if context.recent_relevant_events:
        score += min(8, len(context.recent_relevant_events) * 3)

    return max(0, min(100, int(score))), memory


def daily_market_state_score(intraday_state, memory_rows, recent_events=None):
    class _State:
        snapshot = None
        intraday = None

    state = _State()
    state.intraday = intraday_state
    context = build_daily_market_context(state, seen_cache=None)
    context.recent_relevant_events = _filter_recent_events_for_btc_context(recent_events or [])
    memory = _memory_summary(memory_rows, intraday_state.snapshot) if intraday_state else {}
    context.max_abs_move_15m_24h = _first_known(context.max_abs_move_15m_24h, memory.get("max_move_15m_24h"))
    context.max_abs_move_1h_24h = _first_known(context.max_abs_move_1h_24h, memory.get("max_move_1h_24h"))
    context.max_abs_move_4h_24h = _first_known(context.max_abs_move_4h_24h, memory.get("max_move_4h_24h"))
    context.peak_volume_ratio_24h = _first_known(context.peak_volume_ratio_24h, memory.get("max_volume_ratio_24h"))
    context.peak_volatility_ratio_24h = _first_known(context.peak_volatility_ratio_24h, memory.get("max_volatility_ratio_24h"))
    return daily_market_context_score(context)


def daily_recap_fingerprint(intraday_state, memory):
    snapshot = intraday_state.snapshot
    move_bucket = round((snapshot.price_change_24h or 0) / 1.5) * 1.5
    oi_bucket = round((snapshot.oi_change_4h or 0) / 2) * 2
    return f"btc-today:{move_bucket}:{snapshot.structure_4h}:{oi_bucket}:{round(memory.get('max_move_4h_24h', 0), 1)}"


def daily_recap_context_fingerprint(context, memory):
    move_bucket = round((context.change_24h or 0) / 1.5) * 1.5
    oi_bucket = round((context.oi_change_4h or 0) / 2) * 2
    return f"btc-today:{move_bucket}:{context.structure_4h}:{oi_bucket}:{round(memory.get('max_move_4h_24h', 0), 1)}"


def _recap_text_from_context(context, memory):
    events = ""
    if context.recent_relevant_events:
        events = "\n".join(f"- {event['title']} ({event['source']})" for event in context.recent_relevant_events[:4])
    else:
        events = "- No hay catalizador confirmado destacado en el contexto reciente."

    oi_context = ""
    if context.oi_change_4h is not None and context.oi_change_4h <= -4:
        oi_context = (
            "El dato más interesante está en derivados: el open interest cae de forma notable en 4h, "
            "compatible con limpieza de apalancamiento después del impulso. No identifica por sí solo quién cerró posiciones."
        )
    elif context.oi_change_4h is not None and context.oi_change_4h >= 3:
        oi_context = (
            "El open interest acompaña al movimiento, consistente con construcción de apalancamiento. "
            "Eso eleva la importancia de vigilar si el avance conserva follow-through."
        )
    else:
        oi_context = "El open interest no muestra ahora una señal extrema suficiente para atribuir el movimiento a una sola dinámica."

    return "\n".join(
        [
            f"BTC mantiene un movimiento diario de {_fmt(context.change_24h, '%')}, aunque el impulso inmediato ya no es necesariamente una alerta intradía.",
            f"Durante las últimas 24h, Radar registró un pico aproximado de 1h={_fmt(context.max_abs_move_1h_24h, '%')} y 4h={_fmt(context.max_abs_move_4h_24h, '%')}.",
            oi_context,
            f"Estructura actual: 15m={context.structure_15m}, 1h={context.structure_1h}, 4h={context.structure_4h}.",
            f"Volumen/volatilidad: pico de volumen={_fmt(context.peak_volume_ratio_24h)}x; pico de volatilidad={_fmt(context.peak_volatility_ratio_24h)}x.",
            "Contexto de noticias últimas 24h:",
            events,
            "Pregunta: ¿BTC está descargando exceso de apalancamiento antes de otro tramo, o empieza una vuelta más profunda al rango?",
            "Qué vigilar: niveles recientes, evolución del OI, volumen, liquidez visible y aparición de catalizador confirmado.",
            "Horizonte: Hoy / 4-24h.",
            "No es una recomendación operativa.",
        ]
    )


def daily_recap_to_news_item(intraday_state, score, memory, recent_events):
    snapshot = intraday_state.snapshot
    title = "BTC hoy: consolidación tras gran movimiento diario"
    if (snapshot.oi_change_4h or 0) <= -4:
        title = "BTC hoy: sube fuerte y limpia apalancamiento"
    elif snapshot.structure_4h in {"BULLISH", "BULLISH_BREAKOUT"}:
        title = "BTC hoy: avance diario con estructura 4h alcista"

    content = _recap_text(snapshot, memory, recent_events)
    item = NewsItem(
        title=title,
        summary="Síntesis diaria de BTC tras un movimiento relevante de 24h.",
        content=content,
        link=f"market-state:btc-daily-recap:{daily_recap_fingerprint(intraday_state, memory)}",
        published=snapshot.timestamp,
        source="MARKET_STATE",
        category="BTC Today",
        event_type="BTC_DAILY_RECAP",
        affected_assets=["BTC"],
        asset_class="CRYPTO",
        market_impact=score,
        score=score,
        structural_news_relevance=0,
        daily_news_relevance=score,
        intraday_news_relevance=max(0, min(100, int(score * 0.65))),
        materiality="HIGH" if score >= 82 else "MEDIUM",
        confidence="Media",
        verification_status="PRELIMINARY",
        crypto_asset="BTC",
        impact_horizon="DAILY",
        mechanism="24h price action/volume/open interest/structure -> BTC daily market context",
        market_signals=["DAILY_MARKET_RECAP"],
        confluence_score=score,
        evidence_level="CALCULATED",
        mechanism_of_impact="DIRECT",
        editorial_quality=72,
        accepted_by=["DAILY_RECAP"],
    )
    item.intelligence_summary = {
        "DAILY_MARKET_STATE_SCORE": score,
        "CURRENT_24H_MOVE": snapshot.price_change_24h,
        "MAX_MOVE_1H_24H": memory.get("max_move_1h_24h"),
        "MAX_MOVE_4H_24H": memory.get("max_move_4h_24h"),
        "MAX_VOLUME_RATIO_24H": memory.get("max_volume_ratio_24h"),
        "MAX_VOLATILITY_RATIO_24H": memory.get("max_volatility_ratio_24h"),
        "OI_CONTEXT_4H": snapshot.oi_change_4h,
        "STRUCTURE": f"15m={snapshot.structure_15m}, 1h={snapshot.structure_1h}, 4h={snapshot.structure_4h}",
    }
    return item


def daily_recap_context_to_news_item(context, score, memory):
    title = "BTC hoy: consolidación tras gran movimiento diario"
    if (context.oi_change_4h or 0) <= -4:
        title = "BTC hoy: sube fuerte y limpia apalancamiento"
    elif context.structure_4h in {"BULLISH", "BULLISH_BREAKOUT"}:
        title = "BTC hoy: avance diario con estructura 4h alcista"

    content = _recap_text_from_context(context, memory)
    fingerprint = daily_recap_context_fingerprint(context, memory)
    item = NewsItem(
        title=title,
        summary="Síntesis diaria de BTC tras un movimiento relevante de 24h.",
        content=content,
        link=f"market-state:btc-daily-recap:{fingerprint}",
        published=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source="MARKET_STATE",
        category="BTC Today",
        event_type="BTC_DAILY_RECAP",
        affected_assets=["BTC"],
        asset_class="CRYPTO",
        market_impact=score,
        score=score,
        structural_news_relevance=0,
        daily_news_relevance=score,
        intraday_news_relevance=max(0, min(100, int(score * 0.65))),
        materiality="HIGH" if score >= 82 else "MEDIUM",
        confidence="Media",
        verification_status="PRELIMINARY",
        crypto_asset="BTC",
        impact_horizon="DAILY",
        mechanism="24h price action/volume/open interest/structure -> BTC daily market context",
        market_signals=["DAILY_MARKET_RECAP"],
        confluence_score=score,
        evidence_level="CALCULATED",
        mechanism_of_impact="DIRECT",
        editorial_quality=72,
        accepted_by=["DAILY_RECAP"],
    )
    item.intelligence_summary = {
        "DAILY_MARKET_STATE_SCORE": score,
        "CURRENT_PRICE": context.current_price,
        "CURRENT_24H_MOVE": context.change_24h,
        "MAX_MOVE_15M_24H": context.max_abs_move_15m_24h,
        "MAX_MOVE_1H_24H": context.max_abs_move_1h_24h,
        "MAX_MOVE_4H_24H": context.max_abs_move_4h_24h,
        "MAX_VOLUME_RATIO_24H": context.peak_volume_ratio_24h,
        "MAX_VOLATILITY_RATIO_24H": context.peak_volatility_ratio_24h,
        "OI_CONTEXT_1H": context.oi_change_1h,
        "OI_CONTEXT_4H": context.oi_change_4h,
        "OI_DAILY_CONTEXT": context.oi_daily_context,
        "FUNDING": context.funding,
        "STRUCTURE": f"15m={context.structure_15m}, 1h={context.structure_1h}, 4h={context.structure_4h}",
        "LIQUIDITY_CONTEXT": context.liquidity_context,
        "DATA_STATUS": context.data_status,
    }
    return item


def evaluate_daily_market_recap(btc_market_state, seen_cache=None):
    context = build_daily_market_context(btc_market_state, seen_cache=seen_cache)
    if context.data_status == "INSUFFICIENT":
        return DailyMarketRecapDecision(False, reason="NO_INTRADAY_STATE", context=context)

    score, memory = daily_market_context_score(context)
    context.trace["daily_score"] = score
    fingerprint = daily_recap_context_fingerprint(context, memory)
    duplicate = False
    if seen_cache:
        duplicate, _ = seen_cache.daily_recap_seen(fingerprint)

    if score < DAILY_RECAP_MIN_SCORE:
        context.trace["decision"] = "NO_RECAP"
        return DailyMarketRecapDecision(False, score, "NO_RECAP", "LOW_DAILY_MARKET_STATE_SCORE", duplicate, fingerprint, context.recent_relevant_events, context=context)
    if duplicate:
        context.trace["decision"] = "NO_RECAP"
        return DailyMarketRecapDecision(False, score, "NO_RECAP", "DUPLICATE_DAILY_RECAP", True, fingerprint, context.recent_relevant_events, context=context)
    if _recent_intraday_or_daily_covered(hours=6):
        context.trace["decision"] = "NO_RECAP"
        return DailyMarketRecapDecision(False, score, "NO_RECAP", "RECENT_BTC_POST_ALREADY_COVERED", False, fingerprint, context.recent_relevant_events, context=context)
    if _recent_category_count({"BTC Today"}, hours=24) >= DAILY_RECAP_MAX_PER_DAY:
        context.trace["decision"] = "NO_RECAP"
        return DailyMarketRecapDecision(False, score, "NO_RECAP", "DAILY_RECAP_FREQUENCY_LIMIT", False, fingerprint, context.recent_relevant_events, context=context)

    note = daily_recap_context_to_news_item(context, score, memory)
    context.trace["decision"] = "BTC_TODAY_RECAP"
    return DailyMarketRecapDecision(True, score, "BTC_TODAY_RECAP", "PASS", False, fingerprint, context.recent_relevant_events, note, context=context)


def replay_seen_events_with_current_rules(seen_cache, hours=24):
    events = seen_cache.get_recent_relevant_events(hours=hours) if seen_cache else []
    output = []
    for event in events:
        title = event.get("title", "")
        daily = 0
        intraday = 0
        if any(term in title for term in ["clarity", "crypto regulation", "trump", "sec", "cftc", "bitcoin", "btc"]):
            daily = 82
            intraday = 84 if any(term in title for term in ["trump", "bitcoin", "btc"]) else 72
        output.append(
            {
                **event,
                "would_be_daily_candidate_now": daily >= 76,
                "would_be_intraday_candidate_now": intraday >= 82,
                "daily_relevance_now": daily,
                "intraday_relevance_now": intraday,
                "retroactive_publish": False,
            }
        )
    return output
