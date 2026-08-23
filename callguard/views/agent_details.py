"""Agent details: 30-day KPIs, score trend and call history."""

import math
from datetime import datetime, timedelta

import streamlit as st

from callguard.components import (
    render_column_headers,
    render_pager,
    row_cols,
    row_container,
    score_trend_chart,
)
from callguard.config import PAGE_SIZE, PASS_THRESHOLD
from callguard.database import run_query, scalar
from callguard.formatting import (
    empty_state,
    esc,
    fmt_date,
    fmt_duration,
    id_chip,
    kpi,
    score_cell,
    status_badge,
)
from callguard.navigation import navigate_to


def view_agent_details():
    agent_id = st.session_state.selected_agent
    if not agent_id:
        st.warning("No agent selected.")
        if st.button("← Back to agents"):
            navigate_to("Agents")
            st.rerun()
        return

    agent_df = run_query("SELECT * FROM agents WHERE id = ?", (agent_id,))
    if agent_df.empty:
        st.error("This agent no longer exists.")
        if st.button("← Back to agents"):
            navigate_to("Agents")
            st.rerun()
        return
    agent = agent_df.iloc[0]

    if st.button("← Back to agents", key="agent_back"):
        navigate_to("Agents")
        st.rerun()

    st.title(agent["name"] or "Unnamed agent")
    st.markdown(id_chip(agent["id"]), unsafe_allow_html=True)
    st.caption(f"Team: {agent['team'] or '—'}")

    thirty_days_ago = (datetime.now().date() - timedelta(days=30)).isoformat()
    recent = run_query("""
        SELECT AVG(qa_score) AS avg_score, COUNT(*) AS call_count,
               SUM(CASE WHEN status='Critical' THEN 1 ELSE 0 END) AS critical,
               SUM(COALESCE(profanity_detected,0)) AS profanity
        FROM calls WHERE agent_id = ? AND substr(date, 1, 10) >= ?
    """, (agent_id, thirty_days_ago)).iloc[0]
    lifetime = run_query(
        "SELECT AVG(qa_score) AS avg_score, COUNT(*) AS call_count FROM calls WHERE agent_id = ?",
        (agent_id,)).iloc[0]

    recent_avg = recent["avg_score"]
    life_avg = lifetime["avg_score"]
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi("Avg score · 30 days",
                    f"{recent_avg:.1f}" if recent_avg and not math.isnan(recent_avg) else "—",
                    f"lifetime {life_avg:.1f}" if life_avg and not math.isnan(life_avg) else "no history",
                    "good" if (recent_avg or 0) >= PASS_THRESHOLD else "warn"),
                unsafe_allow_html=True)
    k2.markdown(kpi("Calls · 30 days", int(recent["call_count"] or 0),
                    f"{int(lifetime['call_count'] or 0)} lifetime", "info"),
                unsafe_allow_html=True)
    k3.markdown(kpi("Critical · 30 days", int(recent["critical"] or 0),
                    "calls scoring below 5.0",
                    "crit" if recent["critical"] else "good"), unsafe_allow_html=True)
    k4.markdown(kpi("Profanity · 30 days", int(recent["profanity"] or 0),
                    "flagged language detected",
                    "crit" if recent["profanity"] else "good"), unsafe_allow_html=True)

    df_calls = run_query("""
        SELECT id AS call_id, date, duration_seconds, qa_score, status, manually_adjusted
        FROM calls WHERE agent_id = ? ORDER BY date DESC
    """, (agent_id,))

    if df_calls.empty:
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown(empty_state("No calls recorded for this agent yet",
                                "Upload recordings from the Run audit screen to populate this page."),
                    unsafe_allow_html=True)
        return

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown("#### Score trend")
    team_avg = None
    if agent["team"]:
        team_avg = scalar("""
            SELECT AVG(c.qa_score) FROM calls c JOIN agents a ON c.agent_id = a.id
            WHERE a.team = ?
        """, (agent["team"],), default=None)
    trend = df_calls.rename(columns={"date": "when"}).sort_values("when").tail(60)
    score_trend_chart(trend, team_avg)

    st.markdown("#### Call history")
    widths = [1.9, 1.7, 1.1, 1.3, 1.3, 1.2]
    render_column_headers(widths, ["Call ID", "Date", "Length", "QA score", "Status", ""])

    total = len(df_calls)
    offset = min(st.session_state.page, max(0, math.ceil(total / PAGE_SIZE) - 1)) * PAGE_SIZE
    for _, call in df_calls.iloc[offset:offset + PAGE_SIZE].iterrows():
        with row_container():
            st.markdown("<span class='cg-row'></span>", unsafe_allow_html=True)
            cols = row_cols(widths)
            cols[0].markdown(id_chip(call["call_id"]), unsafe_allow_html=True)
            cols[1].markdown(f"<div class='cg-cell'>{esc(fmt_date(call['date']))}</div>",
                             unsafe_allow_html=True)
            cols[2].markdown(
                f"<div class='cg-cell'>{esc(fmt_duration(call['duration_seconds']))}</div>",
                unsafe_allow_html=True)
            adjusted = "<div class='sub'>adjusted</div>" if call["manually_adjusted"] else ""
            cols[3].markdown(score_cell(call["qa_score"]) + adjusted, unsafe_allow_html=True)
            cols[4].markdown(status_badge(call["status"]), unsafe_allow_html=True)
            if cols[5].button("Report →", key=f"view_call_{call['call_id']}",
                              use_container_width=True):
                navigate_to("CallReport", call_id=call["call_id"])
                st.rerun()

    if total > PAGE_SIZE:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        render_pager(total, "agentdet")
