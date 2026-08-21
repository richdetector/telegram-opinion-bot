from pathlib import Path

from ai import ask_json
from editorial_lanes import needs_ai_enrichment

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "market_enricher.md"


def enrich_metadata(news):
    passthrough = [item for item in news if not needs_ai_enrichment(item)]
    enrichable = [item for item in news if needs_ai_enrichment(item)]

    if not enrichable:
        return news

    rules = PROMPT_PATH.read_text(encoding="utf-8")

    dossier = []

    for i, item in enumerate(enrichable, start=1):

        dossier.append(
            f"""
ID: {i}

Categoría inicial:
{item.category}

Tipo de evento inicial:
{item.event_type}

Título:
{item.title}

Resumen:
{item.summary}

Contenido:
{item.content[:2000]}

Fuente:
{item.source}

Tipo de fuente:
{item.source_type}

Score inicial:
{item.market_impact}

Activos detectados:
{", ".join(item.affected_assets)}

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
      "editorial_topic": "",
      "event_type": "",
      "affected_assets": [],
      "market_impact": 0,
      "materiality": "LOW",
      "impact_horizon": "UNKNOWN",
      "verification_status": "UNCONFIRMED",
      "confidence": "Baja",
      "macro_driver": "",
      "crypto_asset": "",
      "mechanism": "",
      "market_signals": [],
      "discountedness": "UNKNOWN",
      "expected": "",
      "actual": "",
      "surprise": "UNKNOWN"
    }}
  ]
}}
"""

    data = ask_json(prompt)

    for result in data["news"]:

        item = enrichable[result["id"] - 1]

        item.score = result.get("score", item.score)
        item.market_impact = result.get("market_impact", item.market_impact or item.score)
        item.editorial_topic = result.get("editorial_topic", item.editorial_topic)
        item.event_type = result.get("event_type", item.event_type)
        item.affected_assets = result.get("affected_assets", item.affected_assets)
        item.materiality = result.get("materiality", item.materiality)
        item.impact_horizon = result.get("impact_horizon", item.impact_horizon)
        item.verification_status = result.get("verification_status", item.verification_status)
        item.confidence = result.get("confidence", item.confidence)
        item.macro_driver = result.get("macro_driver", item.macro_driver)
        item.crypto_asset = result.get("crypto_asset", item.crypto_asset)
        item.mechanism = result.get("mechanism", item.mechanism)
        item.market_signals = result.get("market_signals", item.market_signals)
        item.discountedness = result.get("discountedness", item.discountedness)
        item.expected = result.get("expected", item.expected)
        item.actual = result.get("actual", item.actual)
        item.surprise = result.get("surprise", item.surprise)

    return passthrough + enrichable
