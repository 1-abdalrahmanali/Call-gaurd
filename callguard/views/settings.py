"""Settings: detection rules and the scoring reference."""

import streamlit as st

from callguard.components import toast
from callguard.database import load_banned_rules, save_banned_rules


def view_settings():
    st.title("Settings")
    st.caption("Configure what the auditor flags.")

    rules_tab, about_tab = st.tabs(["Detection rules", "About"])

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
