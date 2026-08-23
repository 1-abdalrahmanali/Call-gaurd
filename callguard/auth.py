"""Password gate."""

import hmac
import time

import streamlit as st

from callguard.config import APP_NAME, APP_PASSWORD, APP_TAGLINE, BUILT_BY


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

        # FIXED: st.secrets["APP_PASSWORD"] raised a raw KeyError and dumped a
        # traceback to the browser whenever the secret was not configured.
        if not APP_PASSWORD:
            st.error(
                "No password is configured. Add `APP_PASSWORD` to your Streamlit "
                "secrets (or environment) and reload."
            )
            return

        locked_until = st.session_state.get("lockout_until", 0)
        remaining = int(locked_until - time.time())
        if remaining > 0:
            st.error(f"Too many failed attempts. Try again in {remaining}s.")
            return

        with st.form("login_form"):
            password = st.text_input("Password", type="password",
                                     placeholder="Enter your password")
            submitted = st.form_submit_button("Sign in", type="primary",
                                              use_container_width=True)

        # Handled outside the form block so st.rerun() isn't called mid-form.
        if submitted:
            if hmac.compare_digest(password or "", APP_PASSWORD):
                st.session_state.authenticated = True
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
                st.error(f"Incorrect password. {left} attempt{'s' if left != 1 else ''} left.")

        st.caption(f"Built by {BUILT_BY} · All rights reserved")


def require_login():
    """Render the login screen and halt unless this session is authenticated."""
    st.session_state.setdefault("authenticated", False)
    if not st.session_state.authenticated:
        view_login()
        st.stop()
