from pathlib import Path

from ai import ask_json

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "editor_reviewer.md"


def review_report(report, expected_news):

    rules = PROMPT_PATH.read_text(encoding="utf-8")

    prompt = f"""
{rules}

====================================

Se esperaban exactamente {expected_news} noticias.

Este es el informe generado:

{report}

====================================
"""

    review = ask_json(prompt)

    if "ok" not in review:
        raise Exception("El reviewer no devolvió el campo 'ok'.")

    if "errors" not in review:
        raise Exception("El reviewer no devolvió el campo 'errors'.")

    return review