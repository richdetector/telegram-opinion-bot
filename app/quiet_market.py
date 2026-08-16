from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config import (
    QUIET_MARKET_AFTER_HOURS,
    QUIET_MARKET_ENABLED,
    QUIET_MARKET_MAX_PER_DAY,
    QUIET_MARKET_MIN_SCORE,
)
from history import load_history
from models import NewsItem


QUIET_MARKET_CATEGORY = "Quiet Market Note"


@dataclass
class QuietMarketDecision:
    eligible: bool = False
    passed: bool = False
    score: int = 0
    state: str = "UNKNOWN"
    reason: str = ""
    hours_since_material_post: float | None = None
    published: bool = False
    skipped: str = ""
    note: NewsItem | None = None
    message: str = ""
    data_points: list[str] = field(default_factory=list)
    angle: str = "UNKNOWN"


def _parse_history_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M",):
        try:
            return datetime.strptime(value[:16], fmt)
        except Exception:
            continue
    return None


def _recent_published(history, now, category=None, hours=24):
    cutoff = now - timedelta(hours=hours)
    count = 0
    latest = None

    for row in history:
        if row.get("status") != "published":
            continue
        if category and row.get("category") != category:
            continue
        when = _parse_history_date(row.get("date"))
        if when is None:
            continue
        if latest is None or when > latest:
            latest = when
        if when >= cutoff:
            count += 1

    return count, latest


def hours_since_material_post(history=None, now=None):
    now = now or datetime.now()
    history = history if history is not None else load_history()
    latest = None

    for row in history:
        if row.get("status") != "published":
            continue
        if row.get("category") == QUIET_MARKET_CATEGORY:
            continue
        when = _parse_history_date(row.get("date"))
        if when is None:
            continue
        if latest is None or when > latest:
            latest = when

    if latest is None:
        return None

    return (now - latest).total_seconds() / 3600


def _fmt_number(value, digits=2):
    if value is None:
        return None
    return f"{value:,.{digits}f}"


def _fmt_usd(value):
    if value is None:
        return None
    return f"${value:,.0f}"


def _fmt_pct(value):
    if value is None:
        return None
    return f"{value:+.2f}%"


def _fmt_raw(value):
    if value is None:
        return None
    return f"{value:.6f}".rstrip("0").rstrip(".")


def select_quiet_market_angle(state):
    if state is None:
        return "UNKNOWN"

    snapshot = state.snapshot
    liquidity = state.liquidity_structure
    signals = {signal.name for signal in state.signals}

    if "DELEVERAGING" in signals:
        return "DELEVERAGING"
    if (
        snapshot.open_interest_change is not None
        and snapshot.open_interest_change >= 5
        and abs(snapshot.price_change_24h or 0) <= 1
    ):
        return "OI_DIVERGENCE"
    if snapshot.open_interest_change is not None and snapshot.open_interest_change >= 5:
        return "LEVERAGE_BUILDUP"
    if snapshot.funding_extreme in {"POSITIVE", "NEGATIVE"}:
        return "FUNDING_SHIFT"
    if liquidity and liquidity.book_imbalance is not None and abs(liquidity.book_imbalance) >= 0.35:
        return "LIQUIDITY_IMBALANCE"
    if liquidity and liquidity.structure not in {"", "UNKNOWN", "RANGE"}:
        return "MARKET_STRUCTURE_CHANGE"
    if snapshot.volatility_zscore is not None and snapshot.volatility_zscore <= -1:
        return "VOLATILITY_COMPRESSION"
    if snapshot.volume_zscore is not None and snapshot.volume_zscore <= -1:
        return "VOLUME_DRYUP"
    if snapshot.price_change_24h is not None and abs(snapshot.price_change_24h) <= 0.8:
        return "RANGE_BOUND"
    if state.confluence == "LOW":
        return "LOW_CATALYST_ENVIRONMENT"
    return "MIXED_SIGNALS"


def _market_data_points(state):
    if state is None:
        return []

    snapshot = state.snapshot
    liquidity = state.liquidity_structure
    points = []

    if snapshot.price_change_24h is not None and abs(snapshot.price_change_24h) <= 0.8:
        price = _fmt_usd(snapshot.price)
        change = _fmt_pct(snapshot.price_change_24h)
        if price and change:
            points.append(f"Bitcoin cotiza cerca de {price} y se mueve {change} en 24 horas.")
        else:
            points.append("Bitcoin se mantiene dentro de un rango estrecho en 24 horas.")

    if snapshot.volatility_zscore is not None and snapshot.volatility_zscore <= -1.0:
        volatility = _fmt_pct(snapshot.volatility)
        if volatility:
            points.append(f"La volatilidad intradía está comprimida; la última lectura ronda {volatility}.")
        else:
            points.append("La volatilidad intradía está comprimida frente al baseline reciente.")

    if snapshot.volume_zscore is not None and snapshot.volume_zscore <= -1.0:
        points.append("El volumen está por debajo de su baseline reciente.")

    if snapshot.funding_extreme == "NORMAL":
        funding = _fmt_raw(snapshot.funding_rate)
        if funding:
            points.append(f"El funding permanece prácticamente neutral ({funding}).")
        else:
            points.append("El funding permanece neutral, sin sesgo extremo visible.")

    if snapshot.open_interest_change is not None:
        if abs(snapshot.open_interest_change) <= 2:
            points.append(f"El open interest está estable ({_fmt_pct(snapshot.open_interest_change)} frente al baseline).")
        elif snapshot.open_interest_change >= 5 and abs(snapshot.price_change_24h or 0) <= 1:
            points.append(f"El open interest sube {_fmt_pct(snapshot.open_interest_change)} mientras el precio sigue lateral.")

    if liquidity and liquidity.book_imbalance is not None and abs(liquidity.book_imbalance) <= 0.2:
        points.append(f"La liquidez visible del libro está relativamente equilibrada (imbalance {liquidity.book_imbalance:.2f}).")

    if state.confluence == "LOW" and not state.signals:
        points.append("No aparece un catalizador macro, regulatorio o específico de Bitcoin suficientemente fuerte.")

    return points


def quiet_market_fingerprint(state):
    if state is None:
        return "UNKNOWN"
    snapshot = state.snapshot
    liquidity = state.liquidity_structure

    def bucket(value, low, high):
        if value is None:
            return "UNKNOWN"
        if value <= low:
            return "LOW"
        if value >= high:
            return "HIGH"
        return "NEUTRAL"

    return "|".join(
        [
            f"vol={bucket(snapshot.volatility_zscore, -1.0, 1.0)}",
            f"volume={bucket(snapshot.volume_zscore, -1.0, 1.0)}",
            f"funding={snapshot.funding_extreme}",
            f"oi={bucket(snapshot.open_interest_change, -2.0, 5.0)}",
            f"structure={getattr(liquidity, 'structure', 'UNKNOWN') if liquidity else 'UNKNOWN'}",
            f"liquidity={bucket(getattr(liquidity, 'book_imbalance', None), -0.2, 0.2)}",
            f"regime={state.market_regime}",
            f"angle={select_quiet_market_angle(state)}",
        ]
    )


def quiet_market_score(state, hours_since_material=None, previous_note_hours=None):
    points = _market_data_points(state)
    if len(points) < 3:
        return 0, "INSUFFICIENT_DATA", points

    score = 0
    snapshot = state.snapshot
    liquidity = state.liquidity_structure

    if snapshot.price_change_24h is not None and abs(snapshot.price_change_24h) <= 0.8:
        score += 20
    if snapshot.volatility_zscore is not None and snapshot.volatility_zscore <= -1.0:
        score += 20
    if snapshot.volume_zscore is not None and snapshot.volume_zscore <= -1.0:
        score += 10
    if snapshot.funding_extreme == "NORMAL":
        score += 10
    if snapshot.open_interest_change is not None:
        if abs(snapshot.open_interest_change) <= 2:
            score += 10
        elif snapshot.open_interest_change >= 5 and abs(snapshot.price_change_24h or 0) <= 1:
            score += 15
    if liquidity and liquidity.book_imbalance is not None and abs(liquidity.book_imbalance) <= 0.2:
        score += 10
    if state.confluence == "LOW":
        score += 10
    if hours_since_material is None or hours_since_material >= QUIET_MARKET_AFTER_HOURS:
        score += 10
    if previous_note_hours is not None and previous_note_hours < QUIET_MARKET_AFTER_HOURS:
        score -= 30

    if score >= 75:
        quiet_state = "COMPRESSION"
    elif score >= 60:
        quiet_state = "NEUTRAL"
    else:
        quiet_state = "LOW_SIGNAL"

    return max(0, min(100, score)), quiet_state, points


def evaluate_quiet_market(
    state,
    has_market_alert=False,
    history=None,
    now=None,
    reviewer_ok=True,
    seen_cache=None,
):
    now = now or datetime.now()
    history = history if history is not None else load_history()
    decision = QuietMarketDecision()

    if not QUIET_MARKET_ENABLED:
        decision.skipped = "disabled"
        decision.reason = "Quiet Market Mode is disabled."
        return decision

    if has_market_alert:
        decision.skipped = "market_alert_priority"
        decision.reason = "Market alert lane has priority."
        return decision

    material_hours = hours_since_material_post(history, now)
    decision.hours_since_material_post = material_hours
    if material_hours is not None and material_hours < QUIET_MARKET_AFTER_HOURS:
        decision.skipped = "recent_material_post"
        decision.reason = "A material post was published recently."
        return decision

    quiet_count, latest_quiet = _recent_published(
        history,
        now,
        category=QUIET_MARKET_CATEGORY,
        hours=24,
    )
    if quiet_count >= QUIET_MARKET_MAX_PER_DAY:
        decision.skipped = "frequency_limit"
        decision.reason = "Quiet Market daily frequency limit reached."
        return decision

    previous_note_hours = None
    if latest_quiet is not None:
        previous_note_hours = (now - latest_quiet).total_seconds() / 3600

    score, quiet_state, points = quiet_market_score(
        state,
        hours_since_material=material_hours,
        previous_note_hours=previous_note_hours,
    )
    decision.score = score
    decision.state = quiet_state
    decision.data_points = points
    decision.angle = select_quiet_market_angle(state)
    decision.eligible = score >= QUIET_MARKET_MIN_SCORE

    if not decision.eligible:
        decision.skipped = "low_quiet_score"
        decision.reason = "Not enough confluence for a quiet market note."
        return decision

    fingerprint = quiet_market_fingerprint(state)
    if seen_cache:
        unchanged, previous = seen_cache.quiet_market_seen(fingerprint)
        if unchanged:
            decision.skipped = "unchanged_market_state"
            decision.reason = "Quiet market state has not changed materially since the previous note."
            return decision

    note, message = build_quiet_market_note(state, quiet_state, score, points, decision.angle)
    review = review_quiet_market_message(
        message,
        reviewer_ok=reviewer_ok,
        angle=decision.angle,
        observations=points,
    )
    if not review["ok"]:
        decision.skipped = "reviewer_failed"
        decision.reason = "; ".join(review["errors"])
        return decision

    decision.passed = True
    decision.note = note
    decision.message = message
    decision.reason = "Quiet market confluence is sufficient and frequency gate passed."
    if seen_cache:
        seen_cache.remember_quiet_market(fingerprint, published=False)
    return decision


def _title_for_angle(angle):
    titles = {
        "VOLATILITY_COMPRESSION": "Bitcoin lleva horas dormido: la volatilidad se comprime",
        "RANGE_BOUND": "Bitcoin está prácticamente inmóvil: BTC sigue atrapado en rango",
        "LEVERAGE_BUILDUP": "BTC sigue lateral, pero el apalancamiento empieza a moverse",
        "DELEVERAGING": "BTC muestra señales de desapalancamiento sin catalizador claro",
        "FUNDING_SHIFT": "El funding cambia de tono mientras BTC sigue sin dirección clara",
        "OI_DIVERGENCE": "BTC no se mueve, pero el open interest empieza a contar otra historia",
        "VOLUME_DRYUP": "Bitcoin se queda sin volumen: el mercado espera catalizador",
        "LIQUIDITY_IMBALANCE": "La liquidez visible se desequilibra mientras BTC sigue en rango",
        "MARKET_STRUCTURE_CHANGE": "La estructura de BTC cambia, pero aún falta confirmación",
        "LOW_CATALYST_ENVIRONMENT": "Nada está moviendo a Bitcoin, y eso también es información",
        "ONCHAIN_ACTIVITY_CHANGE": "La actividad on-chain cambia, pero no demuestra intención",
        "MIXED_SIGNALS": "BTC mezcla señales: equilibrio frágil sin dirección confirmada",
    }
    return titles.get(angle, titles["LOW_CATALYST_ENVIRONMENT"])


def _reading_for_angle(angle, quiet_state):
    if angle in {"VOLATILITY_COMPRESSION", "RANGE_BOUND", "VOLUME_DRYUP"}:
        return "Neutral / Compresión"
    if angle in {"LEVERAGE_BUILDUP", "OI_DIVERGENCE"}:
        return "Neutral / Apalancamiento en construcción"
    if angle == "DELEVERAGING":
        return "Neutral / Desapalancamiento"
    if angle == "LIQUIDITY_IMBALANCE":
        return "Neutral / Liquidez desequilibrada"
    if angle == "MARKET_STRUCTURE_CHANGE":
        return "Neutral / Cambio de estructura"
    return "Neutral" if quiet_state != "COMPRESSION" else "Neutral / Compresión"


def build_quiet_market_note(state, quiet_state, score, points, angle=None):
    snapshot = state.snapshot
    angle = angle or select_quiet_market_angle(state)
    title = _title_for_angle(angle)

    bullets = "\n".join(f"- {point}" for point in points[:5])
    watch = "la ruptura del rango, cambios en funding/OI y cualquier catalizador macro o regulatorio verificable"
    reading = _reading_for_angle(angle, quiet_state)

    situation = "Bitcoin no muestra ahora mismo un catalizador material suficiente para una alerta de mercado."
    if snapshot.price is not None and snapshot.price_change_24h is not None:
        situation = (
            f"Bitcoin cotiza cerca de {_fmt_usd(snapshot.price)} y se mueve "
            f"{_fmt_pct(snapshot.price_change_24h)} en 24 horas, sin un catalizador material claro."
        )

    message = f"""📊 MARKET NOTE

*{title}*

*Situación:*
{situation}

*Qué muestran los datos:*
{bullets}

*Qué vigilar:*
{watch}.

*Lectura:*
{reading}. Es contexto de mercado, no una predicción de dirección ni una recomendación operativa.
"""

    note = NewsItem(
        title=title,
        summary=f"Quiet market score {score}/100: {quiet_state}",
        content=message,
        link=f"quiet-market:btc:{snapshot.timestamp}",
        published=snapshot.timestamp,
        source="MARKET_STATE",
        category=QUIET_MARKET_CATEGORY,
        event_type="QUIET_MARKET_STATE",
        affected_assets=["BTC"],
        asset_class="CRYPTO",
        market_impact=0,
        score=score,
        materiality="LOW",
        confidence="Media",
        verification_status="PRELIMINARY",
        mechanism="market data context -> BTC monitoring",
        market_signals=["QUIET_MARKET_NOTE"],
        confluence_score=score,
        evidence_level="CALCULATED",
    )
    return note, message


def review_quiet_market_message(message, reviewer_ok=True, angle=None, observations=None):
    errors = []
    lowered = message.lower()
    banned = [
        "buy",
        "sell",
        "compra",
        "vende",
        "va a subir",
        "va a caer",
        "price target",
        "whales are going long",
        "institutions are buying",
        "se viene",
        "explotará",
        "objetivo de precio",
    ]
    for term in banned:
        if term in lowered:
            errors.append(f"forbidden_language:{term}")

    english_fragments = [
        "btc 24h move",
        "funding is neutral",
        "open interest is broadly stable",
        "range-bound",
        "realized intraday volatility",
        "order book balance is",
    ]
    for fragment in english_fragments:
        if fragment in lowered:
            errors.append(f"non_spanish_fragment:{fragment}")

    if "unknown" in lowered:
        errors.append("unknown_presented_as_data")

    if angle is not None and angle == "UNKNOWN":
        errors.append("missing_angle")

    if observations is not None and len(observations) < 2:
        errors.append("insufficient_observations")

    if not reviewer_ok:
        errors.append("reviewer_failed")

    return {"ok": not errors, "errors": errors}


def format_quiet_market_diagnostic(decision):
    hours = decision.hours_since_material_post
    hours_text = "UNKNOWN" if hours is None else f"{hours:.1f}"
    published = "yes" if decision.published else "no"
    eligible = "yes" if decision.eligible else "no"
    return "\n".join(
        [
            "QUIET MARKET",
            f"Eligible: {eligible}",
            f"Hours since material post: {hours_text}",
            f"State: {decision.state}",
            f"Angle: {decision.angle}",
            f"Score: {decision.score}",
            f"Reason: {decision.reason or decision.skipped}",
            f"Published/skipped: {published if decision.published else decision.skipped or 'skipped'}",
        ]
    )
