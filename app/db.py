"""SQLite storage. One file in DATA_DIR; WAL; every write under one lock."""
import json
import os
import sqlite3
import threading

from . import bootstrap

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(
    key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
    pw_hash TEXT NOT NULL, created REAL);
CREATE TABLE IF NOT EXISTS sessions(
    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL,
    expires REAL, last_seen REAL);
CREATE TABLE IF NOT EXISTS api_keys(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, prefix TEXT,
    key_hash TEXT UNIQUE, created REAL, created_by TEXT, last_used REAL);
CREATE TABLE IF NOT EXISTS sched_state(
    id INTEGER PRIMARY KEY CHECK (id = 1), next_fire REAL, last_fire REAL,
    armed_sig TEXT, armed_at REAL);
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL, finished REAL,
    trigger TEXT, by_user TEXT, dry_run INTEGER, outcome TEXT, folders TEXT,
    candidates INTEGER, cand_bytes INTEGER, removed INTEGER,
    bytes_freed INTEGER, vanished INTEGER, errors INTEGER, refused INTEGER,
    dirs_pruned INTEGER, truncated INTEGER, comfy_queue INTEGER, note TEXT,
    details TEXT);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started DESC);
CREATE TABLE IF NOT EXISTS logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, source TEXT,
    msg TEXT);
INSERT OR IGNORE INTO sched_state(id) VALUES (1);
"""

_ready = [None]


def connect():
    """A fresh connection, schema guaranteed. The ONLY makedirs in ComfySweep
    is here, for its own data directory -- never for a cleanup folder."""
    path = bootstrap.db_path()
    if _ready[0] != path:
        with _lock:
            if _ready[0] != path:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                c = sqlite3.connect(path, timeout=15)
                c.execute("PRAGMA journal_mode=WAL")
                c.executescript(SCHEMA)
                c.commit()
                c.close()
                _ready[0] = path
    c = sqlite3.connect(path, timeout=15, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def reset_cache():
    """Tests re-point DATA_DIR; forget which file was initialised."""
    _ready[0] = None


def query(sql, args=()):
    c = connect()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def one(sql, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql, args=()):
    """(rowcount, lastrowid)."""
    with _lock:
        c = connect()
        try:
            cur = c.execute(sql, args)
            c.commit()
            return cur.rowcount, cur.lastrowid
        finally:
            c.close()


def kv_get(key, default=None):
    r = one("SELECT value FROM kv WHERE key=?", (key,))
    if not r:
        return default
    try:
        return json.loads(r["value"])
    except Exception:
        return default


def kv_set(key, value):
    execute("INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)))
