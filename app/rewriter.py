from pathlib import Path
import json

from ai import ask_json

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "editor_writer.md"


def rewrite_news(news):

    rules = PROMPT_PATH.read_text(encoding="utf-8")

    prompt = f"""
{rules}

====================================

Vas a reescribir UNA ÚNICA noticia.

Debes mantener todos los hechos.

Pero cambia completamente:

- el titular
- la estructura
- la redacción
- el enfoque

No repitas frases.

No reutilices párrafos.

====================================

Categoría:
{news.category}

Título:
{news.title}

Fuente:
{news.source}

Fecha:
{news.published}

Contenido:

{news.content}

====================================

Devuelve exactamente este JSON:

{json.dumps({
    "news":[
        {
            "id":1,
            "title":"",
            "key":"",
            "what_happened":"",
            "impact_spain":"",
            "what_to_watch":"",
            "opinion":"",
            "confidence":""
        }
    ]
}, ensure_ascii=False, indent=2)}
"""

    report = ask_json(prompt)

    return report["news"][0]