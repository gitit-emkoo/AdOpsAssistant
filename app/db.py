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
    entity_id TEXT NOT NULL DEFAULT '',
    entity_name TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT 'campaign',
    account_id TEXT NOT NULL DEFAULT '',
    spend REAL NOT NULL DEFAULT 0,
    impressions INTEGER NOT NULL DEFAULT 0,
    clicks INTEGER NOT NULL DEFAULT 0,
    installs REAL NOT NULL DEFAULT 0,
    conversions REAL NOT NULL DEFAULT 0,
    conversion_value REAL NOT NULL DEFAULT 0,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(platform, metric_date, entity_id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS ad_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    connection_key TEXT NOT NULL DEFAULT 'default',
    label TEXT NOT NULL DEFAULT '',
    access_token TEXT,
    refresh_token TEXT,
    expires_at TEXT,
    account_ids TEXT NOT NULL DEFAULT '',
    login_customer_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'connected',
    meta_json TEXT,
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, platform, connection_key),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS monthly_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_month TEXT NOT NULL UNIQUE,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    insights TEXT,
    emailed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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


def _migrate_metric_snapshots(conn: sqlite3.Connection) -> None:
    """Allow multiple campaign rows per platform/day."""
    cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(metric_snapshots)").fetchall()
    }
    if not cols:
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='metric_snapshots'"
    ).fetchone()
    sql = ((row["sql"] if row else "") or "").replace(" ", "").replace("\n", "")
    already_ok = "UNIQUE(platform,metric_date,entity_id)" in sql
    if already_ok and "entity_id" in cols:
        return

    entity_id_expr = "COALESCE(entity_id, '')" if "entity_id" in cols else "''"
    entity_name_expr = "COALESCE(entity_name, '')" if "entity_name" in cols else "''"
    entity_type_expr = (
        "COALESCE(entity_type, 'account')" if "entity_type" in cols else "'account'"
    )
    account_id_expr = "COALESCE(account_id, '')" if "account_id" in cols else "''"
    installs_expr = "COALESCE(installs, 0)" if "installs" in cols else "0"

    conn.execute("DROP TABLE IF EXISTS metric_snapshots_v2")
    conn.execute(
        """
        CREATE TABLE metric_snapshots_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            metric_date TEXT NOT NULL,
            entity_id TEXT NOT NULL DEFAULT '',
            entity_name TEXT NOT NULL DEFAULT '',
            entity_type TEXT NOT NULL DEFAULT 'campaign',
            account_id TEXT NOT NULL DEFAULT '',
            spend REAL NOT NULL DEFAULT 0,
            impressions INTEGER NOT NULL DEFAULT 0,
            clicks INTEGER NOT NULL DEFAULT 0,
            installs REAL NOT NULL DEFAULT 0,
            conversions REAL NOT NULL DEFAULT 0,
            conversion_value REAL NOT NULL DEFAULT 0,
            raw_json TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(platform, metric_date, entity_id)
        )
        """
    )
    conn.execute(
        f"""
        INSERT OR IGNORE INTO metric_snapshots_v2 (
            platform, metric_date, entity_id, entity_name, entity_type, account_id,
            spend, impressions, clicks, installs, conversions, conversion_value,
            raw_json, created_at
        )
        SELECT
            platform, metric_date,
            {entity_id_expr},
            {entity_name_expr},
            {entity_type_expr},
            {account_id_expr},
            spend, impressions, clicks,
            {installs_expr},
            conversions, conversion_value, raw_json, created_at
        FROM metric_snapshots
        """
    )
    conn.execute("DROP TABLE metric_snapshots")
    conn.execute("ALTER TABLE metric_snapshots_v2 RENAME TO metric_snapshots")


def _migrate_ad_connections(conn: sqlite3.Connection) -> None:
    """Allow multiple OAuth logins per platform (user_id, platform, connection_key)."""
    cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(ad_connections)").fetchall()
    }
    if not cols:
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ad_connections'"
    ).fetchone()
    sql = ((row["sql"] if row else "") or "").replace(" ", "").replace("\n", "")
    if "UNIQUE(user_id,platform,connection_key)" in sql and "connection_key" in cols:
        _ensure_column(conn, "oauth_states", "payload", "payload TEXT NOT NULL DEFAULT '{}'")
        return

    conn.execute("DROP TABLE IF EXISTS ad_connections_v2")
    conn.execute(
        """
        CREATE TABLE ad_connections_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            connection_key TEXT NOT NULL DEFAULT 'default',
            label TEXT NOT NULL DEFAULT '',
            access_token TEXT,
            refresh_token TEXT,
            expires_at TEXT,
            account_ids TEXT NOT NULL DEFAULT '',
            login_customer_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'connected',
            meta_json TEXT,
            updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, platform, connection_key),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    key_expr = "COALESCE(connection_key, 'default')" if "connection_key" in cols else "'default'"
    label_expr = "COALESCE(label, '')" if "label" in cols else "''"
    conn.execute(
        f"""
        INSERT OR IGNORE INTO ad_connections_v2 (
            user_id, platform, connection_key, label,
            access_token, refresh_token, expires_at, account_ids,
            login_customer_id, status, meta_json, updated_at, created_at
        )
        SELECT
            user_id, platform, {key_expr}, {label_expr},
            access_token, refresh_token, expires_at, account_ids,
            login_customer_id, status, meta_json, updated_at, created_at
        FROM ad_connections
        """
    )
    conn.execute("DROP TABLE ad_connections")
    conn.execute("ALTER TABLE ad_connections_v2 RENAME TO ad_connections")
    _ensure_column(conn, "oauth_states", "payload", "payload TEXT NOT NULL DEFAULT '{}'")


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "metric_snapshots", "installs", "installs REAL NOT NULL DEFAULT 0")
        _migrate_metric_snapshots(conn)
        _migrate_ad_connections(conn)
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
