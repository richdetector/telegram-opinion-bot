from pathlib import Path
import json

from config import EDITOR_MAX_SELECTED
from ai import ask_json
from history import recent_history
from market_scorer import can_reach_selection
from verification import passes_publish_safety

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "market_selector.md"

MIN_MARKET_IMPACT = 65
MAX_SELECTED = EDITOR_MAX_SELECTED


def _lane_score(item):
    return max(
        item.market_impact,
        getattr(item, "daily_news_relevance", 0),
        getattr(item, "intraday_news_relevance", 0),
        getattr(item, "rumor_relevance", 0),
    )


def _selector_eligible(item):
    if not can_reach_selection(item):
        return False
    if passes_publish_safety(item):
        return True
    if item.event_type == "BTC_INTRADAY_MOVE" and item.confluence_score >= 58:
        return True
    if getattr(item, "daily_news_relevance", 0) >= 76:
        return True
    if getattr(item, "intraday_news_relevance", 0) >= 82:
        return True
    return False


def _fallback_select(news):
    candidates = [
        item
        for item in news
        if _selector_eligible(item)
    ]

    candidates.sort(
        key=lambda item: (
            item.materiality == "CRITICAL",
            _lane_score(item),
            item.source_reliability,
            item.confluence_score,
        ),
        reverse=True,
    )

    return candidates[:MAX_SELECTED]


def select_news_with_ai(news, use_ai=True):

    news = [
        n
        for n in news
        if _lane_score(n) >= MIN_MARKET_IMPACT
        and _selector_eligible(n)
    ]

    if len(news) == 0:
        return []

    if not use_ai:
        return _fallback_select(news)

    rules = PROMPT_PATH.read_text(encoding="utf-8")

    history = recent_history()

    dossier = []

    for i, item in enumerate(news, start=1):

        dossier.append(
            f"""
ID: {i}

Categoría:
{item.category}

Tipo de evento:
{item.event_type}

Título:
{item.title}

Resumen:
{item.summary}

Market impact score:
{item.market_impact}

Relevancia diaria:
{item.daily_news_relevance}

Relevancia intradía:
{item.intraday_news_relevance}

Aceptado por:
{", ".join(item.accepted_by)}

Materialidad:
{item.materiality}

Activos afectados:
{", ".join(item.affected_assets)}

Clase de activo:
{item.asset_class}

Mecanismo:
{item.mechanism}

Estado de verificación:
{item.verification_status}

Confianza:
{item.confidence}

Señales:
{", ".join(item.market_signals)}

Fuentes relacionadas:
{", ".join(item.related_sources)}

Fuente:
{item.source}

Fecha:
{item.published}
"""
        )

    prompt = f"""
{rules}

====================================

NOTICIAS PUBLICADAS RECIENTEMENTE

{json.dumps(history, ensure_ascii=False, indent=2)}

====================================

Estas son las noticias disponibles hoy.

{chr(10).join(dossier)}

====================================

INSTRUCCIONES

Solo selecciona acontecimientos realmente excepcionales para mercados.

No estás obligado a devolver ninguna noticia.

Puedes devolver 0, 1, 2 o más si hay varios eventos realmente distintos y materiales.

Si ninguna merece la pena, devuelve una lista vacía.

Evita repetir temas ya tratados recientemente salvo que exista un cambio realmente importante.

Nunca selecciones más de {MAX_SELECTED}.
"""

    data = ask_json(prompt)

    if "selected_ids" not in data:
        raise Exception("El selector no devolvió 'selected_ids'.")

    selected_news = []

    for news_id in data["selected_ids"][:MAX_SELECTED]:

        if 1 <= news_id <= len(news):
            item = news[news_id - 1]
            if _selector_eligible(item):
                selected_news.append(item)

    return selected_news[:MAX_SELECTED]
