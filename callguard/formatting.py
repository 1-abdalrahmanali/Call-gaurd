"""Pure presentation helpers: escaping, badges, chips and value formatting.

Nothing here touches the database, the network or st.session_state, which is
what makes it all directly unit-testable.
"""

import html
import math
import re

from callguard.config import PASS_THRESHOLD, WARN_THRESHOLD
from callguard.theme import C_CRIT, C_GOOD, C_INFO, C_MUTED_INK, C_WARN


def esc(value) -> str:
    """Escape anything before it goes into an unsafe_allow_html block.

    The original code interpolated agent names, AI summaries and filenames
    straight into markup, so a stray '<' broke the layout and a crafted name
    could inject script.
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


STATUS_META = {
    "Passed": ("badge-passed", C_GOOD),
    "Warning": ("badge-warning", C_WARN),
    "Critical": ("badge-critical", C_CRIT),
    "In Review": ("badge-review", C_INFO),
}


def status_badge(status) -> str:
    cls, _ = STATUS_META.get(status, ("badge-neutral", C_MUTED_INK))
    return f"<span class='status-badge {cls}'><span class='dot'></span>{esc(status or 'Unknown')}</span>"


def status_color(status) -> str:
    return STATUS_META.get(status, ("", C_MUTED_INK))[1]


def sentiment_badge(sentiment) -> str:
    """FIXED: the original wrote `cls, emoji = styles.get(s, ("badge-warning"))`.

    Those parenthesised strings were not tuples, so every call raised
    ValueError and the Call Report page died on any call that had sentiment.
    """
    styles = {
        "Positive": "badge-passed",
        "Neutral": "badge-neutral",
        "Negative": "badge-critical",
    }
    cls = styles.get(sentiment, "badge-neutral")
    return (f"<span class='status-badge {cls}'><span class='dot'></span>"
            f"{esc(sentiment or 'Unknown')}</span>")


def id_chip(value) -> str:
    return f"<span class='id-chip'>{esc(value)}</span>"


def score_cell(score) -> str:
    if score is None or (isinstance(score, float) and math.isnan(score)):
        return "<span class='cg-score'>—</span>"
    score = float(score)
    color = C_GOOD if score >= PASS_THRESHOLD else (C_WARN if score >= WARN_THRESHOLD else C_CRIT)
    pct = max(0.0, min(100.0, score * 10.0))
    return (
        f"<div class='cg-score'>{score:.1f}<span class='den'>/10</span></div>"
        f"<div class='cg-meter' style='margin-top:5px;'>"
        f"<i style='width:{pct:.0f}%;background:{color};'></i></div>"
    )


def kpi(label, value, sub="", accent="info") -> str:
    return (
        f"<div class='cg-kpi accent-{accent}'>"
        f"<div class='k-label'>{esc(label)}</div>"
        f"<div class='k-value'>{esc(value)}</div>"
        f"<div class='k-sub'>{esc(sub)}</div></div>"
    )
def initials(name) -> str:
    """Up to two initials for the sidebar avatar."""
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def short_url(url) -> str:
    """Endpoint shown as an identifier, not an auto-linked hyperlink."""
    return re.sub(r"^https?://", "", str(url or "")).rstrip("/")


def empty_state(title, body) -> str:
    return (
        f"<div class='cg-empty'>"
        f"<div class='e-title'>{esc(title)}</div>"
        f"<div class='e-body'>{esc(body)}</div></div>"
    )
def fmt_duration(seconds) -> str:
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if seconds <= 0 or math.isnan(seconds):
        return "—"
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def fmt_date(value, length=16) -> str:
    return str(value)[:length] if value else "—"


def as_list(value):
    """Coerce whatever the model returned into a clean list of strings.

    The original code did `banned + offensive + general`. If the model
    returned a string or null for any of them, that raised TypeError and the
    whole file failed mid-batch.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, (list, tuple, set)):
        return [str(value)]
    out = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)
