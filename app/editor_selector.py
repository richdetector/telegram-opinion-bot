from pathlib import Path
import json

from ai import ask_json
from history import recent_history

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "editor_selector.md"

MIN_SCORE = 80


def select_news_with_ai(news):

    # Solo llegan al selector noticias realmente importantes
    news = [n for n in news if n.score >= MIN_SCORE]

    if len(news) == 0:
        return []

    rules = PROMPT_PATH.read_text(encoding="utf-8")

    history = recent_history()

    dossier = []

    for i, item in enumerate(news, start=1):

        dossier.append(
            f"""
ID: {i}

Categoría:
{item.category}

Título:
{item.title}

Resumen:
{item.summary}

Score editorial:
{item.score}

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

Solo selecciona noticias realmente excepcionales.

No estás obligado a devolver tres noticias.

Si hoy solo merece la pena publicar una, devuelve una.

Si ninguna merece la pena, devuelve una lista vacía.

Evita repetir temas ya tratados recientemente salvo que exista un cambio realmente importante.

Construye una portada variada y de alto impacto.
"""

    data = ask_json(prompt)

    if "selected_ids" not in data:
        raise Exception("El selector no devolvió 'selected_ids'.")

    selected_news = []

    for news_id in data["selected_ids"]:

        if 1 <= news_id <= len(news):
            selected_news.append(news[news_id - 1])

    return selected_news