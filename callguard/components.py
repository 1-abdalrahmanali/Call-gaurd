"""Reusable Streamlit building blocks: rows, pagers, distributions, charts."""

import math

import pandas as pd
import streamlit as st

from callguard.config import PAGE_SIZE
from callguard.formatting import esc
from callguard.theme import (
    C_CRIT,
    C_GOOD,
    C_GRID,
    C_INFO,
    C_MUTED_INK,
    C_SERIES_1,
    C_SURFACE,
    C_WARN,
)


try:  # Altair ships with Streamlit, but never let a chart take down the app.
    import altair as alt

    HAS_ALTAIR = True
except Exception:  # pragma: no cover
    HAS_ALTAIR = False
@st.cache_data(show_spinner=False)
def _supports_valign() -> bool:
    """st.columns(vertical_alignment=...) landed in Streamlit 1.36."""
    try:
        import inspect
        return "vertical_alignment" in inspect.signature(st.columns).parameters
    except Exception:
        return False


def row_cols(widths):
    """Vertically centred columns where the installed Streamlit supports it."""
    if _supports_valign():
        return st.columns(widths, vertical_alignment="center")
    return st.columns(widths)


def row_container():
    """st.container(border=True) with a graceful fallback on older Streamlit."""
    try:
        return st.container(border=True)
    except TypeError:  # pragma: no cover
        return st.container()


def toast(message):
    try:
        st.toast(message)
    except Exception:  # pragma: no cover
        st.success(message)
def render_status_distribution(counts: dict, total: int):
    """Horizontal stacked bar + legend.

    Status colours are reserved and always ship with a label, never colour
    alone; segments carry a 2px surface gap so adjacent fills stay readable.
    """
    if not total:
        return
    order = [("Passed", C_GOOD), ("Warning", C_WARN), ("Critical", C_CRIT), ("In Review", C_INFO)]
    segments, legend = [], []
    for label, color in order:
        count = int(counts.get(label, 0) or 0)
        if count <= 0:
            continue
        pct = count / total * 100
        segments.append(f"<span style='width:{pct:.4f}%;background:{color};'></span>")
        legend.append(
            f"<div class='item'><span class='swatch' style='background:{color}'></span>"
            f"{esc(label)} <b>{count}</b> "
            f"<span style='color:var(--text-3)'>({pct:.0f}%)</span></div>"
        )
    st.markdown(
        f"<div class='cg-statusbar'>{''.join(segments)}</div>"
        f"<div class='cg-legend'>{''.join(legend)}</div>",
        unsafe_allow_html=True,
    )


def render_column_headers(widths, labels):
    with st.container():
        st.markdown("<div class='cg-rowhead'>", unsafe_allow_html=True)
        header_cols = st.columns(widths)
        for col, label in zip(header_cols, labels):
            if label:
                col.markdown(f"<span class='col-header'>{esc(label)}</span>",
                             unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


def render_pager(total_rows, key_prefix):
    total_pages = max(1, math.ceil(total_rows / PAGE_SIZE))
    page = min(st.session_state.page, total_pages - 1)
    st.session_state.page = page

    left, mid, right = st.columns([1, 3, 1])
    if left.button("← Previous", disabled=page == 0, use_container_width=True,
                   key=f"{key_prefix}_prev"):
        st.session_state.page = page - 1
        st.rerun()
    first = page * PAGE_SIZE + 1
    last = min((page + 1) * PAGE_SIZE, total_rows)
    mid.markdown(
        f"<div style='text-align:center;color:var(--text-3);font-size:12px;padding-top:7px;'>"
        f"{first}–{last} of {total_rows} · page {page + 1} of {total_pages}</div>",
        unsafe_allow_html=True,
    )
    if right.button("Next →", disabled=page >= total_pages - 1, use_container_width=True,
                    key=f"{key_prefix}_next"):
        st.session_state.page = page + 1
        st.rerun()


def score_trend_chart(df: pd.DataFrame, team_avg=None):
    """Single-series score trend: blue 2px line, points coloured by status
    (status palette + legend, never colour alone), dashed team-average rule
    with a direct label, crosshair tooltip. One y-axis, 0–10, always."""
    if df.empty:
        return
    if not HAS_ALTAIR:
        st.line_chart(df.set_index("when")["qa_score"], height=240)
        return

    data = df.copy()
    data["when"] = pd.to_datetime(data["when"], errors="coerce")
    data = data.dropna(subset=["when"])
    if data.empty:
        return
    data["Score"] = data["qa_score"].astype(float).round(1)

    base = alt.Chart(data)
    x = alt.X("when:T", title=None,
              axis=alt.Axis(grid=False, domainColor=C_GRID, tickColor=C_GRID,
                            labelColor=C_MUTED_INK, labelFontSize=11, format="%d %b"))
    y = alt.Y("Score:Q", title=None, scale=alt.Scale(domain=[0, 10], nice=False),
              axis=alt.Axis(grid=True, gridColor=C_GRID, gridDash=[2, 3], domain=False,
                            tickCount=5, labelColor=C_MUTED_INK, labelFontSize=11))

    line = base.mark_line(color=C_SERIES_1, strokeWidth=2,
                          interpolate="monotone").encode(x=x, y=y)
    points = base.mark_point(filled=True, size=90, strokeWidth=1.5,
                             stroke=C_SURFACE).encode(
        x=x, y=y,
        color=alt.Color(
            "status:N", title="Status",
            scale=alt.Scale(domain=["Passed", "Warning", "Critical", "In Review"],
                            range=[C_GOOD, C_WARN, C_CRIT, C_INFO]),
            legend=alt.Legend(orient="top", direction="horizontal", title=None,
                              labelColor=C_MUTED_INK, symbolType="circle",
                              labelFontSize=11, offset=6),
        ),
        tooltip=[alt.Tooltip("when:T", title="Date", format="%d %b %Y %H:%M"),
                 alt.Tooltip("Score:Q", title="QA score"),
                 alt.Tooltip("status:N", title="Status"),
                 alt.Tooltip("call_id:N", title="Call")],
    )

    layers = [line, points]
    if team_avg is not None and not math.isnan(float(team_avg)):
        rule_df = pd.DataFrame({"y": [round(float(team_avg), 2)]})
        rule = alt.Chart(rule_df).mark_rule(
            color=C_MUTED_INK, strokeDash=[4, 4], strokeWidth=1).encode(y="y:Q")
        label = alt.Chart(rule_df).mark_text(
            align="left", dx=6, dy=-7, color=C_MUTED_INK, fontSize=10.5,
            text=f"Team avg {float(team_avg):.1f}").encode(y="y:Q")
        layers += [rule, label]

    chart = (alt.layer(*layers)
             .properties(height=250)
             .configure_view(strokeWidth=0, fill=C_SURFACE)
             .configure(background=C_SURFACE, font="Inter"))
    st.altair_chart(chart, use_container_width=True)
