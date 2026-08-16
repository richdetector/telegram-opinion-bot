import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config import BASE_DIR


DEFAULT_DB_PATH = BASE_DIR / "seen_cache.sqlite"
TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
}
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "after",
    "before",
    "amid",
    "into",
    "over",
    "says",
    "said",
    "will",
    "may",
    "new",
    "latest",
    "update",
    "breaking",
    "report",
    "reports",
}
SYNONYMS = {
    "federal": "fed",
    "reserve": "fed",
    "fed": "fed",
    "cuts": "cut",
    "cutting": "cut",
    "hikes": "hike",
    "raises": "hike",
    "basis": "bp",
    "points": "bp",
    "bps": "bp",
    "percent": "pct",
    "percentage": "pct",
    "confirms": "confirm",
    "confirmed": "confirm",
    "approves": "approve",
    "approved": "approve",
    "denies": "deny",
    "denied": "deny",
    "implements": "implement",
    "implemented": "implement",
    "threatens": "threat",
    "threatened": "threat",
    "tariffs": "tariff",
    "rates": "rate",
}


@dataclass
class IntakeDecision:
    item: object
    status: str
    reason: str
    event_id: str = ""


@dataclass
class IntakeStats:
    collected_total: int = 0
    new_since_last_cycle: int = 0
    exact_duplicates: int = 0
    near_duplicates: int = 0
    same_event_merges: int = 0
    material_updates: int = 0
    rss_new: int = 0
    telegram_new: int = 0
    market_state_new: int = 0
    decisions: list[IntakeDecision] = field(default_factory=list)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_url(url):
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_PARAMS:
            continue
        query.append((key, value))
    normalized_path = re.sub(r"/+$", "", parts.path or "/")
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            normalized_path,
            urlencode(query, doseq=True),
            "",
        )
    )


def normalize_title(title):
    text = (title or "").lower()
    text = text.replace("$", " ")
    text = re.sub(r"[^a-z0-9%]+", " ", text)
    tokens = []
    for token in text.split():
        token = SYNONYMS.get(token, token)
        if token in STOPWORDS or len(token) <= 2:
            continue
        tokens.append(token)
    return " ".join(tokens)


def title_fingerprint(title):
    tokens = normalize_title(title).split()
    return " ".join(tokens[:12])


def event_fingerprint(title, summary=""):
    tokens = normalize_title(f"{title} {summary}").split()
    priority = [
        token
        for token in tokens
        if token
        in {
            "fed",
            "ecb",
            "boj",
            "pboc",
            "sec",
            "bitcoin",
            "btc",
            "ethereum",
            "eth",
            "etf",
            "tariff",
            "china",
            "trump",
            "oil",
            "iran",
            "nvidia",
            "microsoft",
            "apple",
            "rate",
            "inflation",
            "payroll",
            "cpi",
            "approve",
            "cut",
            "hike",
            "bp",
        }
    ]
    if len(priority) >= 3:
        return " ".join(sorted(set(priority))[:10])
    return " ".join(tokens[:10])


def _event_state(text):
    lowered = (text or "").lower()
    if any(term in lowered for term in ["denied", "denies", "false", "not true"]):
        return "DENIED"
    if any(term in lowered for term in ["implemented", "effective immediately", "signed order"]):
        return "IMPLEMENTED"
    if any(term in lowered for term in ["confirmed", "confirms", "officially"]):
        return "CONFIRMED"
    if any(term in lowered for term in ["threatens", "threatened", "may impose", "could impose"]):
        return "THREATENED"
    if any(term in lowered for term in ["rumor", "unconfirmed", "sources say"]):
        return "RUMOR"
    return "UNKNOWN"


def is_material_update(previous_state, new_state):
    if previous_state == new_state or new_state == "UNKNOWN":
        return False
    transitions = {
        ("RUMOR", "CONFIRMED"),
        ("RUMOR", "DENIED"),
        ("THREATENED", "IMPLEMENTED"),
        ("THREATENED", "CONFIRMED"),
        ("CONFIRMED", "IMPLEMENTED"),
    }
    return (previous_state or "UNKNOWN", new_state) in transitions


class SeenCache:
    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = Path(path)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_url TEXT UNIQUE,
                    title_fingerprint TEXT,
                    normalized_title TEXT,
                    source TEXT,
                    published TEXT,
                    first_seen TEXT,
                    last_seen TEXT,
                    event_fingerprint TEXT,
                    event_state TEXT,
                    status TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_title ON seen_items(title_fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_event ON seen_items(event_fingerprint)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_state (
                    source TEXT PRIMARY KEY,
                    last_seen_entry_id TEXT,
                    last_seen_published TEXT,
                    last_success TEXT,
                    latest_urls TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_stats (
                    source TEXT PRIMARY KEY,
                    items_seen INTEGER DEFAULT 0,
                    items_new INTEGER DEFAULT 0,
                    duplicates INTEGER DEFAULT 0,
                    precandidates INTEGER DEFAULT 0,
                    selected INTEGER DEFAULT 0,
                    published INTEGER DEFAULT 0,
                    material_updates INTEGER DEFAULT 0,
                    timeouts INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    last_success TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT,
                    field TEXT,
                    amount INTEGER,
                    timestamp TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_events_source ON source_events(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_events_time ON source_events(timestamp)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_state (
                    kind TEXT PRIMARY KEY,
                    fingerprint TEXT,
                    last_seen TEXT,
                    last_published TEXT
                )
                """
            )

    def close(self):
        return None

    def get_source_state(self, source):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM source_state WHERE source = ?",
                (source,),
            ).fetchone()
            return dict(row) if row else {}

    def update_source_state(self, source, entry_id="", published="", latest_urls=""):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_state(source, last_seen_entry_id, last_seen_published, last_success, latest_urls)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_seen_entry_id=excluded.last_seen_entry_id,
                    last_seen_published=excluded.last_seen_published,
                    last_success=excluded.last_success,
                    latest_urls=excluded.latest_urls
                """,
                (source, str(entry_id or ""), str(published or ""), _utc_now(), latest_urls or ""),
            )

    def increment_source(self, source, field, amount=1):
        allowed = {
            "items_seen",
            "items_new",
            "duplicates",
            "precandidates",
            "selected",
            "published",
            "material_updates",
            "timeouts",
            "errors",
        }
        if field not in allowed:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_stats(source, last_success)
                VALUES (?, ?)
                ON CONFLICT(source) DO NOTHING
                """,
                (source, _utc_now()),
            )
            conn.execute(
                f"UPDATE source_stats SET {field} = {field} + ?, last_success = ? WHERE source = ?",
                (amount, _utc_now(), source),
            )
            conn.execute(
                """
                INSERT INTO source_events(source, field, amount, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (source, field, int(amount), _utc_now()),
            )

    def source_performance(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM source_stats ORDER BY source").fetchall()
            return [dict(row) for row in rows]

    def source_performance_window(self, hours=24):
        with self._connect() as conn:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            rows = conn.execute(
                """
                SELECT source, field, SUM(amount) AS total
                FROM source_events
                WHERE timestamp >= ?
                GROUP BY source, field
                """,
                (cutoff.isoformat(timespec="seconds"),),
            ).fetchall()
            aggregate = defaultdict(lambda: defaultdict(int))
            for row in rows:
                aggregate[row["source"]][row["field"]] = row["total"] or 0

            stats_rows = conn.execute("SELECT source, last_success FROM source_stats").fetchall()
            for row in stats_rows:
                aggregate[row["source"]]["last_success"] = row["last_success"] or ""

        fields = [
            "items_seen",
            "items_new",
            "duplicates",
            "precandidates",
            "selected",
            "published",
            "material_updates",
            "timeouts",
            "errors",
        ]
        output = []
        for source in sorted(aggregate):
            row = {"source": source}
            for field in fields:
                row[field] = int(aggregate[source].get(field, 0) or 0)
            row["last_success"] = aggregate[source].get("last_success", "")
            output.append(row)
        return output

    def seen_before(self, item):
        canonical = canonical_url(item.link)
        tfp = title_fingerprint(item.title)
        efp = event_fingerprint(item.title, item.summary)
        with self._connect() as conn:
            exact = conn.execute(
                "SELECT * FROM seen_items WHERE canonical_url = ?",
                (canonical,),
            ).fetchone()
            if exact:
                return "DUPLICATE", "EXACT", dict(exact)
            title = conn.execute(
                "SELECT * FROM seen_items WHERE title_fingerprint = ?",
                (tfp,),
            ).fetchone()
            if title:
                return "DUPLICATE", "NEAR_DUPLICATE", dict(title)
            event = conn.execute(
                "SELECT * FROM seen_items WHERE event_fingerprint = ? ORDER BY id DESC LIMIT 1",
                (efp,),
            ).fetchone()
            if event:
                row = dict(event)
                new_state = _event_state(f"{item.title} {item.summary}")
                if is_material_update(row.get("event_state"), new_state):
                    return "MATERIAL_UPDATE", "MATERIAL_UPDATE", row
                return "SUPPORTING_SOURCE", "SAME_EVENT", row
        return "NEW_EVENT", "NEW_EVENT", None

    def remember_item(self, item, status="SEEN"):
        canonical = canonical_url(item.link)
        tfp = title_fingerprint(item.title)
        normalized = normalize_title(item.title)
        efp = event_fingerprint(item.title, item.summary)
        state = _event_state(f"{item.title} {item.summary}")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO seen_items(
                    canonical_url, title_fingerprint, normalized_title, source,
                    published, first_seen, last_seen, event_fingerprint, event_state, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    status=excluded.status
                """,
                (
                    canonical,
                    tfp,
                    normalized,
                    item.source,
                    item.published,
                    now,
                    now,
                    efp,
                    state,
                    status,
                ),
            )

    def update_item_status(self, item, status):
        canonical = canonical_url(item.link)
        with self._connect() as conn:
            conn.execute(
                "UPDATE seen_items SET status = ?, last_seen = ? WHERE canonical_url = ?",
                (status, _utc_now(), canonical),
            )

    def filter_new_items(self, items):
        stats = IntakeStats(collected_total=len(items))
        accepted = []
        supporting_by_event = defaultdict(list)

        for item in items:
            self.increment_source(item.source, "items_seen")
            status, reason, previous = self.seen_before(item)
            event_id = event_fingerprint(item.title, item.summary)
            stats.decisions.append(IntakeDecision(item, status, reason, event_id))

            if status == "NEW_EVENT":
                self.remember_item(item, "SEEN")
                self.increment_source(item.source, "items_new")
                stats.new_since_last_cycle += 1
                accepted.append(item)
            elif status == "MATERIAL_UPDATE":
                self.remember_item(item, "UPDATED")
                self.increment_source(item.source, "material_updates")
                stats.material_updates += 1
                accepted.append(item)
            elif reason == "EXACT":
                self.increment_source(item.source, "duplicates")
                stats.exact_duplicates += 1
            elif reason == "NEAR_DUPLICATE":
                self.increment_source(item.source, "duplicates")
                stats.near_duplicates += 1
            else:
                self.increment_source(item.source, "duplicates")
                stats.same_event_merges += 1
                supporting_by_event[event_id].append(item.source)

            if item.category == "Telegram" and status in {"NEW_EVENT", "MATERIAL_UPDATE"}:
                stats.telegram_new += 1
            elif item.source == "MARKET_STATE" and status in {"NEW_EVENT", "MATERIAL_UPDATE"}:
                stats.market_state_new += 1
            elif item.category != "Telegram" and status in {"NEW_EVENT", "MATERIAL_UPDATE"}:
                stats.rss_new += 1

        for item in accepted:
            event_id = event_fingerprint(item.title, item.summary)
            related = sorted(set(supporting_by_event.get(event_id, [])))
            item.related_sources = sorted(set(item.related_sources + related))

        return accepted, stats

    def mark_precandidates(self, items):
        for item in items:
            self.increment_source(item.source, "precandidates")
            self.update_item_status(item, "PROCESSED")

    def mark_selected(self, items):
        for item in items:
            self.increment_source(item.source, "selected")
            self.update_item_status(item, "SELECTED")

    def mark_published(self, items):
        for item in items:
            self.increment_source(item.source, "published")
            self.update_item_status(item, "PUBLISHED")

    def quiet_market_seen(self, fingerprint):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_state WHERE kind = 'quiet_market'",
            ).fetchone()
            if not row:
                return False, None
            return row["fingerprint"] == fingerprint, dict(row)

    def remember_quiet_market(self, fingerprint, published=False):
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_state WHERE kind = 'quiet_market'",
            ).fetchone()
            last_published = now if published else (row["last_published"] if row else "")
            conn.execute(
                """
                INSERT INTO market_state(kind, fingerprint, last_seen, last_published)
                VALUES ('quiet_market', ?, ?, ?)
                ON CONFLICT(kind) DO UPDATE SET
                    fingerprint=excluded.fingerprint,
                    last_seen=excluded.last_seen,
                    last_published=excluded.last_published
                """,
                (fingerprint, now, last_published),
            )


def format_intake_stats(stats):
    if stats is None:
        stats = IntakeStats()
    return "\n".join(
        [
            f"Collected total: {stats.collected_total}",
            f"New since last cycle: {stats.new_since_last_cycle}",
            f"Exact duplicates: {stats.exact_duplicates}",
            f"Near duplicates: {stats.near_duplicates}",
            f"Same-event merges: {stats.same_event_merges}",
            f"Material updates: {stats.material_updates}",
            f"RSS new: {stats.rss_new}",
            f"Telegram new: {stats.telegram_new}",
            f"Market-state new: {stats.market_state_new}",
        ]
    )


def format_source_performance(rows):
    if not rows:
        return "No source performance data yet."
    lines = ["source | items_seen | new_items | duplicate_rate | precandidate_rate | selection_rate | publication_rate | error_rate | last_success"]
    for row in rows:
        seen = row.get("items_seen") or 0
        duplicates = row.get("duplicates") or 0
        errors = row.get("errors") or 0
        def rate(value):
            return "0.00" if not seen else f"{value / seen:.2f}"
        lines.append(
            " | ".join(
                [
                    str(row.get("source", "")),
                    str(seen),
                    str(row.get("items_new") or 0),
                    rate(duplicates),
                    rate(row.get("precandidates") or 0),
                    rate(row.get("selected") or 0),
                    rate(row.get("published") or 0),
                    rate(errors),
                    str(row.get("last_success") or ""),
                ]
            )
        )
    return "\n".join(lines)
