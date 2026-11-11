import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator

from app.config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    due_date TEXT,
    amount REAL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    recurrence TEXT NOT NULL DEFAULT 'none',
    recur_day INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    occurrence_date TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    UNIQUE(task_id, occurrence_date)
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spent_on TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'misc',
    vendor TEXT,
    amount REAL NOT NULL,
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    metric_date TEXT NOT NULL,
    spend REAL NOT NULL DEFAULT 0,
    impressions INTEGER NOT NULL DEFAULT 0,
    clicks INTEGER NOT NULL DEFAULT 0,
    installs REAL NOT NULL DEFAULT 0,
    conversions REAL NOT NULL DEFAULT 0,
    conversion_value REAL NOT NULL DEFAULT 0,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(platform, metric_date)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "metric_snapshots", "installs", "installs REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "tasks", "recurrence", "recurrence TEXT NOT NULL DEFAULT 'none'")
        _ensure_column(conn, "tasks", "recur_day", "recur_day INTEGER")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_iso() -> str:
    return date.today().isoformat()
