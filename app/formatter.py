def format_one(news):

    confidence = news.get("confidence", "").lower()

    if confidence == "alta":
        icon = "🟢"
    elif confidence == "media":
        icon = "🟡"
    else:
        icon = "🔴"

    return f"""*{news['title']}*

🎯 *La clave*
{news['key']}

📰 *Qué ha pasado*
{news['what_happened']}

🇪🇸 *Cómo afecta a España*
{news['impact_spain']}

👀 *Qué deberíamos vigilar*
{news['what_to_watch']}

💬 *Análisis*
{news['opinion']}

{icon} *Confianza:* {news['confidence']}
"""


def format_report(report):

    messages = []

    for news in report["news"]:

        messages.append(
            format_one(news)
        )

    return messages