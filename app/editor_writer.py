from pathlib import Path
import json

from ai import ask_json

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "editor_writer.md"


def write_news(news):

    rules = PROMPT_PATH.read_text(encoding="utf-8")

    dossier = []

    for i, item in enumerate(news, start=1):

        dossier.append(
            f"""
ID: {i}

Categoría:
{item.category}

Título:
{item.title}

Fuente:
{item.source}

Fecha:
{item.published}

Contenido:

{item.content}
"""
        )

    example = {
        "news": []
    }

    for i in range(1, len(news) + 1):

        example["news"].append(
            {
                "id": i,
                "title": "",
                "key": "",
                "what_happened": "",
                "impact_spain": "",
                "what_to_watch": "",
                "opinion": "",
                "confidence": ""
            }
        )

    prompt = f"""
{rules}

====================================

Estas son las noticias ya seleccionadas por el director editorial.

Has recibido exactamente {len(news)} noticias.

Debes redactar TODAS.

No puedes omitir ninguna.

{chr(10).join(dossier)}

====================================

Devuelve exactamente este formato JSON:

{json.dumps(example, ensure_ascii=False, indent=2)}
"""

    report = ask_json(prompt)

    if "news" not in report:
        raise Exception("La IA no devolvió el campo 'news'.")

    if len(report["news"]) != len(news):
        raise Exception(
            f"Se esperaban {len(news)} noticias y la IA devolvió {len(report['news'])}."
        )

    return report