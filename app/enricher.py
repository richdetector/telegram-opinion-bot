from pathlib import Path

from ai import ask_json

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "editor_enricher.md"


def enrich_metadata(news):

    rules = PROMPT_PATH.read_text(encoding="utf-8")

    dossier = []

    for i, item in enumerate(news, start=1):

        dossier.append(
            f"""
ID: {i}

Categoría inicial:
{item.category}

Título:
{item.title}

Resumen:
{item.summary}

Fuente:
{item.source}

Fecha:
{item.published}
"""
        )

    prompt = f"""
{rules}

====================================

Estas son las noticias candidatas.

{chr(10).join(dossier)}

====================================

Devuelve exactamente este JSON:

{{
  "news": [
    {{
      "id": 1,
      "score": 0,
      "editorial_topic": ""
    }}
  ]
}}
"""

    data = ask_json(prompt)

    for result in data["news"]:

        item = news[result["id"] - 1]

        item.score = result["score"]
        item.editorial_topic = result["editorial_topic"]

    return news