"""Dashboard: search, filters, KPIs, call list and the critical queue."""

import math
from datetime import datetime, timedelta

import streamlit as st

from callguard.components import (
    render_column_headers,
    render_pager,
    render_status_distribution,
    row_cols,
    row_container,
)
from callguard.config import PAGE_SIZE, PASS_THRESHOLD
from callguard.database import run_query
from callguard.exports import agent_scores_csv
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


STATUS_PRESETS = {
    "All statuses": None,
    "Passed only": ["Passed"],
    "Needs attention": ["Warning", "Critical"],
    "Critical only": ["Critical"],
    "In review": ["In Review"],
}


def view_dashboard():
    st.title("QA Operations")
    st.caption("Search calls, filter by team and date, then open a report.")

    # --- Filters: one row above the content -------------------------------
    search_query = st.text_input(
        "Search", placeholder="Agent name, agent ID, or call ID",
        label_visibility="collapsed", key="dash_search",
    )

    f1, f2, f3 = st.columns([1.4, 2.1, 1.5])
    teams = ["All Teams"] + sorted(
        t for t in run_query("SELECT DISTINCT team FROM agents")["team"].dropna().tolist() if t
    )
    with f1:
        team_filter = st.selectbox("Team", teams, key="dash_team")
    with f2:
        today = datetime.now().date()
        date_range = st.date_input("Date range", key="dash_dates",
                                   value=(today - timedelta(days=365), today))
    with f3:
        status_preset = st.selectbox("Status", list(STATUS_PRESETS), key="dash_status")
    status_list = STATUS_PRESETS[status_preset]

    start_date = end_date = None
    if isinstance(date_range, (list, tuple)):
        if len(date_range) == 2:
            start_date, end_date = date_range
        elif len(date_range) == 1:
            start_date = end_date = date_range[0]
    elif date_range:
        start_date = end_date = date_range

    # --- Build the WHERE clause once, reuse it everywhere ------------------
    where, params = ["1=1"], []
    if search_query:
        like = f"%{search_query}%"
        where.append("(a.name LIKE ? OR a.id LIKE ? OR c.id LIKE ?)")
        params += [like, like, like]
    if team_filter != "All Teams":
        where.append("a.team = ?")
        params.append(team_filter)
    if status_list:
        where.append(f"c.status IN ({','.join('?' * len(status_list))})")
        params += status_list
    if start_date:
        where.append("substr(c.date, 1, 10) >= ?")
        params.append(start_date.isoformat())
    if end_date:
        where.append("substr(c.date, 1, 10) <= ?")
        params.append(end_date.isoformat())
    clause = " AND ".join(where)
    params = tuple(params)

    # --- KPI row ----------------------------------------------------------
    stats = run_query(f"""
        SELECT COUNT(*) AS total,
               AVG(c.qa_score) AS avg_score,
               SUM(CASE WHEN c.status='Passed'    THEN 1 ELSE 0 END) AS passed,
               SUM(CASE WHEN c.status='Warning'   THEN 1 ELSE 0 END) AS warning,
               SUM(CASE WHEN c.status='Critical'  THEN 1 ELSE 0 END) AS critical,
               SUM(CASE WHEN c.status='In Review' THEN 1 ELSE 0 END) AS in_review,
               SUM(COALESCE(c.profanity_detected,0)) AS profanity,
               SUM(COALESCE(c.duration_seconds,0))   AS total_seconds
        FROM calls c JOIN agents a ON c.agent_id = a.id
        WHERE {clause}
    """, params).iloc[0]

    total = int(stats["total"] or 0)
    avg_score = stats["avg_score"]
    critical = int(stats["critical"] or 0)
    profanity = int(stats["profanity"] or 0)
    crit_rate = (critical / total * 100) if total else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi("Calls audited", f"{total:,}",
                    fmt_duration(stats["total_seconds"]) + " of audio" if stats["total_seconds"]
                    else "in the selected range", "info"), unsafe_allow_html=True)
    k2.markdown(kpi("Average QA score",
                    f"{avg_score:.1f}" if avg_score and not math.isnan(avg_score) else "—",
                    f"pass mark is {PASS_THRESHOLD:.0f}.0",
                    "good" if (avg_score or 0) >= PASS_THRESHOLD else "warn"),
                unsafe_allow_html=True)
    k3.markdown(kpi("Critical rate", f"{crit_rate:.0f}%",
                    f"{critical} of {total} calls",
                    "crit" if crit_rate >= 10 else "good"), unsafe_allow_html=True)
    k4.markdown(kpi("Profanity flags", f"{profanity:,}",
                    "calls containing flagged language",
                    "crit" if profanity else "good"), unsafe_allow_html=True)

    if total:
        st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
        st.markdown("##### Status mix")
        render_status_distribution(
            {"Passed": stats["passed"], "Warning": stats["warning"],
             "Critical": stats["critical"], "In Review": stats["in_review"]},
            total,
        )

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # --- Call list --------------------------------------------------------
    head_left, head_right = st.columns([3, 1])
    head_left.markdown("#### Calls")

    if not total:
        st.markdown(empty_state(
            "Nothing matches these filters",
            "Try widening the date range, clearing the search box, or choosing All Teams."
        ), unsafe_allow_html=True)
        return

    offset = min(st.session_state.page, max(0, math.ceil(total / PAGE_SIZE) - 1)) * PAGE_SIZE
    df_calls = run_query(f"""
        SELECT c.id AS call_id, a.name AS agent_name, a.id AS employee_id,
               c.date, c.duration_seconds, c.qa_score, c.status, c.manually_adjusted
        FROM calls c JOIN agents a ON c.agent_id = a.id
        WHERE {clause}
        ORDER BY c.date DESC
        LIMIT ? OFFSET ?
    """, params + (PAGE_SIZE, offset))

    # Agent-level summary across the WHOLE filtered set, not just this page.
    df_export = run_query(f"""
        SELECT a.name AS agent_name, a.id AS agent_id, AVG(c.qa_score) AS avg_score
        FROM calls c JOIN agents a ON c.agent_id = a.id
        WHERE {clause}
        GROUP BY a.id
        ORDER BY a.name
    """, params)
    head_right.download_button(
        "Export CSV",
        agent_scores_csv(df_export),
        file_name=f"callguard_agent_scores_{datetime.now():%Y%m%d_%H%M}.csv",
        mime="text/csv", use_container_width=True, key="dash_export",
    )

    widths = [2.4, 1.6, 1.5, 1.0, 1.2, 1.3, 1.1]
    render_column_headers(widths, ["Agent", "Call ID", "Date", "Length",
                                   "QA Score", "Status", ""])

    for _, row in df_calls.iterrows():
        with row_container():
            st.markdown("<span class='cg-row'></span>", unsafe_allow_html=True)
            cols = row_cols(widths)
            cols[0].markdown(
                f"<div class='cg-cell'><b>{esc(row['agent_name'])}</b><br>"
                f"{id_chip(row['employee_id'])}</div>", unsafe_allow_html=True)
            cols[1].markdown(id_chip(row["call_id"]), unsafe_allow_html=True)
            cols[2].markdown(
                f"<div class='cg-cell'>{esc(fmt_date(row['date'], 10))}"
                f"<div class='sub'>{esc(fmt_date(row['date'])[11:])}</div></div>",
                unsafe_allow_html=True)
            cols[3].markdown(
                f"<div class='cg-cell'>{esc(fmt_duration(row['duration_seconds']))}</div>",
                unsafe_allow_html=True)
            adjusted = "<div class='sub'>adjusted</div>" if row["manually_adjusted"] else ""
            cols[4].markdown(score_cell(row["qa_score"]) + adjusted, unsafe_allow_html=True)
            cols[5].markdown(status_badge(row["status"]), unsafe_allow_html=True)
            if cols[6].button("Open →", key=f"open_call_{row['call_id']}",
                              use_container_width=True):
                navigate_to("CallReport", call_id=row["call_id"])
                st.rerun()

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    render_pager(total, "dash")

    # --- Critical queue ---------------------------------------------------
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown("#### Critical queue")
    df_critical = run_query(f"""
        SELECT c.id AS call_id, a.name AS agent_name, c.qa_score, c.date, r.summary
        FROM calls c
        JOIN agents a ON c.agent_id = a.id
        LEFT JOIN reports r ON c.id = r.call_id
        WHERE {clause} AND c.status = 'Critical'
        ORDER BY c.date DESC LIMIT 8
    """, params)

    if df_critical.empty:
        st.markdown(empty_state("No critical calls in this range",
                                "Every audited call scored at or above 5.0."),
                    unsafe_allow_html=True)
        return

    for _, row in df_critical.iterrows():
        reason = (row["summary"] or "No summary available for this call.").strip()
        if len(reason) > 180:
            reason = reason[:180].rstrip() + "…"
        card, action = st.columns([5, 1])
        card.markdown(f"""
            <div class="critical-alert-card">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:14px;">
                <div>
                  <div style="font-weight:600;color:var(--text-1);font-size:13.5px;">
                    {esc(row['agent_name'])}
                    <span style="color:var(--text-3);font-weight:400;font-size:12px;">
                      · {esc(fmt_date(row['date'], 10))}</span>
                  </div>
                  <div style="color:var(--text-2);font-size:12.5px;margin-top:4px;line-height:1.5;">
                    {esc(reason)}</div>
                </div>
                <div class="status-badge badge-critical" style="flex:0 0 auto;">
                  {esc(f"{float(row['qa_score'] or 0):.1f}")}/10</div>
              </div>
            </div>
        """, unsafe_allow_html=True)
        with action:
            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
            if st.button("Review →", key=f"crit_open_{row['call_id']}",
                         use_container_width=True):
                navigate_to("CallReport", call_id=row["call_id"])
                st.rerun()
