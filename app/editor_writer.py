from pathlib import Path
import json

from ai import ask_json
from market_interpreter import attach_editorial_interpretations

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "market_writer.md"


def write_news(news):

    attach_editorial_interpretations(news)

    rules = PROMPT_PATH.read_text(encoding="utf-8")

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

Fuente:
{item.source}

Tipo de fuente:
{item.source_type}

Fecha:
{item.published}

Market impact:
{item.market_impact}

Relevancia estructural:
{item.structural_news_relevance}

Relevancia diaria:
{item.daily_news_relevance}

Relevancia intradía:
{item.intraday_news_relevance}

Aceptado por:
{", ".join(item.accepted_by)}

Imagen elegible:
{item.image_eligible}

Brief de imagen:
{item.image_brief}

Interpretacion editorial interna:
{json.dumps((item.intelligence_summary or {}).get("EDITORIAL_INTERPRETATION", {}), ensure_ascii=False, indent=2)}

Materialidad:
{item.materiality}

Activos afectados:
{", ".join(item.affected_assets)}

Mecanismo:
{item.mechanism}

Estado:
{item.verification_status}

Confianza:
{item.confidence}

Señales:
{", ".join(item.market_signals)}

Discountedness:
{item.discountedness}

Expected:
{item.expected}

Actual:
{item.actual}

Surprise:
{item.surprise}

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
                "what_happened": "",
                "why_it_matters": "",
                "affected_markets": [],
                "signals": [],
                "reading": "",
                "what_to_watch": "",
                "status": "",
                "confidence": "",
                "telegram_text": "",
                "internal_diagnostic": {}
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
