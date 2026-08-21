import re
import sqlite3
import json
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
                    latest_urls TEXT,
                    consecutive_failures INTEGER DEFAULT 0,
                    backoff_until TEXT
                )
                """
            )
            self._ensure_column(conn, "source_state", "consecutive_failures", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "source_state", "backoff_until", "TEXT")
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS btc_daily_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    price REAL,
                    price_change_15m REAL,
                    price_change_1h REAL,
                    price_change_4h REAL,
                    price_change_24h REAL,
                    volume_ratio_1h REAL,
                    volume_ratio_4h REAL,
                    volatility_ratio_1h REAL,
                    volatility_ratio_4h REAL,
                    oi_change_1h REAL,
                    oi_change_4h REAL,
                    funding_rate REAL,
                    structure_15m TEXT,
                    structure_1h TEXT,
                    structure_4h TEXT,
                    intraday_decision TEXT,
                    intraday_materiality TEXT,
                    confluence_score INTEGER,
                    signals TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_btc_daily_memory_time ON btc_daily_memory(timestamp)")

    def _ensure_column(self, conn, table, column, definition):
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
                INSERT INTO source_state(
                    source,
                    last_seen_entry_id,
                    last_seen_published,
                    last_success,
                    latest_urls,
                    consecutive_failures,
                    backoff_until
                )
                VALUES (?, ?, ?, ?, ?, 0, '')
                ON CONFLICT(source) DO UPDATE SET
                    last_seen_entry_id=excluded.last_seen_entry_id,
                    last_seen_published=excluded.last_seen_published,
                    last_success=excluded.last_success,
                    latest_urls=excluded.latest_urls,
                    consecutive_failures=0,
                    backoff_until=''
                """,
                (source, str(entry_id or ""), str(published or ""), _utc_now(), latest_urls or ""),
            )

    def mark_source_failure(self, source, backoff_after=3, backoff_minutes=60):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT consecutive_failures FROM source_state WHERE source = ?",
                (source,),
            ).fetchone()
            failures = int(row["consecutive_failures"] or 0) + 1 if row else 1
            backoff_until = ""
            if failures >= backoff_after:
                backoff_until = (
                    datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
                ).isoformat(timespec="seconds")
            conn.execute(
                """
                INSERT INTO source_state(
                    source,
                    last_seen_entry_id,
                    last_seen_published,
                    last_success,
                    latest_urls,
                    consecutive_failures,
                    backoff_until
                )
                VALUES (?, '', '', '', '', ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    consecutive_failures=?,
                    backoff_until=?
                """,
                (source, failures, backoff_until, failures, backoff_until),
            )

    def mark_source_success(self, source):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_state(
                    source,
                    last_seen_entry_id,
                    last_seen_published,
                    last_success,
                    latest_urls,
                    consecutive_failures,
                    backoff_until
                )
                VALUES (?, '', '', ?, '', 0, '')
                ON CONFLICT(source) DO UPDATE SET
                    last_success=?,
                    consecutive_failures=0,
                    backoff_until=''
                """,
                (source, _utc_now(), _utc_now()),
            )

    def source_in_backoff(self, source):
        state = self.get_source_state(source)
        backoff_until = state.get("backoff_until")
        if not backoff_until:
            return False
        try:
            until = datetime.fromisoformat(backoff_until)
        except ValueError:
            return False
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until > datetime.now(timezone.utc)

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

    def remember_btc_intraday_snapshot(self, state):
        if state is None or getattr(state, "snapshot", None) is None:
            return
        snapshot = state.snapshot
        timestamp = snapshot.timestamp or _utc_now()
        signals = [signal.name for signal in getattr(state, "signals", [])]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO btc_daily_memory(
                    timestamp, price, price_change_15m, price_change_1h,
                    price_change_4h, price_change_24h, volume_ratio_1h,
                    volume_ratio_4h, volatility_ratio_1h, volatility_ratio_4h,
                    oi_change_1h, oi_change_4h, funding_rate, structure_15m,
                    structure_1h, structure_4h, intraday_decision,
                    intraday_materiality, confluence_score, signals
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    snapshot.price,
                    snapshot.price_change_15m,
                    snapshot.price_change_1h,
                    snapshot.price_change_4h,
                    snapshot.price_change_24h,
                    snapshot.volume_ratio_1h,
                    snapshot.volume_ratio_4h,
                    snapshot.volatility_ratio_1h,
                    snapshot.volatility_ratio_4h,
                    snapshot.oi_change_1h,
                    snapshot.oi_change_4h,
                    snapshot.funding_rate,
                    snapshot.structure_15m,
                    snapshot.structure_1h,
                    snapshot.structure_4h,
                    state.decision,
                    state.intraday_materiality,
                    state.intraday_confluence_score,
                    json.dumps(signals),
                ),
            )

    def btc_daily_memory(self, hours=24):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM btc_daily_memory
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (cutoff.isoformat(timespec="seconds"),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_relevant_events(self, hours=24, limit=12):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        patterns = [
            r"\bbitcoin\b",
            r"\bbtc\b",
            r"\bclarity\b",
            r"\bcrypto\b.*\bregulation\b",
            r"\bcripto\b.*\bregul",
            r"\bstablecoin",
            r"\btrump\b.*\b(bitcoin|btc|crypto|cripto|clarity|tariff|arancel|fed|rate|treasury|sec|cftc|oil|china|sanction)",
            r"\b(bitcoin|btc|crypto|cripto|clarity|tariff|arancel|fed|rate|treasury|sec|cftc|oil|china|sanction)\b.*\btrump\b",
            r"\bwhite house\b.*\b(bitcoin|btc|crypto|cripto|tariff|arancel|fed|rate|treasury|sec|cftc|oil|china|sanction)",
            r"\b(bitcoin|btc|crypto|cripto|tariff|arancel|fed|rate|treasury|sec|cftc|oil|china|sanction)\b.*\bwhite house\b",
            r"\bsec\b",
            r"\bcftc\b",
            r"\betf\b",
            r"\bfed\b",
            r"\bfederal reserve\b",
            r"\btreasury\b",
            r"\bliquidity\b",
            r"\bliquidez\b",
            r"\brate\b",
            r"\byield",
            r"\bdollar\b",
            r"\busd\b",
            r"\bexchange\b",
            r"\bbinance\b",
            r"\bcoinbase\b",
            r"\bwar\b.*\boil\b",
            r"\boil\b.*\bshock\b",
        ]
        exclusions = [
            r"\bfootball\b",
            r"\bsoccer\b",
            r"\bfederation\b",
            r"\bsocial security\b",
            r"\bground beef\b",
            r"\bcar race\b",
            r"\bballroom\b",
            r"\bsolana\b",
            r"\bnft\b",
            r"\bmemecoin\b",
        ]
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT normalized_title, source, published, event_fingerprint, event_state, status, last_seen
                FROM seen_items
                WHERE last_seen >= ?
                ORDER BY last_seen DESC
                LIMIT 200
                """,
                (cutoff.isoformat(timespec="seconds"),),
            ).fetchall()
        events = []
        seen = set()
        for row in rows:
            normalized = row["normalized_title"] or ""
            event_id = row["event_fingerprint"] or normalized
            if event_id in seen:
                continue
            if any(re.search(pattern, normalized) for pattern in exclusions):
                continue
            if not any(re.search(pattern, normalized) for pattern in patterns):
                continue
            seen.add(event_id)
            events.append(
                {
                    "title": normalized,
                    "source": row["source"] or "",
                    "event_type": row["event_fingerprint"] or "",
                    "daily_relevance": "UNKNOWN",
                    "intraday_relevance": "UNKNOWN",
                    "verification": row["event_state"] or "UNKNOWN",
                    "timestamp": row["published"] or row["last_seen"] or "",
                    "status": row["status"] or "",
                }
            )
            if len(events) >= limit:
                break
        return events

    def daily_recap_seen(self, fingerprint):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_state WHERE kind = 'btc_daily_recap'",
            ).fetchone()
            if not row:
                return False, None
            return row["fingerprint"] == fingerprint, dict(row)

    def remember_daily_recap(self, fingerprint, published=False):
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_state WHERE kind = 'btc_daily_recap'",
            ).fetchone()
            last_published = now if published else (row["last_published"] if row else "")
            conn.execute(
                """
                INSERT INTO market_state(kind, fingerprint, last_seen, last_published)
                VALUES ('btc_daily_recap', ?, ?, ?)
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
