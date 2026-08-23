"""
CallGuard — QA Operations Console
=================================

Entry point. Everything it does is in the order it has to happen:

    1. st.set_page_config()  — must be the first Streamlit call in the process
    2. inject the stylesheet
    3. open/migrate the database
    4. block on the password gate
    5. seed routing state from the URL, draw the sidebar
    6. dispatch to the current view

The application itself lives in the `callguard` package:

    callguard/config.py            secrets, provider endpoints, tuning
    callguard/theme.py             design tokens + stylesheet
    callguard/formatting.py        escaping, badges, chips, value formatting
    callguard/components.py        rows, pagers, distributions, the trend chart
    callguard/database.py          schema, migrations, cached reads, writes
    callguard/providers.py         API clients and model discovery
    callguard/exports.py           the CSV download
    callguard/auth.py              password gate
    callguard/navigation.py        routing + sidebar
    callguard/audit/               the audit pipeline (see its own README note)
    callguard/views/               one module per screen

Run with:  streamlit run app_web.py
"""

import streamlit as st

from callguard.config import APP_NAME

st.set_page_config(
    page_title=f"{APP_NAME} · QA Operations",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Imported after set_page_config: importing a view is harmless, but keeping the
# page config first is a hard Streamlit requirement and this ordering makes
# that impossible to break by accident.
from callguard.auth import require_login                      # noqa: E402
from callguard.database import init_db                        # noqa: E402
from callguard.navigation import (                            # noqa: E402
    init_state,
    render_sidebar,
)
from callguard.theme import inject_css                        # noqa: E402
from callguard.views.agent_details import view_agent_details  # noqa: E402
from callguard.views.agents import view_agents                # noqa: E402
from callguard.views.auditor import view_auditor              # noqa: E402
from callguard.views.call_report import view_call_report      # noqa: E402
from callguard.views.dashboard import view_dashboard          # noqa: E402
from callguard.views.settings import view_settings            # noqa: E402

inject_css()
init_db()
require_login()

init_state()
render_sidebar()

VIEW_ROUTER = {
    "Dashboard": view_dashboard,
    "Agents": view_agents,
    "AgentDetails": view_agent_details,
    "CallReport": view_call_report,
    "Auditor": view_auditor,
    "Settings": view_settings,
}

VIEW_ROUTER.get(st.session_state.current_view, view_dashboard)()
