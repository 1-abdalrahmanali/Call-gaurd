"""Sign-in gate.

Authentication lives in session state, which survives navigation, audits and
reruns for as long as the browser tab stays open. A hard refresh starts a new
Streamlit session and asks for credentials again — that is the trade for
carrying no cookie dependency.
"""

import time

import streamlit as st

from callguard.accounts import authenticate, load_accounts
from callguard.config import APP_NAME, APP_TAGLINE, BUILT_BY


MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 120


def view_login():
    st.markdown("<div style='height:8vh'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        st.markdown(
            "<div class='cg-brand' style='justify-content:center;margin-bottom:14px;'>"
            "<div class='mark'>CG</div>"
            f"<div><div class='name' style='font-size:20px;'>{APP_NAME}</div>"
            f"<div class='sub'>{APP_TAGLINE}</div></div></div>",
            unsafe_allow_html=True,
        )

        # A missing configuration is reported, never guessed around — an app
        # that let people in because no accounts were defined would be worse
        # than one that refuses to start.
        if not load_accounts():
            st.error(
                "No accounts are configured. Add a `[users]` section to your "
                "Streamlit secrets and reload — see `secrets.toml.example`."
            )
            return

        locked_until = st.session_state.get("lockout_until", 0)
        remaining = int(locked_until - time.time())
        if remaining > 0:
            st.error(f"Too many failed attempts. Try again in {remaining}s.")
            return

        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Your username")
            password = st.text_input("Password", type="password",
                                     placeholder="Your password")
            submitted = st.form_submit_button("Sign in", type="primary",
                                              use_container_width=True)

        # Handled outside the form block so st.rerun() isn't called mid-form.
        if submitted:
            account = authenticate(username, password)
            if account:
                st.session_state.authenticated = True
                st.session_state.user = account
                st.session_state.login_attempts = 0
                st.rerun()
            else:
                attempts = st.session_state.get("login_attempts", 0) + 1
                st.session_state.login_attempts = attempts
                if attempts >= MAX_LOGIN_ATTEMPTS:
                    st.session_state.lockout_until = time.time() + LOCKOUT_SECONDS
                    st.session_state.login_attempts = 0
                    st.rerun()
                left = MAX_LOGIN_ATTEMPTS - attempts
                # Deliberately does not say which half was wrong.
                st.error(f"Incorrect username or password. "
                         f"{left} attempt{'s' if left != 1 else ''} left.")

        st.caption(f"Built by {BUILT_BY} · All rights reserved")


def require_login():
    """Render the sign-in screen and halt unless this session is signed in."""
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("user", None)
    if not st.session_state.authenticated or not st.session_state.user:
        view_login()
        st.stop()


def sign_out():
    """Drop the identity and every piece of per-session view state."""
    for key in ("authenticated", "user", "current_view", "selected_agent",
                "selected_call", "previous_view", "last_audited_calls", "page"):
        st.session_state.pop(key, None)
