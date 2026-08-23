"""Call report: score, sentiment, violations, notes and score override."""

import json
import math
import os

import streamlit as st

from callguard.components import toast
from callguard.config import PASS_THRESHOLD, WARN_THRESHOLD
from callguard.database import execute_query, run_query
from callguard.formatting import (
    as_list,
    esc,
    fmt_date,
    fmt_duration,
    id_chip,
    kpi,
    sentiment_badge,
    status_badge,
)
from callguard.navigation import navigate_to
from callguard.theme import C_CRIT, C_GOOD, C_MUTED_INK, C_WARN


def view_call_report():
    call_id = st.session_state.selected_call
    back_target = st.session_state.get("previous_view") or "Dashboard"

    if not call_id:
        st.warning("No call selected.")
        if st.button("← Back"):
            navigate_to(back_target)
            st.rerun()
        return

    # LEFT JOIN, not INNER JOIN: a call whose report row failed to write used
    # to become permanently unreachable instead of showing a partial report.
    df = run_query("""
        SELECT c.*, a.name AS agent_name, a.id AS employee_id, a.team,
               r.language, r.summary, r.violations, r.grammar_feedback, r.manager_notes,
               r.recommended_coaching, r.sentiment_start, r.sentiment_end
        FROM calls c
        JOIN agents a ON c.agent_id = a.id
        LEFT JOIN reports r ON c.id = r.call_id
        WHERE c.id = ?
    """, (call_id,))

    if df.empty:
        st.error("This report could not be found. It may have been deleted.")
        if st.button("← Back"):
            navigate_to(back_target)
            st.rerun()
        return

    call = df.iloc[0]

    if st.button("← Back", key="report_back"):
        navigate_to(back_target)
        st.rerun()

    st.title("Call report")
    st.markdown(id_chip(call_id), unsafe_allow_html=True)
    st.caption(
        f"{call['agent_name']} ({call['employee_id']})"
        f"{'  ·  ' + call['team'] if call['team'] else ''}"
        f"  ·  Audited {fmt_date(call['date'])}"
        f"{'  ·  ' + (call['language'] or '') if call['language'] else ''}"
    )

    raw_score = call["qa_score"]
    score = float(raw_score) if raw_score is not None and not (
        isinstance(raw_score, float) and math.isnan(raw_score)) else None

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi(
        "QA score", f"{score:.1f}" if score is not None else "—",
        "manually adjusted" if call["manually_adjusted"] else f"grammar {float(call['grammar_score'] or 0):.1f}",
        "good" if (score or 0) >= PASS_THRESHOLD else ("warn" if (score or 0) >= WARN_THRESHOLD else "crit"),
    ), unsafe_allow_html=True)
    with k2:
        st.markdown(
            "<div class='cg-kpi'><div class='k-label'>Status</div>"
            f"<div style='margin-top:12px'>{status_badge(call['status'])}</div>"
            f"<div class='k-sub'>{esc(fmt_duration(call['duration_seconds']))} of audio</div></div>",
            unsafe_allow_html=True)
    k3.markdown(kpi(
        "Profanity", "Flagged" if call["profanity_detected"] else "Clean",
        "review the violations below" if call["profanity_detected"] else "no flagged language",
        "crit" if call["profanity_detected"] else "good",
    ), unsafe_allow_html=True)
    with k4:
        st.markdown("<div style='height:22px'></div>", unsafe_allow_html=True)
        if call["status"] == "In Review":
            st.markdown(
                "<div style='text-align:center;color:var(--info);font-size:12.5px;'>"
                "Already flagged for review</div>", unsafe_allow_html=True)
        elif st.button("Flag for manual review", use_container_width=True,
                       key=f"flag_{call_id}"):
            execute_query("UPDATE calls SET status = ? WHERE id = ?", ("In Review", call_id))
            toast("Flagged for manual review.")
            st.rerun()

    st.divider()

    # --- Sentiment journey -------------------------------------------------
    start_sentiment, end_sentiment = call["sentiment_start"], call["sentiment_end"]
    if start_sentiment or end_sentiment:
        st.markdown("##### Customer sentiment")
        s1, s2, s3, s4 = st.columns([1.1, 0.35, 1.1, 2.4])
        s1.markdown(
            f"<div style='color:var(--text-3);font-size:11px;text-transform:uppercase;"
            f"letter-spacing:.07em;font-weight:650;'>Start of call</div>"
            f"<div style='margin-top:6px'>{sentiment_badge(start_sentiment)}</div>",
            unsafe_allow_html=True)
        s2.markdown("<div style='text-align:center;font-size:18px;margin-top:26px;"
                    "color:var(--text-3);'>→</div>", unsafe_allow_html=True)
        s3.markdown(
            f"<div style='color:var(--text-3);font-size:11px;text-transform:uppercase;"
            f"letter-spacing:.07em;font-weight:650;'>End of call</div>"
            f"<div style='margin-top:6px'>{sentiment_badge(end_sentiment)}</div>",
            unsafe_allow_html=True)

        rank = {"Negative": 0, "Neutral": 1, "Positive": 2}
        note, color = None, C_MUTED_INK
        if start_sentiment in rank and end_sentiment in rank:
            delta = rank[end_sentiment] - rank[start_sentiment]
            if delta > 0:
                note, color = "Improved during the call — the agent moved the customer up.", C_GOOD
            elif delta < 0:
                note, color = "Declined during the call — worth listening to.", C_CRIT
            elif start_sentiment == "Negative":
                note, color = "Stayed negative — no de-escalation.", C_WARN
            elif start_sentiment == "Positive":
                note, color = "Held positive throughout.", C_GOOD
            else:
                note = "Stayed neutral throughout."
        if note:
            s4.markdown(
                f"<div style='margin-top:24px;font-size:12.5px;color:{color};'>{esc(note)}</div>",
                unsafe_allow_html=True)
        st.divider()

    # --- Panels ------------------------------------------------------------
    left, right = st.columns([1.35, 1])

    with left:
        with st.expander("Audio recording", expanded=True):
            audio_file = call["audio_file"]
            if audio_file and os.path.exists(str(audio_file)):
                st.audio(str(audio_file))
            else:
                st.info("Audio file archived or unavailable on this host.")

        with st.expander("Executive summary", expanded=True):
            st.write(call["summary"] or "_No summary was generated for this call._")

        with st.expander("Recommended coaching", expanded=True):
            st.write(call["recommended_coaching"] or "_No coaching notes generated._")

        with st.expander("Transcript", expanded=False):
            transcript = call["transcription"] or ""
            if transcript:
                st.text_area("Transcript", transcript, height=280,
                             label_visibility="collapsed", disabled=True,
                             key=f"tx_{call_id}")
                st.download_button(
                    "Download transcript",
                    transcript.encode("utf-8"),
                    file_name=f"{call_id}_transcript.txt", mime="text/plain",
                    key=f"tx_dl_{call_id}",
                )
            else:
                st.caption("No transcript stored.")

    with right:
        with st.expander("Violations & compliance", expanded=True):
            try:
                violations = as_list(json.loads(call["violations"] or "[]"))
            except (TypeError, ValueError):
                violations = []
            if violations:
                for violation in violations:
                    st.markdown(
                        f"<div class='audit-row-err'><span>{esc(violation)}</span></div>",
                        unsafe_allow_html=True)
            else:
                st.markdown(
                    "<div class='audit-row-ok'><span>No compliance violations detected.</span></div>",
                    unsafe_allow_html=True)

        with st.expander("Grammar analysis", expanded=True):
            try:
                grammar = json.loads(call["grammar_feedback"] or "[]")
                grammar = grammar if isinstance(grammar, list) else []
            except (TypeError, ValueError):
                grammar = []
            if grammar:
                st.caption(f"{len(grammar)} issue{'s' if len(grammar) != 1 else ''} found")
                for item in grammar:
                    if not isinstance(item, dict):
                        continue
                    st.markdown(
                        f"<div class='audit-row-skip'>"
                        f"<span><b>{esc(item.get('error'))}</b> → "
                        f"{esc(item.get('correction'))}</span></div>",
                        unsafe_allow_html=True)
                    if item.get("reason"):
                        st.caption(item["reason"])
            else:
                st.markdown(
                    "<div class='audit-row-ok'><span>No grammar issues detected.</span></div>",
                    unsafe_allow_html=True)

        with st.expander("Manager notes", expanded=True):
            with st.form(f"notes_form_{call_id}"):
                notes = st.text_area(
                    "Notes", value=call["manager_notes"] or "", height=110,
                    label_visibility="collapsed",
                    placeholder="Add manager notes for this call…")
                save_notes = st.form_submit_button("Save notes", type="primary")
            if save_notes:
                # UPSERT: a call with no report row would otherwise silently
                # discard the note (UPDATE ... WHERE call_id matched nothing).
                execute_query("""
                    INSERT INTO reports (call_id, manager_notes) VALUES (?, ?)
                    ON CONFLICT(call_id) DO UPDATE SET manager_notes = excluded.manager_notes
                """, (call_id, notes))
                toast("Notes saved.")
                st.rerun()

        with st.expander("Override score", expanded=False):
            st.caption("Manually correct the AI score. Status follows automatically.")
            with st.form(f"score_form_{call_id}"):
                new_score = st.number_input(
                    "QA score", min_value=0.0, max_value=10.0, step=0.1,
                    value=float(score) if score is not None else 0.0)
                save_score = st.form_submit_button("Save score", type="primary")
            if save_score:
                new_score = round(float(new_score), 1)
                new_status = ("Passed" if new_score >= PASS_THRESHOLD
                              else "Warning" if new_score >= WARN_THRESHOLD else "Critical")
                execute_query(
                    "UPDATE calls SET qa_score = ?, status = ?, manually_adjusted = 1 WHERE id = ?",
                    (new_score, new_status, call_id))
                toast(f"Score updated to {new_score:.1f} ({new_status}).")
                st.rerun()
