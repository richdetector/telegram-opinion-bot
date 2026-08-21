from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from config import DAILY_RECAP_MAX_PER_DAY, DAILY_RECAP_MIN_SCORE
from history import recent_history
from models import NewsItem


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


def daily_market_state_score(intraday_state, memory_rows, recent_events=None):
    if intraday_state is None or getattr(intraday_state, "snapshot", None) is None:
        return 0, {}
    snapshot = intraday_state.snapshot
    if not snapshot.data_available.get("price", snapshot.price is not None):
        return 0, {}

    memory = _memory_summary(memory_rows, snapshot)
    score = 0

    move_24h = _abs(snapshot.price_change_24h)
    if move_24h >= 7:
        score += 52
    elif move_24h >= 5:
        score += 36
    elif move_24h >= 3:
        score += 22
    elif move_24h >= 1.5:
        score += 10

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

    oi_4h = snapshot.oi_change_4h
    if oi_4h is not None and abs(oi_4h) >= 4:
        score += 14
    elif memory["max_oi_change_24h"] >= 3:
        score += 6

    if snapshot.structure_4h in {"BULLISH", "BEARISH", "BULLISH_BREAKOUT", "BEARISH_BREAKOUT"}:
        score += 6
    if move_24h >= 7 and oi_4h is not None and abs(oi_4h) >= 4:
        score += 8
    if recent_events:
        score += min(8, len(recent_events) * 3)

    return max(0, min(100, int(score))), memory


def daily_recap_fingerprint(intraday_state, memory):
    snapshot = intraday_state.snapshot
    move_bucket = round((snapshot.price_change_24h or 0) / 1.5) * 1.5
    oi_bucket = round((snapshot.oi_change_4h or 0) / 2) * 2
    return f"btc-today:{move_bucket}:{snapshot.structure_4h}:{oi_bucket}:{round(memory.get('max_move_4h_24h', 0), 1)}"


def _recap_text(snapshot, memory, recent_events):
    events = ""
    if recent_events:
        events = "\n".join(f"- {event['title']} ({event['source']})" for event in recent_events[:4])
    else:
        events = "- No hay catalizador confirmado destacado en el contexto reciente."

    oi_context = ""
    if snapshot.oi_change_4h is not None and snapshot.oi_change_4h <= -4:
        oi_context = (
            "El dato más interesante está en derivados: el open interest cae de forma notable en 4h, "
            "compatible con limpieza de apalancamiento después del impulso. No identifica por sí solo quién cerró posiciones."
        )
    elif snapshot.oi_change_4h is not None and snapshot.oi_change_4h >= 3:
        oi_context = (
            "El open interest acompaña al movimiento, consistente con construcción de apalancamiento. "
            "Eso eleva la importancia de vigilar si el avance conserva follow-through."
        )
    else:
        oi_context = "El open interest no muestra ahora una señal extrema suficiente para atribuir el movimiento a una sola dinámica."

    return "\n".join(
        [
            f"BTC mantiene un movimiento diario de {_fmt(snapshot.price_change_24h, '%')}, aunque el impulso inmediato ya no es necesariamente una alerta intradía.",
            f"Durante las últimas 24h, Radar registró un pico aproximado de 1h={_fmt(memory.get('max_move_1h_24h'), '%')} y 4h={_fmt(memory.get('max_move_4h_24h'), '%')}.",
            oi_context,
            f"Estructura actual: 15m={snapshot.structure_15m}, 1h={snapshot.structure_1h}, 4h={snapshot.structure_4h}.",
            f"Volumen/volatilidad: pico de volumen={_fmt(memory.get('max_volume_ratio_24h'))}x; pico de volatilidad={_fmt(memory.get('max_volatility_ratio_24h'))}x.",
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


def evaluate_daily_market_recap(btc_market_state, seen_cache=None):
    if btc_market_state is None or getattr(btc_market_state, "intraday", None) is None:
        return DailyMarketRecapDecision(False, reason="NO_INTRADAY_STATE")

    intraday = btc_market_state.intraday
    snapshot = intraday.snapshot
    market_snapshot = getattr(btc_market_state, "snapshot", None)
    if market_snapshot is not None:
        if snapshot.price is None:
            snapshot.price = market_snapshot.price
        if snapshot.price_change_24h is None:
            snapshot.price_change_24h = market_snapshot.price_change_24h
        if not snapshot.timestamp:
            snapshot.timestamp = market_snapshot.timestamp
    if seen_cache:
        seen_cache.remember_btc_intraday_snapshot(intraday)
        memory_rows = seen_cache.btc_daily_memory(hours=24)
        recent_events = seen_cache.get_recent_relevant_events(hours=24)
    else:
        memory_rows = []
        recent_events = []

    score, memory = daily_market_state_score(intraday, memory_rows, recent_events)
    fingerprint = daily_recap_fingerprint(intraday, memory)
    duplicate = False
    if seen_cache:
        duplicate, _ = seen_cache.daily_recap_seen(fingerprint)

    if score < DAILY_RECAP_MIN_SCORE:
        return DailyMarketRecapDecision(False, score, "NO_RECAP", "LOW_DAILY_MARKET_STATE_SCORE", duplicate, fingerprint, recent_events)
    if duplicate:
        return DailyMarketRecapDecision(False, score, "NO_RECAP", "DUPLICATE_DAILY_RECAP", True, fingerprint, recent_events)
    if _recent_intraday_or_daily_covered(hours=6):
        return DailyMarketRecapDecision(False, score, "NO_RECAP", "RECENT_BTC_POST_ALREADY_COVERED", False, fingerprint, recent_events)
    if _recent_category_count({"BTC Today"}, hours=24) >= DAILY_RECAP_MAX_PER_DAY:
        return DailyMarketRecapDecision(False, score, "NO_RECAP", "DAILY_RECAP_FREQUENCY_LIMIT", False, fingerprint, recent_events)

    note = daily_recap_to_news_item(intraday, score, memory, recent_events)
    return DailyMarketRecapDecision(True, score, "BTC_TODAY_RECAP", "PASS", False, fingerprint, recent_events, note)


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
