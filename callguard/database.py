"""SQLite access: schema, migrations, cached reads and transactional writes."""

import json
import math
import os
import sqlite3
import tempfile
from contextlib import contextmanager

import pandas as pd
import streamlit as st

from callguard.config import BANNED_WORDS_FILE, DB_FILE, QUERY_TTL
from callguard.formatting import as_list


@contextmanager
def db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        conn.close()


def ensure_columns(cursor, table, columns):
    existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, decl in columns.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


@st.cache_resource(show_spinner=False)
def init_db():
    """Runs once per process instead of on every single rerun."""
    with db() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS agents (
                        id TEXT PRIMARY KEY, name TEXT, team TEXT, email TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS calls (
                        id TEXT PRIMARY KEY, agent_id TEXT, date TEXT, duration TEXT,
                        audio_file TEXT, transcription TEXT, qa_score REAL, grammar_score REAL,
                        status TEXT, profanity_detected INTEGER,
                        manually_adjusted INTEGER DEFAULT 0,
                        duration_seconds REAL,
                        FOREIGN KEY(agent_id) REFERENCES agents(id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS reports (
                        call_id TEXT PRIMARY KEY, language TEXT, summary TEXT,
                        violations TEXT, grammar_feedback TEXT, manager_notes TEXT,
                        recommended_coaching TEXT,
                        sentiment_start TEXT, sentiment_end TEXT,
                        FOREIGN KEY(call_id) REFERENCES calls(id) ON DELETE CASCADE)""")

        ensure_columns(c, "reports", {
            "recommended_coaching": "TEXT",
            "sentiment_start": "TEXT",
            "sentiment_end": "TEXT",
        })
        ensure_columns(c, "calls", {
            "manually_adjusted": "INTEGER DEFAULT 0",
            "duration_seconds": "REAL",
            # Username of the account that ran the audit. Nullable on purpose:
            # calls recorded before multi-user login simply have no owner.
            "uploaded_by": "TEXT",
        })

        # Without these, every dashboard filter was a full table scan.
        c.execute("CREATE INDEX IF NOT EXISTS idx_calls_agent   ON calls(agent_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_calls_date    ON calls(date DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_calls_status  ON calls(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_agents_team   ON agents(team)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_calls_uploader ON calls(uploaded_by)")
        conn.commit()
    return True
def bump_data_version():
    st.session_state.data_version = st.session_state.get("data_version", 0) + 1


@st.cache_data(ttl=QUERY_TTL, show_spinner=False)
def _cached_query(query: str, params: tuple, _version: int) -> pd.DataFrame:
    with db() as conn:
        return pd.read_sql_query(query, conn, params=params)


def run_query(query, params=(), cached=True) -> pd.DataFrame:
    params = tuple(params)
    if cached:
        version = st.session_state.get("data_version", 0)
        return _cached_query(query, params, version).copy()
    with db() as conn:
        return pd.read_sql_query(query, conn, params=params)


def scalar(query, params=(), default=0):
    df = run_query(query, params)
    if df.empty:
        return default
    value = df.iloc[0, 0]
    return default if value is None or (isinstance(value, float) and math.isnan(value)) else value


def execute_query(query, params=()):
    with db() as conn:
        conn.execute(query, params)
        conn.commit()
    bump_data_version()


def execute_batch(statements):
    """Run several executemany() writes inside ONE transaction.

    The point is atomicity: previously a `calls` row could commit while its
    matching `reports` row was lost, leaving a call whose report page 404s.
    """
    with db() as conn:
        try:
            c = conn.cursor()
            for sql, rows in statements:
                if rows:
                    c.executemany(sql, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    bump_data_version()


def upsert_agent(agent_id, name, team):
    """FIXED: was INSERT OR IGNORE, so renaming an agent or moving them to a
    new team silently did nothing on every audit after the first.

    No email is written. The agents.email column is left in the schema so that
    existing databases keep loading, but nothing reads or writes it any more.
    """
    execute_query(
        """INSERT INTO agents (id, name, team) VALUES (?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             name = excluded.name,
             team = COALESCE(NULLIF(excluded.team, ''), agents.team)""",
        (agent_id, name, team),
    )


DEFAULT_RULES = {
    "english_banned": ["not my problem", "I don't care", "whatever"],
    "spanish_banned": [],
    "english_offensive": ["idiot", "stupid"],
    "spanish_offensive": [],
}


def load_banned_rules():
    if os.path.exists(BANNED_WORDS_FILE):
        try:
            with open(BANNED_WORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {key: as_list(data.get(key, [])) for key in DEFAULT_RULES}
        except (json.JSONDecodeError, OSError):
            pass  # corrupt file must not brick the app
    return {key: list(value) for key, value in DEFAULT_RULES.items()}


def save_banned_rules(rules):
    """Atomic write — a crash mid-save used to leave a truncated JSON file
    that then failed to parse on every subsequent load."""
    directory = os.path.dirname(os.path.abspath(BANNED_WORDS_FILE)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)
        os.replace(tmp, BANNED_WORDS_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
