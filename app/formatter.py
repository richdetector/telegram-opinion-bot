def format_one(news):

    confidence = news.get("confidence", "").lower()

    if confidence == "alta":
        icon = "🟢"
    elif confidence == "media":
        icon = "🟡"
    else:
        icon = "🔴"

    markets = news.get("affected_markets", [])
    signals = news.get("signals", [])

    if isinstance(markets, list):
        markets = " · ".join(markets)

    if isinstance(signals, list):
        signals = "\n".join(f"- {signal}" for signal in signals[:5])

    return f"""*{news['title']}*

*Qué ha pasado:*
{news['what_happened']}

*Por qué importa:*
{news['why_it_matters']}

*Mercados:*
{markets}

*Señales:*
{signals}

*Lectura:*
{news['reading']}

*Qué vigilar:*
{news['what_to_watch']}

*Estado:* {news['status']}
{icon} *Confianza:* {news['confidence']}
"""


def format_report(report):

    messages = []

    for news in report["news"]:

        messages.append(
            format_one(news)
        )

    return messages
