import json
import uuid
from pathlib import Path


PENDING_FILE = Path(__file__).resolve().parent.parent / "pending.json"


def load_pending():

    if not PENDING_FILE.exists():
        return {}

    try:

        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:

        return {}


def save_pending(data):

    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_pending(news, message, message_id=None):

    data = load_pending()

    pending_id = uuid.uuid4().hex

    data[pending_id] = {
        "message": message,
        "message_id": message_id,
        "news": {
            "title": news.title,
            "link": news.link,
            "category": news.category,
            "score": news.score,
            "editorial_topic": news.editorial_topic,
            "source": news.source,
            "published": news.published,
            "content": news.content,
        },
    }

    save_pending(data)

    return pending_id


def update_pending(pending_id, message):

    data = load_pending()

    if pending_id in data:

        data[pending_id]["message"] = message

        save_pending(data)


def update_message_id(pending_id, message_id):

    data = load_pending()

    if pending_id in data:

        data[pending_id]["message_id"] = message_id

        save_pending(data)


def is_pending(link):

    data = load_pending()

    return any(
        pending["news"]["link"] == link
        for pending in data.values()
    )


def get_pending(pending_id):

    data = load_pending()

    return data.get(pending_id)


def remove_pending(pending_id):

    data = load_pending()

    data.pop(pending_id, None)

    save_pending(data)