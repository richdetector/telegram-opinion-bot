FORBIDDEN_PUBLICATION_TERMS = [
    "compra",
    "vende",
    "comprar",
    "vender",
    "buy",
    "sell",
    "to the moon",
    "objetivo de precio",
    "va a subir",
    "va a caer",
    "institutions are buying",
    "las instituciones estan comprando",
    "las instituciones están comprando",
    "whales are going long",
    "las ballenas van en largo",
    "manipulacion institucional",
    "manipulación institucional",
]


def _num(value):
    try:
        return float(value)
    except Exception:
        return None


def _fmt_pct(value):
    value = _num(value)
    if value is None:
        return None
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _fmt_ratio(value):
    value = _num(value)
    if value is None:
        return None
    return f"{value:.1f}x"


def _add_data(points, label, value):
    if value in {None, "", "UNKNOWN"}:
        return
    points.append(f"{label}: {value}")


def _summary_value(summary, key):
    return (summary or {}).get(key)


def _catalyst_confidence(item):
    summary = item.intelligence_summary or {}
    event_status = summary.get("CATALYST_EVENT_STATUS")
    causality = summary.get("CATALYST_CAUSALITY_CONFIDENCE")
    if event_status == "CONFIRMED_EVENT" and causality:
        return f"{event_status}_CAUSALITY_{causality}"
    catalyst = summary.get("CATALYST") or summary.get("catalyst_status")
    if catalyst in {
        "CONFIRMED_CATALYST",
        "LIKELY_CATALYST",
        "POSSIBLE_CATALYST",
        "NO_CLEAR_CATALYST",
    }:
        return catalyst
    if item.verification_status == "CONFIRMED":
        return "CONFIRMED_CATALYST"
    if item.verification_status in {"RUMOR", "UNCONFIRMED", "PRELIMINARY"}:
        return "POSSIBLE_CATALYST"
    return "NO_CLEAR_CATALYST"


def _contains_forbidden(text):
    lowered = (text or "").lower()
    return [term for term in FORBIDDEN_PUBLICATION_TERMS if term in lowered]


def _plain_structure(structure):
    mapping = {
        "BULLISH": "estructura alcista",
        "BEARISH": "estructura bajista",
        "RANGE": "rango",
        "BULLISH_BREAKOUT": "ruptura alcista",
        "BEARISH_BREAKOUT": "ruptura bajista",
        "FAILED_BREAKOUT_UP": "falsa ruptura por arriba",
        "FAILED_BREAKOUT_DOWN": "falsa ruptura por abajo",
        "TRANSITION": "transicion",
    }
    return mapping.get(structure or "UNKNOWN", str(structure).lower())


def interpret_btc_price_oi(item):
    summary = item.intelligence_summary or {}
    move_24h = _num(_summary_value(summary, "CURRENT_24H_MOVE"))
    if move_24h is None:
        move_24h = _num(_summary_value(summary, "MOVE_24H"))
    oi_4h = _num(_summary_value(summary, "OI_CONTEXT_4H"))
    if oi_4h is None:
        oi_4h = _num(_summary_value(summary, "OI_4H"))
    price_15m = _num(_summary_value(summary, "PRICE_CHANGE_15M"))
    price_1h = _num(_summary_value(summary, "PRICE_CHANGE_1H"))
    price_4h = _num(_summary_value(summary, "PRICE_CHANGE_4H"))
    oi_15m = _num(_summary_value(summary, "OI_CHANGE_15M"))
    oi_1h = _num(_summary_value(summary, "OI_CHANGE_1H"))
    structure = _summary_value(summary, "STRUCTURE") or ""

    oi_falling_stack = all(value is not None and value < 0 for value in [oi_15m, oi_1h, oi_4h])
    short_term_cooling = (
        move_24h is not None
        and move_24h >= 5
        and any(value is not None and value < 0 for value in [price_15m, price_1h, price_4h])
        and oi_falling_stack
    )
    if short_term_cooling:
        return {
            "primary_hypothesis": (
                "BTC sigue claramente arriba en 24h, pero el corto plazo empieza a enfriar. "
                "La caida simultanea del open interest en 15m, 1h y 4h es compatible con limpieza de posiciones apalancadas."
            ),
            "alternative_hypothesis": (
                "La lectura alternativa es agotamiento del rally: si el precio pierde estructura y el OI vuelve a crecer en la bajada, "
                "la correccion tendria peor calidad."
            ),
            "interesting_angle": "LEVERAGE_RESET_AFTER_RALLY",
            "headline": "BTC ENFRIA EL RALLY",
            "question": "¿Es un reset saludable despues del rally o el inicio de una vuelta mas profunda al rango?",
        }

    if move_24h is not None and move_24h >= 5 and oi_4h is not None and oi_4h <= -3:
        return {
            "primary_hypothesis": (
                "BTC conserva una subida diaria fuerte mientras desaparece apalancamiento. "
                "Eso es compatible con limpieza de leverage, no con una prueba automatica de demanda nueva."
            ),
            "alternative_hypothesis": (
                "Parte del avance pudo venir de cierres de posiciones; necesita volumen y OI renovado "
                "para confirmar demanda mas persistente."
            ),
            "interesting_angle": "PRICE_UP_OI_DOWN",
            "headline": "BITCOIN SUBE, PERO EL APALANCAMIENTO DESAPARECE",
            "question": "¿Es limpieza de leverage antes de otro impulso o falta demanda nueva para sostener el rally?",
        }
    if move_24h is not None and move_24h >= 5:
        return {
            "primary_hypothesis": (
                "BTC muestra un movimiento diario relevante. La lectura depende de si volumen, estructura "
                "y derivados confirman continuidad o solo un rebote de corto plazo."
            ),
            "alternative_hypothesis": "Sin catalizador claro, el movimiento puede ser mas fragil de lo que parece.",
            "interesting_angle": "BTC_DAILY_EXTENSION",
            "headline": "BITCOIN DESPIERTA",
            "question": "¿Aparece demanda nueva o el movimiento se queda en momentum de corto plazo?",
        }
    if "BULLISH" in structure:
        return {
            "primary_hypothesis": "BTC mantiene estructura favorable, pero la estructura por si sola no confirma continuidad.",
            "alternative_hypothesis": "Una perdida rapida del nivel roto convertiria la ruptura en una senal de menor calidad.",
            "interesting_angle": "STRUCTURE_RECOVERY",
            "headline": "BTC ROMPE EL SILENCIO",
            "question": "¿Aguanta la estructura cuando vuelva el volumen?",
        }
    return {}


def interpret_liquidity_language(item):
    signals = " ".join(item.market_signals or [])
    content = f"{item.title} {item.summary} {item.content} {signals}".lower()
    if any(term in content for term in ["equal_high", "equal highs", "liquidity above", "visible above", "liquidez encima"]):
        return (
            "BTC tiene una zona de liquidez relevante por encima. Eso no implica que el precio tenga que ir alli, "
            "pero si convierte esa zona en un punto natural de vigilancia."
        )
    if any(term in content for term in ["failed breakout", "barrida", "sweep"]):
        return (
            "La lectura tecnica es una posible barrida de liquidez: el precio ataca una zona visible y vuelve al rango. "
            "No es una prueba de manipulacion; es una forma prudente de describir la estructura."
        )
    return ""


def select_important_data(item):
    summary = item.intelligence_summary or {}
    data = []
    _add_data(data, "BTC 24h", _fmt_pct(_summary_value(summary, "CURRENT_24H_MOVE")))
    _add_data(data, "BTC 15m", _fmt_pct(_summary_value(summary, "PRICE_CHANGE_15M")))
    _add_data(data, "BTC 1h", _fmt_pct(_summary_value(summary, "PRICE_CHANGE_1H")))
    _add_data(data, "Pico 4h", _fmt_pct(_summary_value(summary, "MAX_MOVE_4H_24H")))
    _add_data(data, "Open interest 4h", _fmt_pct(_summary_value(summary, "OI_CONTEXT_4H")))
    _add_data(data, "Volumen 15m", _fmt_ratio(_summary_value(summary, "VOLUME_RATIO_15M")))
    _add_data(data, "Volumen", _fmt_ratio(_summary_value(summary, "MAX_VOLUME_RATIO_24H")))
    _add_data(data, "Volatilidad", _fmt_ratio(_summary_value(summary, "MAX_VOLATILITY_RATIO_24H")))
    structure = _summary_value(summary, "STRUCTURE")
    if structure and structure != "UNKNOWN":
        data.append(f"Estructura: {structure}")
    if item.daily_news_relevance >= 76 and item.event_type != "BTC_DAILY_RECAP":
        data.append(f"Relevancia diaria: {item.daily_news_relevance}/100")
    if item.intraday_news_relevance >= 70:
        data.append(f"Relevancia intradia: {item.intraday_news_relevance}/100")
    return data[:4]


def omitted_data(item, selected):
    available = []
    summary = item.intelligence_summary or {}
    for key in sorted(summary):
        value = summary[key]
        if value is None:
            continue
        if isinstance(value, str) and value in {"", "UNKNOWN"}:
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        if not isinstance(value, (str, int, float, bool, list, dict)):
            value = str(value)
        if value not in {None, "", "UNKNOWN"} if isinstance(value, (str, int, float, bool)) else True:
            available.append(key)
    selected_keys = " ".join(selected)
    return [key for key in available if key not in selected_keys][:10]


def _news_angle(item):
    text = f"{item.title} {item.summary} {item.content}".lower()
    if "clarity" in text:
        return "CLARITY_ACT", "LA CLARITY ACT VUELVE AL TABLERO"
    if "trump" in text and any(term in text for term in ["bitcoin", "crypto", "cripto", "tariff", "arancel"]):
        return "TRUMP_MARKET_SENSITIVE", "TRUMP VUELVE A METER PRESION AL CRIPTO"
    if "sec" in text and any(term in text for term in ["bitcoin", "crypto", "cripto", "etf"]):
        return "SEC_CRYPTO", "LA SEC ABRE OTRA PUERTA AL CRIPTO"
    if item.event_type == "COMBINED_MARKET_STORY":
        return "COMBINED_STORY", "VARIAS PIEZAS EMPIEZAN A ENCAJAR"
    if item.verification_status == "RUMOR":
        return "MARKET_RUMOR", "RUMOR CON POTENCIAL DE MOVER MERCADO"
    return "NEWS_CATALYST", item.title.upper()[:80]


def build_editorial_interpretation(item):
    selected = select_important_data(item)
    btc_oi = interpret_btc_price_oi(item)
    liquidity = interpret_liquidity_language(item)
    news_angle, news_headline = _news_angle(item)
    catalyst_confidence = _catalyst_confidence(item)

    if item.category == "Quiet Market Note":
        interesting_angle = "QUIET_MARKET"
        headline = "BITCOIN LLEVA HORAS SIN DECIDIRSE"
        primary = "La ausencia de catalizadores tambien es informacion si coincide con compresion de volatilidad o rango estrecho."
        alternative = "Si no hay cambio real en rango, volatilidad, OI o liquidez, no merece repetirse como historia nueva."
        question = "¿De que lado buscará liquidez primero?"
    elif item.event_type in {"BTC_INTRADAY_MOVE", "BTC_DAILY_RECAP"}:
        interesting_angle = btc_oi.get("interesting_angle") or "BTC_MARKET_STATE"
        headline = btc_oi.get("headline") or ("BTC TIENE UNA DECISION DELANTE")
        primary = btc_oi.get("primary_hypothesis") or item.summary or item.content.split("\n")[0]
        alternative = btc_oi.get("alternative_hypothesis") or "La lectura pierde fuerza si el precio devuelve el movimiento sin volumen ni confirmacion de estructura."
        question = btc_oi.get("question") or "¿Aguanta el movimiento cuando vuelva el volumen?"
    else:
        interesting_angle = news_angle
        headline = news_headline
        primary = "La noticia importa si cambia expectativas de regulacion, liquidez, riesgo o acceso institucional a BTC."
        alternative = "Si no hay reaccion de mercado ni confirmacion adicional, puede quedarse en narrativa de corto plazo."
        question = "¿El mercado lo trata como catalizador real o como ruido politico/regulatorio?"

    if liquidity:
        primary = f"{primary} {liquidity}"

    news_summary = item.summary or item.title
    if item.content:
        first_lines = [line.strip() for line in item.content.splitlines() if line.strip()]
        if first_lines:
            news_summary = first_lines[0][:240]

    interpretation = {
        "story_angle": interesting_angle,
        "headline": headline,
        "primary_hypothesis": primary,
        "alternative_hypothesis": alternative,
        "evidence_for": selected[:3] or item.market_signals[:3],
        "evidence_against": [
            "No usar correlacion temporal como causalidad confirmada.",
            "No hay senal suficiente para hablar de intencion de ballenas o instituciones.",
        ],
        "confidence": item.confidence or "Media",
        "catalyst_confidence": catalyst_confidence,
        "interesting_data_selected": selected,
        "data_omitted_from_publication": omitted_data(item, selected),
        "what_confirms": "Volumen, OI y estructura acompanando el movimiento; o confirmacion primaria si es noticia.",
        "what_invalidates": "Devolucion rapida del movimiento, falta de seguimiento o desmentido/ausencia de confirmacion.",
        "news_summary": news_summary,
        "market_interpretation": primary,
        "suggested_question": question,
        "analysis_value_ratio": "HIGH",
        "editorial_duplicate": False,
        "quality_checks": {
            "concise": True,
            "fact_safe_title": not _contains_forbidden(headline),
            "no_buy_sell": True,
            "causality_guard": catalyst_confidence != "NO_CLEAR_CATALYST" or "sin catalizador claro",
            "max_selected_data": len(selected) <= 4,
        },
    }
    return interpretation


def attach_editorial_interpretations(items):
    for item in items:
        item.intelligence_summary = item.intelligence_summary or {}
        item.intelligence_summary["EDITORIAL_INTERPRETATION"] = build_editorial_interpretation(item)
    return items


def validate_publication_text(text):
    errors = []
    forbidden = _contains_forbidden(text)
    if forbidden:
        errors.extend(f"forbidden_language:{term}" for term in forbidden)
    lowered = (text or "").lower()
    if "shorts provocaron la subida" in lowered:
        errors.append("unsupported_short_covering_causality")
    if "ballenas van" in lowered or "instituciones estan comprando" in lowered or "instituciones están comprando" in lowered:
        errors.append("unsupported_whale_or_institution_claim")
    if len((text or "").split()) > 350:
        errors.append("too_long")
    return {"ok": not errors, "errors": errors}
