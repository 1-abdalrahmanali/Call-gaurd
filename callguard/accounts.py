"""The five user accounts.

Accounts are defined in Streamlit secrets, never in this file, so credentials
stay out of the repository:

    [users.alice]
    password = "..."
    name     = "Alice Hassan"
    role     = "QA Lead"

Anything under `[users]` becomes an account, so five is a convention rather
than a hard limit — add or remove a block and the login screen follows.

Passwords are compared with hmac.compare_digest and are never written to the
database, the session, or a log line. What lands in an audit record is the
username only.
"""

import hmac

import streamlit as st

from callguard.config import APP_PASSWORD


# Shown when a legacy single-password deployment has not defined [users] yet,
# so an existing install keeps working the moment this version is pushed.
LEGACY_USERNAME = "admin"
LEGACY_NAME = "Administrator"
LEGACY_ROLE = "Legacy login"


def _clean(value, fallback=""):
    text = str(value or "").strip()
    return text or fallback


def load_accounts():
    """{username: {"name": str, "role": str, "password": str}}.

    Empty when nothing is configured, which the login screen reports rather
    than silently letting anyone in.
    """
    accounts = {}
    try:
        raw = st.secrets.get("users", None)
    except Exception:
        raw = None

    if raw:
        for username, entry in dict(raw).items():
            username = _clean(username)
            if not username:
                continue
            if isinstance(entry, str):          # users.alice = "password"
                password, name, role = entry, username, ""
            else:                               # [users.alice] table
                entry = dict(entry)
                password = entry.get("password", "")
                name = _clean(entry.get("name"), username)
                role = _clean(entry.get("role"))
            if _clean(password):
                accounts[username] = {
                    "name": _clean(name, username),
                    "role": role,
                    "password": str(password),
                }

    # Migration path: an install that still has only APP_PASSWORD keeps working
    # as a single administrator account until [users] is added.
    if not accounts and APP_PASSWORD:
        accounts[LEGACY_USERNAME] = {
            "name": LEGACY_NAME,
            "role": LEGACY_ROLE,
            "password": APP_PASSWORD,
        }
    return accounts


def authenticate(username, password):
    """The account dict on success, else None. Constant-time comparison.

    A wrong username still costs a comparison, so response time does not
    reveal which usernames exist.
    """
    accounts = load_accounts()
    username = _clean(username)
    supplied = str(password or "")

    record = accounts.get(username)
    expected = record["password"] if record else "\0unmatchable"
    ok = hmac.compare_digest(supplied, expected)
    if record and ok:
        return {"username": username, "name": record["name"], "role": record["role"]}
    return None


def display_name(username):
    """Label for a stored `uploaded_by` value.

    Records keep the username, so renaming someone in secrets updates every
    past audit. An account that has since been removed falls back to the raw
    username rather than showing a blank cell.
    """
    if not username:
        return "—"
    record = load_accounts().get(str(username))
    return record["name"] if record else str(username)


def current_user():
    """The signed-in account, or None."""
    return st.session_state.get("user")


def current_username():
    """Username to stamp onto a new record. None when not signed in."""
    user = current_user()
    return user.get("username") if user else None
