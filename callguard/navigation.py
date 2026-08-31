"""URL/session routing and the sidebar."""

import streamlit as st

from callguard.config import (
    APP_NAME,
    APP_TAGLINE,
    AUDIT_API_KEY,
    BUILT_BY,
    TRANSCRIBE_API_KEY,
)
from callguard.database import run_query
from callguard.formatting import esc
from callguard.theme import C_CRIT, C_INFO
from callguard.accounts import current_user
from callguard.auth import sign_out
from callguard.formatting import initials


def sync_query_params(params):
    """Best-effort URL sync. Query params must be strings."""
    try:
        st.query_params.clear()
        st.query_params.update({k: str(v) for k, v in params.items() if v})
    except Exception:
        pass


def read_query_params():
    try:
        return dict(st.query_params)
    except Exception:
        return {}
def navigate_to(view, agent_id=None, call_id=None):
    if view == "CallReport":
        st.session_state.previous_view = st.session_state.current_view
    if view != st.session_state.current_view:
        st.session_state.page = 0
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
    view = st.session_state.current_view
    if view == "AgentDetails":
        return "Agents"
    if view == "CallReport":
        previous = st.session_state.get("previous_view")
        if previous == "AgentDetails":
            return "Agents"
        return previous if previous in {"Auditor", "Agents"} else "Dashboard"
    return view
NAV_ITEMS = [
    ("Dashboard", "Dashboard"),
    ("Agents", "Agents"),
    ("Auditor", "Run audit"),
    ("Settings", "Settings"),
]


def init_state():
    """Seed session state from the URL query string. Call once per run."""
    _qp = read_query_params()
    st.session_state.setdefault("current_view", _qp.get("view", "Dashboard"))
    st.session_state.setdefault("selected_agent", _qp.get("agent_id"))
    st.session_state.setdefault("selected_call", _qp.get("call_id"))
    st.session_state.setdefault("previous_view", None)
    st.session_state.setdefault("last_audited_calls", None)
    st.session_state.setdefault("data_version", 0)
    st.session_state.setdefault("page", 0)


def render_sidebar():
    """Draw the sidebar. Returns nothing; navigation reruns the script."""
    with st.sidebar:
        st.markdown(
            "<div class='cg-brand'><div class='mark'>CG</div>"
            f"<div><div class='name'>{APP_NAME}</div>"
            f"<div class='sub'>{APP_TAGLINE}</div></div></div>",
            unsafe_allow_html=True,
        )

        _user = current_user()
        if _user:
            _role = (f"<div class='u-role'>{esc(_user['role'])}</div>"
                     if _user.get("role") else "")
            st.markdown(
                "<div class='cg-user'>"
                f"<div class='u-avatar'>{esc(initials(_user['name']))}</div>"
                f"<div><div class='u-name'>{esc(_user['name'])}</div>{_role}</div>"
                "</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div class='cg-navlabel'>Workspace</div>", unsafe_allow_html=True)
        _active = active_nav_key()
        for _key, _label in NAV_ITEMS:
            if st.button(_label, use_container_width=True, key=f"nav_{_key}",
                         type="primary" if _active == _key else "secondary"):
                navigate_to(_key)
                st.rerun()

        st.markdown("<div class='cg-navlabel'>At a glance</div>", unsafe_allow_html=True)
        _totals = run_query(
            "SELECT COUNT(*) AS calls, "
            "SUM(CASE WHEN status='Critical' THEN 1 ELSE 0 END) AS crit, "
            "SUM(CASE WHEN status='In Review' THEN 1 ELSE 0 END) AS review FROM calls"
        ).iloc[0]
        st.markdown(
            "<div class='cg-sidefoot'>"
            f"<b>{int(_totals['calls'] or 0)}</b> calls audited<br>"
            f"<span style='color:{C_CRIT}'>●</span> <b>{int(_totals['crit'] or 0)}</b> critical<br>"
            f"<span style='color:{C_INFO}'>●</span> <b>{int(_totals['review'] or 0)}</b> in review"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        if not TRANSCRIBE_API_KEY or not AUDIT_API_KEY:
            st.warning("API key missing — audits are disabled.")

        st.divider()
        if st.button("Log out", use_container_width=True, key="logout_btn"):
            sign_out()
            sync_query_params({})
            st.rerun()

        st.markdown(
            f"<div class='cg-sidefoot' style='margin-top:10px;'>Built by <b>{esc(BUILT_BY)}</b><br>"
            "All rights reserved</div>",
            unsafe_allow_html=True,
        )
