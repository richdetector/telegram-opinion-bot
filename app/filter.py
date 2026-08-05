import re


MIN_TITLE_LENGTH = 25

BANNED_WORDS = [
    "live",
    "watch live",
    "podcast",
    "video",
    "photos",
    "gallery",
    "sport",
    "football",
    "soccer",
    "tennis",
    "nba",
    "premier league",
    "champions league",
    "transfer",
    "celebrity",
    "tv",
    "movie",
    "music",
    "showbiz",
]

LOW_VALUE_WORDS = [
    "opinion",
    "editorial",
    "review",
    "quiz",
    "how to",
    "best",
    "top 10",
]


def normalize(text):

    text = text.lower()
    text = re.sub(r"<.*?>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def clean_news(news):

    cleaned = []
    seen = set()

    for item in news:

        title = normalize(item.title)
        summary = normalize(item.summary)

        text = f"{title} {summary}"

        if len(title) < MIN_TITLE_LENGTH:
            continue

        if any(word in text for word in BANNED_WORDS):
            continue

        if any(word in title for word in LOW_VALUE_WORDS):
            continue

        key = title[:120]

        if key in seen:
            continue

        seen.add(key)

        item.title = item.title.strip()
        item.summary = item.summary.strip()

        cleaned.append(item)

    return cleaned