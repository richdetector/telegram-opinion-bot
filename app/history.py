import json
from pathlib import Path
from datetime import datetime


HISTORY_FILE = Path(__file__).resolve().parent.parent / "history.json"


def load_history():

    if not HISTORY_FILE.exists():
        return []

    try:

        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)

    except Exception:
        return []

    return history


def save_history(history):

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def was_sent(link):

    history = load_history()

    return any(item["link"] == link for item in history)


def remember(news, status):

    history = load_history()

    history.append(
        {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "status": status,
            "title": news.title,
            "category": news.category,
            "score": news.score,
            "editorial_topic": news.editorial_topic,
            "link": news.link,
        }
    )

    history = history[-500:]

    save_history(history)


def recent_history(days=7):

    history = load_history()

    return history[-50:]