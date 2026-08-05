import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

FILE = DATA_DIR / "history.json"


def load_history():

    if not FILE.exists():
        return []

    with open(FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(history):

    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)