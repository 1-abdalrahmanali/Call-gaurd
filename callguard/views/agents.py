"""Agents: top performers and the agent directory."""

from datetime import datetime, timedelta

import streamlit as st

from callguard.components import render_column_headers, row_cols, row_container
from callguard.database import run_query
from callguard.formatting import empty_state, esc, fmt_date, id_chip, score_cell
from callguard.navigation import navigate_to


def view_agents():
    st.title("Agents")
    st.caption("Find an agent, then open their call history.")

    thirty_days_ago = (datetime.now().date() - timedelta(days=30)).isoformat()
    df_top = run_query("""
        SELECT a.id, a.name, a.team, AVG(c.qa_score) AS avg_score, COUNT(c.id) AS call_count
        FROM agents a JOIN calls c ON a.id = c.agent_id
        WHERE substr(c.date, 1, 10) >= ?
        GROUP BY a.id HAVING COUNT(c.id) >= 1
        ORDER BY avg_score DESC LIMIT 5
    """, (thirty_days_ago,))

    if not df_top.empty:
        st.markdown("##### Top performers · last 30 days")
        for col, (rank, (_, row)) in zip(st.columns(len(df_top)),
                                         enumerate(df_top.iterrows(), start=1)):
            call_word = "call" if row["call_count"] == 1 else "calls"
            col.markdown(f"""
                <div class="top-performer-card">
                  <div class="rank">#{rank}</div>
                  <div style="font-weight:600;color:var(--text-1);font-size:13px;margin-top:3px;">
                    {esc(row['name'])}</div>
                  <div style="color:var(--text-3);font-size:11px;margin-top:2px;">
                    {esc(row['team'] or '—')}</div>
                  <div style="color:var(--warn);font-weight:700;font-size:20px;margin-top:8px;
                              letter-spacing:-.02em;">{float(row['avg_score'] or 0):.1f}
                    <span style="font-size:11px;color:var(--text-3);font-weight:500;">/10</span></div>
                  <div style="color:var(--text-3);font-size:11px;">
                    {int(row['call_count'])} {call_word}</div>
                </div>
            """, unsafe_allow_html=True)
        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    search = st.text_input("Search agents", key="agent_search",
                           placeholder="Search by agent name or agent ID",
                           label_visibility="collapsed")

    query = """
        SELECT a.id, a.name, a.team,
               MAX(c.date) AS last_call,
               COUNT(c.id) AS call_count,
               AVG(c.qa_score) AS avg_score,
               SUM(CASE WHEN c.status = 'Critical' THEN 1 ELSE 0 END) AS critical_count
        FROM agents a LEFT JOIN calls c ON a.id = c.agent_id
    """
    params = []
    if search:
        like = f"%{search}%"
        query += " WHERE a.name LIKE ? OR a.id LIKE ?"
        params = [like, like]
    query += " GROUP BY a.id ORDER BY a.name"
    df_agents = run_query(query, tuple(params))

    if df_agents.empty:
        st.markdown(empty_state(
            "No agents yet" if not search else "No agents match that search",
            "Agents are created automatically the first time you run an audit for them."
        ), unsafe_allow_html=True)
        return

    widths = [2.2, 1.5, 1.5, 1.5, 1.2, 1.2, 1.3]
    render_column_headers(widths, ["Agent", "Employee ID", "Team", "Last call",
                                   "Calls", "Avg score", ""])

    for _, agent in df_agents.iterrows():
        crit = int(agent["critical_count"] or 0)
        with row_container():
            st.markdown("<span class='cg-row'></span>", unsafe_allow_html=True)
            cols = row_cols(widths)
            crit_note = (f"<div class='sub' style='color:var(--crit)'>{crit} critical</div>"
                         if crit else "")
            cols[0].markdown(
                f"<div class='cg-cell'><b>{esc(agent['name'])}</b>{crit_note}</div>",
                unsafe_allow_html=True)
            cols[1].markdown(id_chip(agent["id"]), unsafe_allow_html=True)
            cols[2].markdown(f"<div class='cg-cell'>{esc(agent['team'] or '—')}</div>",
                             unsafe_allow_html=True)
            cols[3].markdown(
                f"<div class='cg-cell'>{esc(fmt_date(agent['last_call']) or 'No calls yet')}</div>",
                unsafe_allow_html=True)
            cols[4].markdown(f"<div class='cg-cell'>{int(agent['call_count'] or 0)}</div>",
                             unsafe_allow_html=True)
            cols[5].markdown(score_cell(agent["avg_score"]), unsafe_allow_html=True)
            if cols[6].button("Open →", key=f"open_agent_{agent['id']}",
                              use_container_width=True):
                navigate_to("AgentDetails", agent_id=agent["id"])
                st.rerun()
