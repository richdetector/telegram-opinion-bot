from pathlib import Path
import json

from ai import ask_json
from history import recent_history
from market_scorer import can_reach_selection
from verification import passes_publish_safety

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "market_selector.md"

MIN_MARKET_IMPACT = 65
MAX_SELECTED = 2


def _fallback_select(news):
    candidates = [
        item
        for item in news
        if can_reach_selection(item)
        and passes_publish_safety(item)
    ]

    candidates.sort(
        key=lambda item: (
            item.materiality == "CRITICAL",
            item.market_impact,
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
        if n.market_impact >= MIN_MARKET_IMPACT
        and can_reach_selection(n)
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

Puedes devolver 0, 1 o 2.

Si ninguna merece la pena, devuelve una lista vacía.

Evita repetir temas ya tratados recientemente salvo que exista un cambio realmente importante.

Nunca selecciones más de dos.
"""

    data = ask_json(prompt)

    if "selected_ids" not in data:
        raise Exception("El selector no devolvió 'selected_ids'.")

    selected_news = []

    for news_id in data["selected_ids"][:MAX_SELECTED]:

        if 1 <= news_id <= len(news):
            item = news[news_id - 1]
            if passes_publish_safety(item):
                selected_news.append(item)

    return selected_news[:MAX_SELECTED]
