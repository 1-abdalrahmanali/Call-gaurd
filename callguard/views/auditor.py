"""Run audit: upload, preflight, batch execution and results."""


import json
import os
import uuid
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import streamlit as st

from callguard.audit.pipeline import process_one_call
from callguard.components import render_column_headers, row_cols, row_container
from callguard.config import (
    ALLOWED_AUDIO,
    AUDIT_API_KEY,
    AUDIT_WORKERS,
    CHUNK_SIZE,
    MAX_UPLOAD_MB,
    TRANSCRIBE_API_KEY,
)
from callguard.database import execute_batch, load_banned_rules, upsert_agent
from callguard.formatting import (
    esc,
    fmt_duration,
    score_cell,
    short_url,
    status_badge,
)
from callguard.navigation import navigate_to
from callguard.providers import (
    audit_client,
    missing_models,
    similar_models,
    transcribe_client,
)
from callguard.accounts import current_username


def view_auditor():
    st.title("Call Analyzer")
    st.caption("Upload one or more recordings. Each file is transcribed, audited and scored.")

    with st.form("audit_form"):
        c1, c2, c3 = st.columns(3)
        agent_name = c2.text_input("Agent name", placeholder="Lowercase only")
        agent_id = c1.text_input("Agent ID", placeholder="numbers only")
        agent_team = c3.text_input("account", placeholder="the name of the account")

        uploaded_files = st.file_uploader(
            "Audio recordings", type=ALLOWED_AUDIO, accept_multiple_files=True)
        st.caption("**Important:** Please keep this tab open until all calls have "
                   "been fully analyzed.")

        submitted = st.form_submit_button("Run", type="primary")

    if submitted:
        run_audit_batch(agent_id, agent_name, agent_team, uploaded_files)

    if st.session_state.get("last_audited_calls"):
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        st.markdown("#### Just audited")
        widths = [3, 1.4, 1.4, 1.4]
        render_column_headers(widths, ["File", "Score", "Status", ""])
        for call_uid, fname, score, call_status in st.session_state.last_audited_calls:
            with row_container():
                st.markdown("<span class='cg-row'></span>", unsafe_allow_html=True)
                cols = row_cols(widths)
                cols[0].markdown(f"<div class='cg-cell'>{esc(fname)}</div>",
                                 unsafe_allow_html=True)
                cols[1].markdown(score_cell(score), unsafe_allow_html=True)
                cols[2].markdown(status_badge(call_status), unsafe_allow_html=True)
                if cols[3].button("Report →", key=f"view_new_{call_uid}",
                                  use_container_width=True):
                    navigate_to("CallReport", call_id=call_uid)
                    st.session_state.last_audited_calls = None
                    st.rerun()
        if st.button("Clear list", key="clear_recent"):
            st.session_state.last_audited_calls = None
            st.rerun()


def run_audit_batch(agent_id, agent_name, agent_team, uploaded_files):
    agent_id = (agent_id or "").strip()
    agent_name = (agent_name or "").strip()
    agent_team = (agent_team or "").strip()

    if not agent_id or not agent_name:
        st.error("Enter both an agent ID and an agent name.")
        return
    if not uploaded_files:
        st.error("Upload at least one audio file.")
        return
    if not TRANSCRIBE_API_KEY:
        st.error("No transcription key. Add `TRANSCRIBE_API_KEY` (or `GROQ_API_KEY`) "
                 "to your secrets and reload.")
        return
    if not AUDIT_API_KEY:
        st.error("No audit key. Add `OPENROUTER_API_KEY` (or `AUDIT_API_KEY`) "
                 "to your secrets and reload.")
        return

    # Reject oversized files up front rather than paying for a failed request.
    accepted, rejected = [], []
    for uploaded in uploaded_files:
        size_mb = uploaded.size / (1024 * 1024)
        (rejected if size_mb > MAX_UPLOAD_MB else accepted).append((uploaded, size_mb))

    for uploaded, size_mb in rejected:
        st.markdown(
            f"<div class='audit-row-skip'><b>{esc(uploaded.name)}</b> — skipped, "
            f"{size_mb:.1f} MB exceeds the {MAX_UPLOAD_MB:.0f} MB limit.</div>",
            unsafe_allow_html=True)
    if not accepted:
        st.error("Every file was rejected. Compress the audio and try again.")
        return

    # Preflight: a wrong or retired model ID would otherwise fail once per
    # file with a raw 404 — and for the audit model, only AFTER paying for the
    # transcription. Check both providers before spending anything.
    for row in missing_models():
        st.error(
            f"{row['label']} model `{row['model']}` is not available at "
            f"`{short_url(row['base_url'])}`. Set `{row['prefix']}_MODEL` in your secrets "
            "to one of these and reload."
        )
        suggestions = similar_models(row["models"], row["model"])
        st.code("\n".join(suggestions) or "no similar model IDs found",
                language="text")
    if missing_models():
        return

    # Read once, before any worker starts: every call in this batch is
    # attributed to whoever is signed in right now.
    uploader = current_username()

    clients = (transcribe_client(), audit_client())
    banned_rules = load_banned_rules()
    upsert_agent(agent_id, agent_name, agent_team)

    files = [uploaded for uploaded, _ in accepted]
    total_files = len(files)
    progress_bar = st.progress(0.0, text=f"0 of {total_files} processed")
    log = st.container()

    committed_calls, committed_count, done_count, credit_failures = [], 0, 0, 0

    for chunk_start in range(0, total_files, CHUNK_SIZE):
        chunk = files[chunk_start:chunk_start + CHUNK_SIZE]
        call_rows, report_rows, pending, chunk_paths = [], [], [], []

        with ThreadPoolExecutor(max_workers=AUDIT_WORKERS) as pool:
            futures = {}
            for uploaded in chunk:
                # uuid4, not timestamp+index: two batches submitted in the same
                # second both started at index 0 and collided on the primary key.
                call_uid = f"CALL_{uuid.uuid4().hex[:12].upper()}"
                # .getbuffer() must be read on the main thread — Streamlit's
                # UploadedFile is not thread-safe.
                payload = uploaded.getbuffer().tobytes()
                futures[pool.submit(process_one_call, clients, banned_rules,
                                    uploaded.name, payload, call_uid)] = uploaded.name

            for future in as_completed(futures):
                outcome = future.result()
                done_count += 1
                progress_bar.progress(done_count / total_files,
                                      text=f"{done_count} of {total_files} processed")

                if not outcome["ok"]:
                    if outcome.get("budget_error"):
                        credit_failures += 1
                    log.markdown(
                        f"<div class='audit-row-err'><b>{esc(outcome['filename'])}</b> — "
                        f"{esc(outcome['error'])}</div>", unsafe_allow_html=True)
                    continue

                chunk_paths.append(outcome["audio_path"])
                call_rows.append((
                    outcome["call_uid"], agent_id, datetime.now().isoformat(sep=" ", timespec="seconds"),
                    fmt_duration(outcome["duration_seconds"]),
                    outcome["audio_path"], outcome["transcript_text"],
                    outcome["final_score"], outcome["grammar_score"],
                    outcome["call_status"], outcome["profanity_flag"],
                    outcome["duration_seconds"], uploader,
                ))
                report_rows.append((
                    outcome["call_uid"], outcome["language"], outcome["audit_summary"],
                    json.dumps(outcome["all_violations"], ensure_ascii=False),
                    json.dumps(outcome["grammar_errs"], ensure_ascii=False),
                    "", outcome["recommended_coaching"],
                    outcome["sentiment_start"], outcome["sentiment_end"],
                ))
                pending.append((outcome["call_uid"], outcome["filename"],
                                outcome["final_score"], outcome["call_status"]))
                notes = []
                if outcome.get("truncated"):
                    notes.append("transcript trimmed for the audit")
                if outcome.get("json_retries"):
                    plural = "s" if outcome["json_retries"] > 1 else ""
                    notes.append(f"needed {outcome['json_retries']} "
                                 f"re-ask{plural} for valid JSON")
                note = (" — " + "; ".join(notes)) if notes else ""
                log.markdown(
                    f"<div class='audit-row-ok'><b>{esc(outcome['filename'])}</b> — "
                    f"{outcome['final_score']}/10 {status_badge(outcome['call_status'])}"
                    f"<span style='color:var(--text-3)'>{esc(note)}</span></div>",
                    unsafe_allow_html=True)

        # One transaction per chunk: calls and their reports land together or
        # not at all. Nothing is counted as a success until it is committed.
        if not call_rows:
            continue
        try:
            execute_batch([
                ("""INSERT INTO calls (id, agent_id, date, duration, audio_file, transcription,
                                       qa_score, grammar_score, status, profanity_detected,
                                       duration_seconds, uploaded_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", call_rows),
                ("""INSERT INTO reports (call_id, language, summary, violations, grammar_feedback,
                                         manager_notes, recommended_coaching,
                                         sentiment_start, sentiment_end)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", report_rows),
            ])
        except Exception as exc:
            # The originals counted these as successes and offered a
            # "View report" link to a row that was never written.
            log.markdown(
                f"<div class='audit-row-err'><b>{len(call_rows)} file(s)</b> processed but "
                f"could not be saved — {esc(exc)}</div>", unsafe_allow_html=True)
            for path in chunk_paths:  # don't leave orphaned audio behind
                try:
                    os.remove(path)
                except OSError:
                    pass
            continue

        committed_calls.extend(pending)
        committed_count += len(call_rows)

    progress_bar.empty()
    failed = total_files - committed_count
    if credit_failures and credit_failures == failed and failed:
        st.warning(
            "Every failure was an OpenRouter budget error. OpenRouter limits how "
            "much spend can be **in flight at once**, not just your balance, so "
            f"{AUDIT_WORKERS} parallel audits of a large model can trip it even "
            "with credit left. Either add credits at "
            "openrouter.ai/settings/credits, or set `CALLGUARD_WORKERS = \"1\"` "
            "in your secrets and re-run.")
    if committed_count:
        st.success(f"Saved {committed_count} of {total_files} call(s) for {agent_name}."
                   + (f" {failed} did not complete." if failed else ""))
        st.session_state.last_audited_calls = committed_calls
    else:
        st.error("No calls were saved. Check the errors above and try again.")
