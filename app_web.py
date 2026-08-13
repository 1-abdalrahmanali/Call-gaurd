import json
import os
import random
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from openai import OpenAI

# ==========================================
# 1. CONFIGURATION & SETUP
# ==========================================
try:
    SERVER_GROQ_KEY = st.secrets.get("GROQ_API_KEY", "")
except Exception:
    SERVER_GROQ_KEY = ""
SERVER_GROQ_KEY = SERVER_GROQ_KEY or os.environ.get("GROQ_API_KEY", "")

DB_FILE = "enterprise_qa.db"
BANNED_WORDS_FILE = "banned_words.json"
AUDIO_DIR = "audio_store"
os.makedirs(AUDIO_DIR, exist_ok=True)

# ---- Pipeline tuning -------------------------------------------------------
# Workers = how many calls are in flight at once. Keep this at or below your
# Groq RPM budget divided by 2 (each call = 1 Whisper request + 1 LLM request).
DEFAULT_WORKERS = 4
# Files are processed in chunks. Each chunk is committed to SQLite before the
# next one starts, so a crash or closed tab loses at most one chunk.
CHUNK_SIZE = 25
MAX_RETRIES = 5
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}

st.set_page_config(
    page_title="QA Operations Console",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==========================================
# 2. DATABASE HELPERS
# ==========================================
def get_conn():
    # timeout: wait for a lock instead of instantly raising "database is locked".
    # WAL: lets readers (the dashboard) work while a batch is writing.
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY, name TEXT, team TEXT, email TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY, agent_id TEXT, date TEXT, duration TEXT,
                    audio_file TEXT, transcription TEXT, qa_score REAL, grammar_score REAL,
                    status TEXT, profanity_detected INTEGER, manually_adjusted INTEGER DEFAULT 0,
                    FOREIGN KEY(agent_id) REFERENCES agents(id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS reports (
                    call_id TEXT PRIMARY KEY, language TEXT, summary TEXT,
                    violations TEXT, grammar_feedback TEXT, manager_notes TEXT,
                    recommended_coaching TEXT,
                    sentiment_start TEXT, sentiment_end TEXT,
                    FOREIGN KEY(call_id) REFERENCES calls(id))""")

    # Migration for databases created before recommended_coaching existed.
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(reports)").fetchall()]
    if "recommended_coaching" not in existing_cols:
        c.execute("ALTER TABLE reports ADD COLUMN recommended_coaching TEXT")
    if "sentiment_start" not in existing_cols:
        c.execute("ALTER TABLE reports ADD COLUMN sentiment_start TEXT")
    if "sentiment_end" not in existing_cols:
        c.execute("ALTER TABLE reports ADD COLUMN sentiment_end TEXT")

    existing_call_cols = [row[1] for row in c.execute("PRAGMA table_info(calls)").fetchall()]
    if "manually_adjusted" not in existing_call_cols:
        c.execute("ALTER TABLE calls ADD COLUMN manually_adjusted INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


init_db()


def run_query(query, params=()):
    conn = get_conn()
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def execute_query(query, params=()):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def execute_batch(statements):
    """Run several executemany() writes inside ONE transaction.

    statements: list of (sql, list_of_param_tuples)

    This matters less for speed than the advice you were given suggests — the
    real win is atomicity. Previously a `calls` row could be committed and the
    matching `reports` row lost if anything failed in between, leaving an
    orphaned call with no report attached to it.
    """
    conn = get_conn()
    try:
        c = conn.cursor()
        for sql, rows in statements:
            if rows:
                c.executemany(sql, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_banned_rules():
    if os.path.exists(BANNED_WORDS_FILE):
        with open(BANNED_WORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "english_banned": ["not my problem", "I don't care", "whatever"],
        "spanish_banned": [],
        "english_offensive": ["idiot", "stupid"],
        "spanish_offensive": [],
    }


def save_banned_rules(rules):
    with open(BANNED_WORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)


# ==========================================
# 3. STYLING
# ==========================================
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; }
    .main { background-color: #0A0D12; }
    section[data-testid="stSidebar"] { background-color: #0D1117; border-right: 1px solid #1D232E; }
    h1, h2, h3, h4 { letter-spacing: -0.01em; }

    /* Identifier chips — the one visual motif used for every Call ID / Employee ID */
    .id-chip {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 12px;
        color: #9AA5B8;
        background: #171C25;
        border: 1px solid #262D3A;
        padding: 2px 8px;
        border-radius: 5px;
        letter-spacing: 0.02em;
        display: inline-block;
    }

    /* Status badges */
    .status-badge {
        display: inline-block;
        font-size: 12px;
        font-weight: 600;
        padding: 3px 10px;
        border-radius: 999px;
        letter-spacing: 0.01em;
        white-space: nowrap;
    }
    .badge-passed   { background: rgba(63, 182, 139, 0.15); color: #3FB68B; border: 1px solid rgba(63,182,139,0.35); }
    .badge-warning  { background: rgba(224, 167, 62, 0.15); color: #E0A73E; border: 1px solid rgba(224,167,62,0.35); }
    .badge-critical { background: rgba(229, 72, 77, 0.15);  color: #E5484D; border: 1px solid rgba(229,72,77,0.35); }
    .badge-review   { background: rgba(124, 147, 255, 0.15); color: #7C93FF; border: 1px solid rgba(124,147,255,0.35); }

    .critical-alert-card {
        background: rgba(229, 72, 77, 0.06);
        border: 1px solid rgba(229, 72, 77, 0.35);
        border-left: 3px solid #E5484D;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 8px;
    }

    .top-performer-card {
        background: rgba(212, 162, 76, 0.06);
        border: 1px solid rgba(212, 162, 76, 0.35);
        border-left: 3px solid #D4A24C;
        border-radius: 8px;
        padding: 12px 14px;
    }

    .col-header { color: #8A94A6; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; }
    .row-divider { margin: 4px 0 10px; border: none; border-top: 1px solid #1D232E; }

    .audit-row-ok, .audit-row-err {
        padding: 6px 10px; border-radius: 6px; font-size: 13px; margin-bottom: 4px;
    }
    .audit-row-ok { background: rgba(63,182,139,0.08); }
    .audit-row-err { background: rgba(229,72,77,0.08); color: #E5484D; }

    [data-testid="stMetric"] { background-color: #12161D; border: 1px solid #232935; padding: 14px 16px; border-radius: 10px; }
    [data-testid="stMetricLabel"] { color: #8A94A6; }
    [data-testid="stMetricValue"] { color: #EAEDF3; }

    div.stButton > button { border-radius: 7px; font-weight: 500; }
    </style>
""", unsafe_allow_html=True)


def status_badge(status):
    styles = {
        "Passed": ("badge-passed", "🟢"),
        "Warning": ("badge-warning", "🟡"),
        "Critical": ("badge-critical", "🔴"),
        "In Review": ("badge-review", "🔵"),
    }
    cls, emoji = styles.get(status, ("badge-warning", "⚪"))
    return f"<span class='status-badge {cls}'>{emoji} {status}</span>"


def id_chip(value):
    return f"<span class='id-chip'>{value}</span>"


def sentiment_badge(sentiment):
    styles = {
        "Positive": ("badge-passed"),
        "Neutral": ("badge-warning"),
        "Negative": ("badge-critical"),
    }
    cls, emoji = styles.get(sentiment, ("badge-warning"))
    return f"<span class='status-badge {cls}'>{emoji} {sentiment or 'Unknown'}</span>"

# ==========================================
#  Login
# ==========================================

def view_login():
    st.title("callguard")
    st.caption("please enter the password")

    with st.form("simple_login_form"):
        password = st.text_input(
            "Password", type="password", placeholder="Enter your password"
        )

        submit_btn = st.form_submit_button("Sign In", type="primary")

        if submit_btn:
            correct_password = st.secrets["APP_PASSWORD"]

            if password == correct_password:
                st.session_state.authenticated = True
                st.success("Welcome back!")
                st.rerun()
            else:
                st.error(
                    "Authentication failed. Please check your password and try"
                    " again."
                )
                
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.get("authenticated", False):
    view_login()
    st.stop()  
# ==========================================
# 4. ROUTER / STATE MANAGEMENT
# ==========================================
    


def sync_query_params(params):
    """Best-effort URL sync. Safe no-op on Streamlit versions without st.query_params."""
    try:
        st.query_params.clear()
        st.query_params.update(params)
    except Exception:
        pass


def read_query_params():
    try:
        return dict(st.query_params)
    except Exception:
        return {}


_qp = read_query_params()
if "current_view" not in st.session_state:
    st.session_state.current_view = _qp.get("view", "Dashboard")
if "selected_agent" not in st.session_state:
    st.session_state.selected_agent = _qp.get("agent_id")
if "selected_call" not in st.session_state:
    st.session_state.selected_call = _qp.get("call_id")
if "previous_view" not in st.session_state:
    st.session_state.previous_view = None
if "last_audited_calls" not in st.session_state:
    st.session_state.last_audited_calls = None


def navigate_to(view, agent_id=None, call_id=None):
    if view == "CallReport":
        st.session_state.previous_view = st.session_state.current_view
    st.session_state.current_view = view
    if agent_id is not None:
        st.session_state.selected_agent = agent_id
    if call_id is not None:
        st.session_state.selected_call = call_id

    params = {"view": view}
    if view == "AgentDetails" and st.session_state.selected_agent:
        params["agent_id"] = st.session_state.selected_agent
    if view == "CallReport" and st.session_state.selected_call:
        params["call_id"] = st.session_state.selected_call
    sync_query_params(params)


def active_nav_key():
    cv = st.session_state.current_view
    if cv == "AgentDetails":
        return "Agents"
    if cv == "CallReport":
        prev = st.session_state.get("previous_view")
        return "Agents" if prev == "AgentDetails" else ("Auditor" if prev == "Auditor" else "Dashboard")
    return cv


# ==========================================
# 5. SIDEBAR NAVIGATION
# ==========================================
with st.sidebar:
    st.markdown("### Call guard")
    st.caption("Quality Assurance Platform")
    st.divider()

    nav_items = [
        ("Dashboard", " Dashboard"),
        ("Agents", " Agents"),
        ("Auditor", "Audios"),
        ("Settings", " Settings"),
    ]
    active_key = active_nav_key()
    for view_key, label in nav_items:
        if st.button(label, use_container_width=True,
                     type="primary" if active_key == view_key else "secondary",
                     key=f"nav_{view_key}"):
            navigate_to(view_key)
            st.rerun()

    if st.button(" Logout", use_container_width=True):
     st.session_state.authenticated = False
     for key in ("current_view", "selected_agent", "selected_call", "previous_view", "last_audited_calls"):
        st.session_state.pop(key, None)
     sync_query_params({})
     st.rerun()

    
    st.divider()    
    st.markdown("Made by: Abdalruhman Ali")
    st.caption("All Rights Reserved")
    
# ==========================================
# 6. VIEW: DASHBOARD
# ==========================================
def view_dashboard():
    st.title(" QA Operations")
    st.caption("Find an agent, open their calls, and review the reports.")

    st.markdown("#####  Search")
    search_query = st.text_input(
        "Search", placeholder="Agent name, Agent ID, or call ID",
        label_visibility="collapsed",
    )

    st.markdown("##### Filters")
    fc1, fc2, fc3, fc4, fc5 = st.columns([1.6, 2, 1, 1, 1])
    teams = ["All Teams"] + sorted(
        [t for t in run_query("SELECT DISTINCT team FROM agents")["team"].dropna().tolist() if t]
    )
    with fc1:
        team_filter = st.selectbox("Team", teams)
    with fc2:
        today = datetime.now().date()
        date_range = st.date_input("Date range", value=(today - timedelta(days=365), today))
    with fc3:
        critical_only = st.checkbox("🔴 Critical only")
    with fc4:
        show_passed = st.checkbox("🟢 Passed")
    with fc5:
        show_failed = st.checkbox("🟡 Failed")

    # "Failed" bundles Warning + Critical statuses; Critical-only overrides the rest.
    status_list = None
    if critical_only:
        status_list = ["Critical"]
    else:
        chosen = []
        if show_passed:
            chosen.append("Passed")
        if show_failed:
            chosen += ["Warning", "Critical"]
        if chosen:
            status_list = list(dict.fromkeys(chosen))

    start_date = end_date = None
    if isinstance(date_range, (list, tuple)):
        if len(date_range) == 2:
            start_date, end_date = date_range
        elif len(date_range) == 1:
            start_date = end_date = date_range[0]
    elif date_range:
        start_date = end_date = date_range

    query = """
        SELECT c.id as call_id, a.name as agent_name, a.id as employee_id,
               c.date, c.duration, c.qa_score, c.status
        FROM calls c JOIN agents a ON c.agent_id = a.id
        WHERE 1=1
    """
    params = []
    if search_query:
        like = f"%{search_query}%"
        query += " AND (a.name LIKE ? OR a.id LIKE ? OR c.id LIKE ?)"
        params += [like, like, like]
    if team_filter != "All Teams":
        query += " AND a.team = ?"
        params.append(team_filter)
    if status_list:
        query += f" AND c.status IN ({','.join(['?'] * len(status_list))})"
        params += status_list
    if start_date:
        query += " AND substr(c.date, 1, 10) >= ?"
        params.append(start_date.isoformat())
    if end_date:
        query += " AND substr(c.date, 1, 10) <= ?"
        params.append(end_date.isoformat())
    query += " ORDER BY c.date DESC LIMIT 25"
    df_calls = run_query(query, tuple(params))

    st.markdown("####  Calls")
    if df_calls.empty:
        st.info("No calls match your search and filters.")
    else:
        col_widths = [2.2, 1.5, 1.3, 1.0, 1.0, 1.3, 1.2]
        headers = ["Agent", "Call ID", "Date", "Duration", "Score", "Status", ""]
        header_cols = st.columns(col_widths)
        for col, label in zip(header_cols, headers):
            if label:
                col.markdown(f"<span class='col-header'>{label.upper()}</span>", unsafe_allow_html=True)

        for _, row in df_calls.iterrows():
            cols = st.columns(col_widths)
            cols[0].markdown(f"**{row['agent_name']}**<br>{id_chip(row['employee_id'])}", unsafe_allow_html=True)
            cols[1].markdown(id_chip(row['call_id']), unsafe_allow_html=True)
            cols[2].write(str(row['date'])[:16])
            cols[3].write(row['duration'] or "—")
            cols[4].write(f"{row['qa_score']}/10")
            cols[5].markdown(status_badge(row['status']), unsafe_allow_html=True)
            if cols[6].button("Open →", key=f"open_call_{row['call_id']}", use_container_width=True):
                navigate_to("CallReport", call_id=row['call_id'])
                st.rerun()
            st.markdown("<hr class='row-divider'>", unsafe_allow_html=True)

    st.markdown("####  Critical Calls")
    crit_query = """
        SELECT c.id as call_id, a.name as agent_name, c.qa_score, r.summary
        FROM calls c
        JOIN agents a ON c.agent_id = a.id
        JOIN reports r ON c.id = r.call_id
        WHERE c.status = 'Critical'
    """
    crit_params = []
    if team_filter != "All Teams":
        crit_query += " AND a.team = ?"
        crit_params.append(team_filter)
    if start_date:
        crit_query += " AND substr(c.date, 1, 10) >= ?"
        crit_params.append(start_date.isoformat())
    if end_date:
        crit_query += " AND substr(c.date, 1, 10) <= ?"
        crit_params.append(end_date.isoformat())
    crit_query += " ORDER BY c.date DESC LIMIT 10"
    df_critical = run_query(crit_query, tuple(crit_params))

    if df_critical.empty:
        st.success("No critical calls right now.")
    else:
        for _, row in df_critical.iterrows():
            reason = (row['summary'] or "No summary available.").strip()
            if len(reason) > 160:
                reason = reason[:160].rstrip() + "…"
            st.markdown(f"""
                <div class="critical-alert-card">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">
                        <div>
                            <div style="font-weight:600;color:#EAEDF3;">{row['agent_name']}</div>
                            <div style="color:#8A94A6;font-size:13px;margin-top:2px;">{reason}</div>
                        </div>
                        <div class="status-badge badge-critical">{row['qa_score']}/10</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            if st.button("Open Report →", key=f"crit_open_{row['call_id']}"):
                navigate_to("CallReport", call_id=row['call_id'])
                st.rerun()


# ==========================================
# 7. VIEW: AGENTS
# ==========================================
def view_agents():
    st.title(" Agents")
    st.caption("Find an agent, then open their calls.")

    thirty_days_ago = (datetime.now().date() - timedelta(days=30)).isoformat()
    df_top = run_query("""
        SELECT a.id, a.name, a.team, AVG(c.qa_score) as avg_score, COUNT(c.id) as call_count
        FROM agents a
        JOIN calls c ON a.id = c.agent_id
        WHERE substr(c.date, 1, 10) >= ?
        GROUP BY a.id
        ORDER BY avg_score DESC
        LIMIT 5
    """, (thirty_days_ago,))

    if not df_top.empty:
        st.markdown("##### Top Performers (Last 30 Days)")
        tp_cols = st.columns(len(df_top))
        for col, (_, row) in zip(tp_cols, df_top.iterrows()):
            call_word = "call" if row['call_count'] == 1 else "calls"
            col.markdown(f"""
                <div class="top-performer-card">
                    <div style="font-weight:600;color:#EAEDF3;font-size:13px;">{row['name']}</div>
                    <div style="color:#8A94A6;font-size:11px;margin-top:2px;">{row['team'] or '—'}</div>
                    <div style="color:#D4A24C;font-weight:700;font-size:18px;margin-top:6px;">{row['avg_score']:.2f}/10</div>
                    <div style="color:#8A94A6;font-size:11px;">{int(row['call_count'])} {call_word}</div>
                </div>
            """, unsafe_allow_html=True)
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    search = st.text_input("Search agents", placeholder="Search by agent name or agent ID",
                            label_visibility="collapsed")

    query = """
        SELECT a.id, a.name, a.team,
               MAX(c.date) as last_call,
               SUM(CASE WHEN c.status = 'Critical' THEN 1 ELSE 0 END) as critical_count
        FROM agents a
        LEFT JOIN calls c ON a.id = c.agent_id
    """
    params = []
    if search:
        like = f"%{search}%"
        query += " WHERE a.name LIKE ? OR a.id LIKE ?"
        params = [like, like]
    query += " GROUP BY a.id ORDER BY a.name"
    df_agents = run_query(query, tuple(params))

    if df_agents.empty:
        st.info("No agents yet. Agents are added automatically the first time you run an AI audit for them.")
        return

    col_widths = [2.2, 1.6, 1.6, 1.6, 1.4, 1.3]
    headers = ["Agent Name", "Employee ID", "Team", "Last Call", "Critical Calls", ""]
    header_cols = st.columns(col_widths)
    for col, label in zip(header_cols, headers):
        if label:
            col.markdown(f"<span class='col-header'>{label.upper()}</span>", unsafe_allow_html=True)

    for _, ag in df_agents.iterrows():
        crit = int(ag['critical_count'] or 0)
        last_call = str(ag['last_call'])[:16] if ag['last_call'] else "No calls yet"
        crit_html = (f"<span class='status-badge badge-critical'>{crit}</span>" if crit > 0
                     else "<span class='status-badge badge-passed'>0</span>")

        cols = st.columns(col_widths)
        cols[0].markdown(f"**{ag['name']}**")
        cols[1].markdown(id_chip(ag['id']), unsafe_allow_html=True)
        cols[2].write(ag['team'] or "—")
        cols[3].write(last_call)
        cols[4].markdown(crit_html, unsafe_allow_html=True)
        if cols[5].button("Open Calls →", key=f"open_agent_{ag['id']}", use_container_width=True):
            navigate_to("AgentDetails", agent_id=ag['id'])
            st.rerun()
        st.markdown("<hr class='row-divider'>", unsafe_allow_html=True)


# ==========================================
# 8. VIEW: AGENT DETAILS
# ==========================================
def view_agent_details():
    agent_id = st.session_state.selected_agent
    if not agent_id:
        st.warning("No agent selected.")
        if st.button("← Back to Agents"):
            navigate_to("Agents")
            st.rerun()
        return

    agent_df = run_query("SELECT * FROM agents WHERE id = ?", (agent_id,))
    if agent_df.empty:
        st.error("This agent no longer exists.")
        if st.button("← Back to Agents"):
            navigate_to("Agents")
            st.rerun()
        return
    agent_info = agent_df.iloc[0]

    if st.button("← Back to Agents"):
        navigate_to("Agents")
        st.rerun()

    st.title(f"👤 {agent_info['name']}")
    st.markdown(id_chip(agent_info['id']), unsafe_allow_html=True)
    st.caption(f"Team: {agent_info['team'] or '—'}  ·  {agent_info['email'] or 'No email on file'}")

    thirty_days_ago = (datetime.now().date() - timedelta(days=30)).isoformat()
    recent_stats = run_query(
        "SELECT AVG(qa_score) as avg_score, COUNT(*) as call_count FROM calls "
        "WHERE agent_id = ? AND substr(date, 1, 10) >= ?",
        (agent_id, thirty_days_ago),
    ).iloc[0]

    st.markdown("#### Score History")
    sh1, sh2 = st.columns(2)
    if recent_stats['call_count'] and recent_stats['call_count'] > 0:
        sh1.metric("Avg Score (Last 30 Days)", f"{recent_stats['avg_score']:.2f}/10")
    else:
        sh1.metric("Avg Score (Last 30 Days)", "—")
    sh2.metric("Calls (Last 30 Days)", int(recent_stats['call_count'] or 0))

    st.markdown("#### Call History")
    df_calls = run_query(
        "SELECT id as call_id, date, duration, qa_score, status FROM calls WHERE agent_id = ? ORDER BY date DESC",
        (agent_id,),
    )

    if df_calls.empty:
        st.info("No calls recorded for this agent yet.")
        return

    col_widths = [1.8, 1.6, 1.1, 1.0, 1.3, 1.3]
    headers = ["Call ID", "Date", "Duration", "QA Score", "Status", ""]
    header_cols = st.columns(col_widths)
    for col, label in zip(header_cols, headers):
        if label:
            col.markdown(f"<span class='col-header'>{label.upper()}</span>", unsafe_allow_html=True)

    for _, call in df_calls.iterrows():
        cols = st.columns(col_widths)
        cols[0].markdown(id_chip(call['call_id']), unsafe_allow_html=True)
        cols[1].write(str(call['date'])[:16])
        cols[2].write(call['duration'] or "—")
        cols[3].write(f"{call['qa_score']}/10")
        cols[4].markdown(status_badge(call['status']), unsafe_allow_html=True)
        if cols[5].button("View Report →", key=f"view_call_{call['call_id']}", use_container_width=True):
            navigate_to("CallReport", call_id=call['call_id'])
            st.rerun()
        st.markdown("<hr class='row-divider'>", unsafe_allow_html=True)


# ==========================================
# 9. VIEW: CALL REPORT
# ==========================================
def view_call_report():
    call_id = st.session_state.selected_call
    back_target = st.session_state.get("previous_view") or "Dashboard"

    if not call_id:
        st.warning("No call selected.")
        if st.button("← Back"):
            navigate_to(back_target)
            st.rerun()
        return

    df = run_query("""
        SELECT c.*, a.name as agent_name, a.id as employee_id, a.team,
               r.language, r.summary, r.violations, r.grammar_feedback, r.manager_notes,
               r.recommended_coaching, r.sentiment_start, r.sentiment_end
        FROM calls c
        JOIN agents a ON c.agent_id = a.id
        JOIN reports r ON c.id = r.call_id
        WHERE c.id = ?
    """, (call_id,))

    if df.empty:
        st.error("This report could not be found.")
        if st.button("← Back"):
            navigate_to(back_target)
            st.rerun()
        return

    call_data = df.iloc[0]

    if st.button("← Back"):
        navigate_to(back_target)
        st.rerun()

    st.title(" Call Report")
    st.markdown(id_chip(call_id), unsafe_allow_html=True)
    st.caption(f"Agent: {call_data['agent_name']} ({call_data['employee_id']})  ·  Audited: {str(call_data['date'])[:16]}")

    hc1, hc2, hc3, hc4 = st.columns(4)
    hc1.metric("QA Score", f"{call_data['qa_score']}/10")
    if call_data['manually_adjusted']:
        hc1.caption(" Manually adjusted")
    with hc2:
        st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
        st.markdown(status_badge(call_data['status']), unsafe_allow_html=True)
    hc3.metric("Profanity", "Flagged " if call_data['profanity_detected'] else "Clean ")
    with hc4:
        st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
        if call_data['status'] == "In Review":
            st.caption("🔵 Already flagged for review")
        else:
            if st.button(" Flag for Manual Review", use_container_width=True, key=f"flag_{call_id}"):
                execute_query("UPDATE calls SET status = ? WHERE id = ?", ("In Review", call_id))
                st.success("Flagged for manual review.")
                st.rerun()

    st.divider()

    sentiment_start = call_data['sentiment_start']
    sentiment_end = call_data['sentiment_end']
    if sentiment_start or sentiment_end:
        st.markdown("##### Customer Sentiment")
        sc1, sc2, sc3 = st.columns([1, 0.3, 1])
        sc1.markdown(f"Start of call<br>{sentiment_badge(sentiment_start)}", unsafe_allow_html=True)
        sc2.markdown("<div style='text-align:center;font-size:20px;margin-top:22px;color:#8A94A6;'>→</div>",
                     unsafe_allow_html=True)
        sc3.markdown(f"End of call<br>{sentiment_badge(sentiment_end)}", unsafe_allow_html=True)

        rank = {"Negative": 0, "Neutral": 1, "Positive": 2}
        if sentiment_start in rank and sentiment_end in rank:
            start_r, end_r = rank[sentiment_start], rank[sentiment_end]
            if end_r > start_r:
                st.caption("📈 Improved during the call.")
            elif end_r < start_r:
                st.caption("📉 Declined during the call.")
            elif sentiment_start == "Negative":
                st.caption("⚠️ Remained negative — no improvement.")
            elif sentiment_start == "Positive":
                st.caption("Stayed positive throughout.")
            else:
                st.caption("Stayed neutral throughout.")

        st.divider()

    with st.expander(" Audio Record Player", expanded=True):
        if call_data['audio_file'] and os.path.exists(str(call_data['audio_file'])):
            st.audio(call_data['audio_file'])
        else:
            st.info("Audio file archived or unavailable locally.")

    with st.expander(" Executive Summary", expanded=True):
        st.info(call_data['summary'] or "No summary available.")

    with st.expander(" Speech Transcription"):
        st.write(call_data['transcription'])

    with st.expander(" Detected Violations & Compliance", expanded=True):
        try:
            violations = json.loads(call_data['violations'])
        except (TypeError, ValueError):
            violations = None
        if violations:
            for v in violations:
                st.error(f"• {v}")
        else:
            st.success("No compliance violations detected.")

    with st.expander(" Grammar Analysis"):
        try:
            grammar = json.loads(call_data['grammar_feedback'])
        except (TypeError, ValueError):
            grammar = None
        if grammar:
            for err in grammar:
                st.warning(f"Spoken: {err.get('error')} ➔ Corrected: {err.get('correction')}")
                st.caption(f"Reason: {err.get('reason')}")
        else:
            st.success("Perfect grammar!")

    with st.expander(" Recommended Coaching", expanded=True):
        st.write(call_data['recommended_coaching'] or "No coaching notes generated for this call.")

    with st.expander(" Manager Notes", expanded=True):
        with st.form(f"notes_form_{call_id}"):
            notes_input = st.text_area(
                "Notes", value=call_data['manager_notes'] or "", height=100,
                label_visibility="collapsed", placeholder="Add manager notes for this call...",
            )
            if st.form_submit_button("💾 Save Notes"):
                execute_query("UPDATE reports SET manager_notes = ? WHERE call_id = ?", (notes_input, call_id))
                st.success("Notes saved.")
                st.rerun()

    with st.expander(" Override Score"):
        st.caption("Manually correct the AI-computed score. Status updates automatically to match.")
        with st.form(f"score_form_{call_id}"):
            new_score = st.number_input(
                "QA Score", min_value=0.0, max_value=10.0, step=0.1,
                value=float(call_data['qa_score']),
            )
            if st.form_submit_button(" Save Score"):
                new_score = round(new_score, 1)
                new_status = "Passed" if new_score >= 8.0 else ("Warning" if new_score >= 5.0 else "Critical")
                execute_query(
                    "UPDATE calls SET qa_score = ?, status = ?, manually_adjusted = 1 WHERE id = ?",
                    (new_score, new_status, call_id),
                )
                st.success("Score updated.")
                st.rerun()


# ==========================================
# 10. VIEW: RUN AI AUDIT (multi-file)
# ==========================================
# ==========================================
# AUDIT PIPELINE (thread-safe — no Streamlit calls in here)
# ==========================================
def _retry_after_seconds(exc):
    """Honour the server's own Retry-After / reset headers when it sends them."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or {}
    for key in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        raw = headers.get(key) or headers.get(key.title())
        if not raw:
            continue
        text = str(raw).strip().lower()
        try:
            if text.endswith("ms"):
                return float(text[:-2]) / 1000.0
            return float(text.rstrip("s"))
        except ValueError:
            continue
    return None


def call_with_backoff(fn, *args, **kwargs):
    """Exponential backoff with jitter on rate limits and transient 5xx.

    fn is called fresh on every attempt, so file handles must be opened inside
    it — a consumed file object cannot be re-sent on retry.
    """
    delay = 2.0
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status is None:
                status = getattr(getattr(exc, "response", None), "status_code", None)
            if status not in RETRYABLE_STATUS or attempt == MAX_RETRIES - 1:
                raise
            wait = _retry_after_seconds(exc) or delay
            time.sleep(min(wait, 60) + random.uniform(0, 1.0))
            delay = min(delay * 2, 60)


def build_audit_prompt(transcript_text, banned_rules):
    return f"""
                    You are a strict Senior Quality Assurance Auditor. Your job is NOT to coach on politeness or style, but to find STRICT GRAMMATICAL ERRORS ONLY, and verify structural requirements.

                    IMPORTANT:
                    This transcript has NO speaker labels — the agent's and customer's words are not
                    reliably distinguishable from raw transcription alone. Do not try to guess which
                    sentences belong to which speaker. Evaluate the full transcript against the checks
                    below as-is.

                    Transcript: "{transcript_text}"

                    Reference Lists:
                    - English Banned Phrases: {banned_rules.get('english_banned', [])}
                    - Spanish Banned Phrases: {banned_rules.get('spanish_banned', [])}
                    - English Offensive Words: {banned_rules.get('english_offensive', [])}
                    - Spanish Offensive Words: {banned_rules.get('spanish_offensive', [])}

                    Tasks to execute:
                    1. Detect primary spoken language (English or Spanish).
                    2. Check if ANY exact phrase from the Banned lists above appears anywhere in the transcript. List them in `banned_words_found`.
                    3. Check if ANY exact word from the Offensive lists above appears anywhere in the transcript. List them in `offensive_words_found`. Set `has_profanity` to true if any are found.
                    4. Separately, using your own judgment, identify any OTHER genuinely vulgar, profane, or offensive language anywhere in the transcript that is NOT already on the Banned/Offensive lists above. List these in `general_profanity_found`. Do not duplicate anything already captured in `offensive_words_found` or `banned_words_found`. Set `has_profanity` to true if this list is non-empty too.
                       - Only flag language that is genuinely vulgar, profane, or offensive (swearing, slurs, crude insults). Do NOT flag language that is merely blunt, informal, or impolite.
                    5. Scan the ENTIRE transcript for any use of the Arabic language — any Arabic word, phrase, or sentence, in any context.
                       - Do NOT count proper names (people's names, company names, place names) as Arabic, even if they are Arabic in origin — only actual Arabic-language speech counts.
                       - Set `arabic_detected` to true if any is found, and list the specific Arabic text found in `arabic_words_found`. If none is found, set `arabic_detected` to false and leave `arabic_words_found` empty.
                    6. Check for GRAMMAR ERRORS ONLY in the transcript.
                       - STRICT RULE: Do NOT flag sentences just because they lack politeness, or because you want a "better phrasing".
                       - Only flag undeniable grammar, tense, or syntax structural breakages.
                       - If there are no true grammar errors, return an empty list [].
                    7. Check if the call opens with a formal professional greeting.
                       A formal greeting MUST include ALL of the following:
                       - Greeting
                       - Agent name
                       - Company introduction
                       If ANY required element is missing, set `formal_greeting_made` to false.
                    8. Rate the CUSTOMER's sentiment at the very beginning of the call and again at the very end of the call. Each must be exactly one of "Positive", "Neutral", or "Negative" — this is used to see whether the agent improved or de-escalated the interaction.
                    9. Write a short executive audit summary paragraph.
                    10. Write 1-3 short, actionable coaching recommendations for this agent's manager.

                    Return ONLY a valid JSON object matching this structure precisely:
                    {{
                      "language": "English/Spanish",
                      "has_profanity": true/false,
                      "formal_greeting_made": true/false,
                      "offensive_words_found": [],
                      "banned_words_found": [],
                      "general_profanity_found": [],
                      "arabic_detected": true/false,
                      "arabic_words_found": [],
                      "grammar_errors": [
                        {{"error": "string", "correction": "string", "reason": "string"}}
                      ],
                      "sentiment_start": "Positive/Neutral/Negative",
                      "sentiment_end": "Positive/Neutral/Negative",
                      "audit_summary": "string summary paragraph",
                      "recommended_coaching": "string with 1-3 short coaching recommendations"
                    }}
                    """


def score_result(result):
    """Pure scoring — identical weights to the original, just factored out."""
    grammar_errs = result.get("grammar_errors", [])
    banned_words = result.get("banned_words_found", [])
    offensive_words = result.get("offensive_words_found", [])
    general_profanity = result.get("general_profanity_found", [])
    arabic_detected = result.get("arabic_detected", False)
    arabic_words_found = result.get("arabic_words_found", [])
    # Default to True (no penalty) if the model omits the field, so a
    # missing key never silently costs the agent a point.
    formal_greeting_made = result.get("formal_greeting_made", True)

    grammar_penalty = min(len(grammar_errs) * 0.15, 2.0)
    # general_profanity is weighted the same as configured offensive words (-2.0 each) —
    # no separate weight was specified, so this matches the existing tier.
    offensive_penalty = (len(offensive_words) + len(general_profanity)) * 2.0
    banned_penalty = len(banned_words) * 1.0
    greeting_penalty = 0.0 if formal_greeting_made else 1.0

    grammar_score = round(max(0.0, 10.0 - grammar_penalty), 1)
    final_score = round(
        max(0.0, 10.0 - grammar_penalty - offensive_penalty - banned_penalty - greeting_penalty), 1
    )

    call_status = "Passed" if final_score >= 8.0 else ("Warning" if final_score >= 5.0 else "Critical")
    profanity_flag = 1 if (result.get("has_profanity") or offensive_words or general_profanity) else 0

    all_violations = banned_words + offensive_words + general_profanity
    if not formal_greeting_made:
        all_violations.append("Missing formal greeting at the beginning of the call.")
    if arabic_detected:
        # Informational only — doesn't affect qa_score unless you ask for a penalty too.
        if arabic_words_found:
            all_violations.append(f"Arabic language detected: {', '.join(arabic_words_found)}")
        else:
            all_violations.append("Arabic language detected during the call.")

    return {
        "final_score": final_score,
        "grammar_score": grammar_score,
        "call_status": call_status,
        "profanity_flag": profanity_flag,
        "all_violations": all_violations,
        "grammar_errs": grammar_errs,
    }


def process_one_call(client, banned_rules, filename, audio_bytes, call_uid):
    """Runs in a worker thread. Returns a plain dict — never touches st.* or the DB."""
    ext = os.path.splitext(filename)[1] or ".mp3"
    audio_path = os.path.join(AUDIO_DIR, f"{call_uid}{ext}")
    try:
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        def _transcribe():
            # Re-opened per attempt: a spent file handle can't be replayed on retry.
            with open(audio_path, "rb") as fh:
                return client.audio.transcriptions.create(model="whisper-large-v3", file=fh)

        transcript_text = call_with_backoff(_transcribe).text

        response = call_with_backoff(
            client.chat.completions.create,
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": build_audit_prompt(transcript_text, banned_rules)}],
        )

        try:
            result = json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            return {"ok": False, "filename": filename, "error": "couldn't parse the AI's response"}

        scored = score_result(result)
        return {
            "ok": True,
            "filename": filename,
            "call_uid": call_uid,
            "audio_path": audio_path,
            "transcript_text": transcript_text,
            "result": result,
            **scored,
        }
    except Exception as exc:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        return {"ok": False, "filename": filename, "error": str(exc)}


def audio_store_size_mb():
    total = 0
    for name in os.listdir(AUDIO_DIR):
        path = os.path.join(AUDIO_DIR, name)
        if os.path.isfile(path):
            total += os.path.getsize(path)
    return total / (1024 * 1024)


def view_auditor():
    st.title("Analyze Call")

    with st.form("audit_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            agent_id = st.text_input(" Agent ID", placeholder="The code")
        with c2:
            agent_name = st.text_input(" Agent Name", placeholder="all lowercase")
        with c3:
            agent_team = st.text_input(" Team leader", placeholder=" all lowercase")

        uploaded_files = st.file_uploader(
            " Upload Audio Records (multiple allowed)",
            type=["mp3", "wav", "m4a"],
            accept_multiple_files=True,
        )

        submit_btn = st.form_submit_button(" Run ", type="primary")

    if submit_btn:
        if not agent_id or not agent_name or not uploaded_files:
            st.error(" Please fill in all agent details and upload at least one audio file.")
        elif not SERVER_GROQ_KEY:
            st.error(" No API key configured. Add API_KEY.")
        else:
            client = OpenAI(api_key=SERVER_GROQ_KEY, base_url="https://api.groq.com/openai/v1")
            banned_rules = load_banned_rules()

            # Register the agent once — not once per file.
            execute_query(
                "INSERT OR IGNORE INTO agents (id, name, team, email) VALUES (?, ?, ?, ?)",
                (agent_id, agent_name, agent_team, f"{agent_id}@company.com"),
            )

            total_files = len(uploaded_files)
            progress_bar = st.progress(0.0)
            status_area = st.container()
            new_calls = []
            success_count = 0
            done_count = 0

            call_rows = []
            report_rows = []

            # Chunked so that (a) peak memory stays bounded and (b) each chunk is
            # committed before the next starts — a closed tab loses one chunk, not
            # the whole batch.
            for chunk_start in range(0, total_files, CHUNK_SIZE):
                chunk = uploaded_files[chunk_start:chunk_start + CHUNK_SIZE]
                call_rows.clear()
                report_rows.clear()

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {}
                    for uploaded_file in chunk:
                        # uuid4, not a timestamp+index: two batches submitted in the
                        # same second both started at index 0 and collided on the
                        # primary key.
                        call_uid = f"CALL_{uuid.uuid4().hex[:12].upper()}"
                        future = pool.submit(
                            process_one_call,
                            client,
                            banned_rules,
                            uploaded_file.name,
                            uploaded_file.getbuffer().tobytes(),
                            call_uid,
                        )
                        futures[future] = uploaded_file.name

                    for future in as_completed(futures):
                        outcome = future.result()
                        done_count += 1
                        progress_bar.progress(done_count / total_files)

                        if not outcome["ok"]:
                            status_area.markdown(
                                f"<div class='audit-row-err'> <b>{outcome['filename']}</b> — "
                                f"{outcome['error']}</div>",
                                unsafe_allow_html=True,
                            )
                            continue

                        result = outcome["result"]
                        call_rows.append((
                            outcome["call_uid"], agent_id, str(datetime.now()), "N/A",
                            outcome["audio_path"], outcome["transcript_text"],
                            outcome["final_score"], outcome["grammar_score"],
                            outcome["call_status"], outcome["profanity_flag"],
                        ))
                        report_rows.append((
                            outcome["call_uid"], result.get("language"), result.get("audit_summary"),
                            json.dumps(outcome["all_violations"]), json.dumps(outcome["grammar_errs"]),
                            "", result.get("recommended_coaching"),
                            result.get("sentiment_start"), result.get("sentiment_end"),
                        ))
                        new_calls.append((
                            outcome["call_uid"], outcome["filename"],
                            outcome["final_score"], outcome["call_status"],
                        ))
                        success_count += 1
                        status_area.markdown(
                            f"<div class='audit-row-ok'> <b>{outcome['filename']}</b> — "
                            f"{outcome['final_score']}/10 {status_badge(outcome['call_status'])}</div>",
                            unsafe_allow_html=True,
                        )

                # One transaction per chunk: calls and their reports land together
                # or not at all.
                try:
                    execute_batch([
                        ("""INSERT INTO calls (id, agent_id, date, duration, audio_file, transcription,
                                               qa_score, grammar_score, status, profanity_detected)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", list(call_rows)),
                        ("""INSERT INTO reports (call_id, language, summary, violations, grammar_feedback,
                                                 manager_notes, recommended_coaching, sentiment_start, sentiment_end)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", list(report_rows)),
                    ])
                except Exception as exc:
                    success_count -= len(call_rows)
                    status_area.error(f"Chunk failed to save: {exc}")

            st.success(f" Audited {success_count} of {total_files} call(s) for {agent_name}.")
            if new_calls:
                st.session_state.last_audited_calls = new_calls

    if st.session_state.get("last_audited_calls"):
        st.markdown("#### Just Audited")
        for call_uid, fname, score, call_status in st.session_state.last_audited_calls:
            rc = st.columns([3, 1.2, 1.3, 1.5])
            rc[0].write(fname)
            rc[1].write(f"{score}/10")
            rc[2].markdown(status_badge(call_status), unsafe_allow_html=True)
            if rc[3].button("View Report →", key=f"view_new_{call_uid}", use_container_width=True):
                navigate_to("CallReport", call_id=call_uid)
                st.session_state.last_audited_calls = None
                st.rerun()


# ==========================================
# 11. VIEW: SETTINGS
# ==========================================
def view_settings():
    st.title(" Settings")
    st.caption("Configure the words and phrases the AI auditor checks for.")

    rules = load_banned_rules()

    st.markdown("####  Banned Phrases")
    st.caption("Exact phrases agents should never say (e.g. dismissive language). One per line.")
    banned_en = st.text_area("English banned phrases", value="\n".join(rules.get("english_banned", [])), height=140)
    banned_es = st.text_area("Spanish banned phrases", value="\n".join(rules.get("spanish_banned", [])), height=100)

    st.markdown("####  Offensive Words")
    st.caption("Individual words that should always be flagged as profanity. One per line.")
    off_en = st.text_area("English offensive words", value="\n".join(rules.get("english_offensive", [])), height=100)
    off_es = st.text_area("Spanish offensive words", value="\n".join(rules.get("spanish_offensive", [])), height=100)

    if st.button(" Save Changes", type="primary"):
        save_banned_rules({
            "english_banned": [w.strip() for w in banned_en.splitlines() if w.strip()],
            "spanish_banned": [w.strip() for w in banned_es.splitlines() if w.strip()],
            "english_offensive": [w.strip() for w in off_en.splitlines() if w.strip()],
            "spanish_offensive": [w.strip() for w in off_es.splitlines() if w.strip()],
        })
        st.success("Saved. New rules apply to the next audit you run.")


# ==========================================
# 12. ROUTE TO THE ACTIVE VIEW
# ==========================================
VIEW_ROUTER = {
    "Dashboard": view_dashboard,
    "Agents": view_agents,
    "AgentDetails": view_agent_details,
    "CallReport": view_call_report,
    "Auditor": view_auditor,
    "Settings": view_settings,
}
VIEW_ROUTER.get(st.session_state.current_view, view_dashboard)()
