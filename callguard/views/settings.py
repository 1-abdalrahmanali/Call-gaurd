"""Settings: detection rules, storage and provider health."""


import os

import streamlit as st

from callguard.audit.pipeline import audio_store_stats
from callguard.components import toast
from callguard.config import (
    APP_NAME,
    APP_TAGLINE,
    AUDIO_DIR,
    AUDIT_API_KEY,
    AUDIT_BASE_URL,
    AUDIT_MODEL,
    AUDIT_WORKERS,
    BUILT_BY,
    DATA_DIR,
    DB_FILE,
    TRANSCRIBE_API_KEY,
    TRANSCRIBE_BASE_URL,
    TRANSCRIBE_MODEL,
)
from callguard.database import (
    load_banned_rules,
    run_query,
    save_banned_rules,
    scalar,
)
from callguard.formatting import esc, kpi, short_url
from callguard.providers import _list_models, provider_status, similar_models


def view_settings():
    st.title("Settings")
    st.caption("Configure what the auditor flags.")

    rules_tab, storage_tab, about_tab = st.tabs(["Detection rules", "Storage", "About"])

    with rules_tab:
        rules = load_banned_rules()
        with st.form("rules_form"):
            st.markdown("##### Banned phrases")
            st.caption("Exact phrases agents should never say. One per line.")
            b1, b2 = st.columns(2)
            banned_en = b1.text_area("English", value="\n".join(rules["english_banned"]), height=150)
            banned_es = b2.text_area("Spanish", value="\n".join(rules["spanish_banned"]), height=150)

            st.markdown("##### Offensive words")
            st.caption("Individual words always flagged as profanity. One per line.")
            o1, o2 = st.columns(2)
            off_en = o1.text_area("English ", value="\n".join(rules["english_offensive"]), height=130)
            off_es = o2.text_area("Spanish ", value="\n".join(rules["spanish_offensive"]), height=130)

            saved = st.form_submit_button("Save rules", type="primary")

        if saved:
            def clean(text):
                seen, out = set(), []
                for line in text.splitlines():
                    line = line.strip()
                    if line and line.lower() not in seen:
                        seen.add(line.lower())
                        out.append(line)
                return out

            try:
                save_banned_rules({
                    "english_banned": clean(banned_en),
                    "spanish_banned": clean(banned_es),
                    "english_offensive": clean(off_en),
                    "spanish_offensive": clean(off_es),
                })
                toast("Rules saved. They apply to the next audit you run.")
            except OSError as exc:
                st.error(f"Could not save the rules file: {exc}")

    # with storage_tab:
    #     file_count, size_mb = audio_store_stats()
    #     db_mb = os.path.getsize(DB_FILE) / (1024 * 1024) if os.path.exists(DB_FILE) else 0.0
    #     calls = int(scalar("SELECT COUNT(*) FROM calls"))
    #     agents = int(scalar("SELECT COUNT(*) FROM agents"))
    #     orphans = int(scalar(
    #         "SELECT COUNT(*) FROM calls c LEFT JOIN reports r ON c.id = r.call_id "
    #         "WHERE r.call_id IS NULL"))

    #     s1, s2, s3, s4 = st.columns(4)
    #     s1.markdown(kpi("Audio files", f"{file_count:,}", f"{size_mb:.1f} MB on disk", "info"),
    #                 unsafe_allow_html=True)
    #     s2.markdown(kpi("Database", f"{db_mb:.1f} MB", f"{calls:,} calls · {agents:,} agents", "info"),
    #                 unsafe_allow_html=True)
    #     s3.markdown(kpi("Calls without a report", f"{orphans:,}",
    #                     "should always be zero", "crit" if orphans else "good"),
    #                 unsafe_allow_html=True)
    #     s4.markdown(kpi("Storage path", os.path.abspath(DATA_DIR).split(os.sep)[-1] or "/",
    #                     "set CALLGUARD_DATA_DIR to change", "info"), unsafe_allow_html=True)

    #     st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    #     st.warning(
    #         "On Streamlit Community Cloud the container filesystem is wiped on every "
    #         "restart or redeploy — the database and stored audio go with it. Point "
    #         "`CALLGUARD_DATA_DIR` at a mounted volume, or move to Postgres/S3, before "
    #         "you rely on this for records retention.")

    #     st.markdown("##### Cleanup")
    #     st.caption("Delete audio files in the store that no call row references any more.")
    #     if st.button("Find and remove orphaned audio"):
    #         referenced = set(run_query(
    #             "SELECT audio_file FROM calls WHERE audio_file IS NOT NULL"
    #         )["audio_file"].dropna().map(os.path.abspath))
    #         removed = 0
    #         for name in os.listdir(AUDIO_DIR):
    #             path = os.path.abspath(os.path.join(AUDIO_DIR, name))
    #             if os.path.isfile(path) and path not in referenced:
    #                 try:
    #                     os.remove(path)
    #                     removed += 1
    #                 except OSError:
    #                     pass
    #         toast(f"Removed {removed} orphaned file(s).")
    #         st.rerun()

    with about_tab:
        st.markdown("##### Scoring model")
        st.markdown("""
| Finding | Penalty |
|---|---|
| Each grammar error | −0.15 (capped at −2.0) |
| Each offensive / profane word | −2.0 |
| Each banned phrase | −1.0 |
| Missing formal greeting | −1.0 |
| Arabic detected | informational only |

A call is **Passed** at 8.0 and above, **Warning** from 5.0, **Critical** below 5.0.
""")
