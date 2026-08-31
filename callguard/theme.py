"""Design tokens and the stylesheet.

Colour constants are shared with the chart layer so the UI and the plots
cannot drift apart. Chart colours are validated against the dark surface
#0F131A: series blue #3987E5 and orange #D95926 clear every CVD and contrast
check, and the four status colours clear 3:1.
"""

import streamlit as st


C_GOOD = "#3DD68C"
C_WARN = "#F5B544"
C_CRIT = "#F2555A"
C_INFO = "#7C93FF"
C_SERIES_1 = "#3987E5"
C_SERIES_2 = "#D95926"
C_SURFACE = "#111620"
C_MUTED_INK = "#8A94A6"
C_GRID = "#1E2532"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --bg:            #0B0E14;
  --surface-1:     #111620;
  --surface-2:     #161C28;
  --surface-3:     #1D2533;
  --border:        #212936;
  --border-strong: #2E3849;
  --text-1:        #E9EDF4;
  --text-2:        #9BA6B8;
  --text-3:        #6B7688;
  --accent:        #3987E5;
  --accent-soft:   rgba(57,135,229,0.14);
  --good:          #3DD68C;
  --warn:          #F5B544;
  --crit:          #F2555A;
  --info:          #7C93FF;
  --radius:        10px;
  --radius-lg:     14px;
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 24px; --sp-6: 32px;
  --shadow-1: 0 1px 2px rgba(0,0,0,.35);
  --shadow-2: 0 6px 20px rgba(0,0,0,.45);
}

html, body, [class*="css"], .stApp {
  font-family: 'Inter', system-ui, -apple-system, "Segoe UI", sans-serif;
}
.stApp { background: var(--bg); color: var(--text-1); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { right: 8px; }
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1500px; }

h1, h2, h3, h4 { letter-spacing: -0.02em; color: var(--text-1); font-weight: 650; }
h1 { font-size: 1.9rem !important; }
h4 { font-size: 1.05rem !important; }
h5 { font-size: 0.9rem !important; color: var(--text-2) !important; font-weight: 600 !important;
     text-transform: uppercase; letter-spacing: 0.06em; }
p, span, label, li { color: var(--text-1); }
[data-testid="stCaptionContainer"], .stCaption, small { color: var(--text-3) !important; }
hr { border-color: var(--border) !important; }

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"] > div {
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  padding-top: var(--sp-4);
}
.cg-brand { display:flex; align-items:center; gap:10px; padding: 2px 4px 2px; }
.cg-brand .mark {
  width:34px; height:34px; border-radius:9px; flex:0 0 34px;
  background: linear-gradient(140deg, var(--accent), #6E5CE8);
  display:flex; align-items:center; justify-content:center;
  font-size:12.5px; font-weight:700; color:#fff; letter-spacing:.04em;
  box-shadow: var(--shadow-1);
}
.cg-brand .name { font-size:15px; font-weight:650; color:var(--text-1); line-height:1.15; }
.cg-brand .sub  { font-size:11px; color:var(--text-3); letter-spacing:.03em; }
.cg-user {
  display:flex; align-items:center; gap:10px;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 9px 11px; margin: 14px 4px 2px;
}
.cg-user .u-avatar {
  width:30px; height:30px; flex:0 0 30px; border-radius:50%;
  background: var(--accent-soft); border: 1px solid rgba(57,135,229,.45);
  color: var(--accent); font-size:11.5px; font-weight:700; letter-spacing:.03em;
  display:flex; align-items:center; justify-content:center;
}
.cg-user .u-name { font-size:12.5px; font-weight:600; color: var(--text-1); line-height:1.25; }
.cg-user .u-role { font-size:10.5px; color: var(--text-3); letter-spacing:.02em; }
.cg-by { font-size:12px; color: var(--text-2); }

.cg-navlabel { font-size:10px; letter-spacing:.1em; text-transform:uppercase;
               color:var(--text-3); font-weight:600; margin: 14px 4px 6px; }
.cg-sidefoot { font-size:11px; color:var(--text-3); line-height:1.6; padding: 0 4px; }
.cg-sidefoot b { color: var(--text-2); font-weight:600; }

/* ---------- Buttons ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-1);
  border-radius: 8px;
  font-weight: 500;
  font-size: 13px;
  padding: 0.38rem 0.85rem;
  transition: background .14s ease, border-color .14s ease, transform .08s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
  background: var(--surface-3); border-color: var(--border-strong); color: #fff;
}
.stButton > button:active { transform: translateY(1px); }
.stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}
/* kind is "primary" for st.button and "primaryFormSubmit" for form submits */
.stButton > button[kind^="primary"], .stFormSubmitButton > button[kind^="primary"],
.stDownloadButton > button[kind^="primary"] {
  background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600;
}
.stButton > button[kind^="primary"]:hover, .stFormSubmitButton > button[kind^="primary"]:hover,
.stDownloadButton > button[kind^="primary"]:hover {
  background: #2f76cd; border-color: #2f76cd;
}

/* ---------- Inputs ---------- */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
.stDateInput input, [data-baseweb="select"] > div {
  background: var(--surface-2) !important;
  border-color: var(--border) !important;
  color: var(--text-1) !important;
  border-radius: 8px !important;
  font-size: 13px !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
  border-color: var(--accent) !important; box-shadow: 0 0 0 3px var(--accent-soft) !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder { color: var(--text-3) !important; }
[data-testid="stWidgetLabel"] p { font-size: 12px !important; color: var(--text-2) !important; font-weight: 500; }
[data-testid="stFileUploaderDropzone"] {
  background: var(--surface-2); border: 1px dashed var(--border-strong); border-radius: var(--radius);
}

/* ---------- Chips, badges, meters ---------- */
.id-chip {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 11.5px; color: var(--text-2);
  background: var(--surface-3); border: 1px solid var(--border);
  padding: 1px 7px; border-radius: 5px; letter-spacing: .02em;
  display: inline-block; white-space: nowrap;
}
.status-badge {
  display:inline-flex; align-items:center; gap:5px;
  font-size: 11.5px; font-weight: 600; padding: 3px 10px;
  border-radius: 999px; letter-spacing: .01em; white-space: nowrap; line-height:1.5;
}
.status-badge .dot { width:6px; height:6px; border-radius:50%; background: currentColor; flex:0 0 6px; }
.badge-passed   { background: rgba(61,214,140,.13); color: var(--good); border: 1px solid rgba(61,214,140,.30); }
.badge-warning  { background: rgba(245,181,68,.13); color: var(--warn); border: 1px solid rgba(245,181,68,.30); }
.badge-critical { background: rgba(242,85,90,.13);  color: var(--crit); border: 1px solid rgba(242,85,90,.30); }
.badge-review   { background: rgba(124,147,255,.13);color: var(--info); border: 1px solid rgba(124,147,255,.30); }
.badge-neutral  { background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border); }

.cg-meter { height:5px; background: var(--surface-3); border-radius:999px; overflow:hidden; width:100%; }
.cg-meter > i { display:block; height:100%; border-radius:999px; transition: width .3s ease; }

.cg-score { font-family:'IBM Plex Mono', monospace; font-size:13px; font-weight:500;
            font-variant-numeric: tabular-nums; color: var(--text-1); }
.cg-score .den { color: var(--text-3); font-size:11px; }

/* ---------- KPI tiles ---------- */
.cg-kpi {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 14px 16px 15px; height: 100%;
}
.cg-kpi .k-label { font-size:10.5px; letter-spacing:.08em; text-transform:uppercase;
                   color: var(--text-3); font-weight:650; }
.cg-kpi .k-value { font-size:27px; font-weight:650; color: var(--text-1);
                   line-height:1.15; margin-top:7px; letter-spacing:-.025em; }
.cg-kpi .k-sub   { font-size:11.5px; color: var(--text-2); margin-top:5px; }
.cg-kpi.accent-good  { border-left: 2px solid var(--good); }
.cg-kpi.accent-warn  { border-left: 2px solid var(--warn); }
.cg-kpi.accent-crit  { border-left: 2px solid var(--crit); }
.cg-kpi.accent-info  { border-left: 2px solid var(--accent); }

/* ---------- Status distribution bar ---------- */
.cg-statusbar { display:flex; gap:2px; height:9px; border-radius:999px;
                overflow:hidden; background: var(--surface-3); margin: 4px 0 10px; }
.cg-statusbar > span { display:block; height:100%; }
.cg-legend { display:flex; flex-wrap:wrap; gap:16px; font-size:12px; color: var(--text-2); }
.cg-legend .item { display:flex; align-items:center; gap:6px; }
.cg-legend .swatch { width:9px; height:9px; border-radius:3px; flex:0 0 9px; }
.cg-legend b { color: var(--text-1); font-weight:600; font-variant-numeric: tabular-nums; }

/* ---------- Cards ---------- */
.critical-alert-card {
  background: linear-gradient(90deg, rgba(242,85,90,.07), rgba(242,85,90,.02));
  border: 1px solid rgba(242,85,90,.26); border-left: 2px solid var(--crit);
  border-radius: var(--radius); padding: 12px 14px; margin-bottom: 6px;
}
.top-performer-card {
  background: var(--surface-1); border: 1px solid var(--border);
  border-top: 2px solid var(--warn);
  border-radius: var(--radius); padding: 13px 14px; height:100%;
}
.top-performer-card .rank { font-size:10px; color: var(--text-3); font-weight:700; letter-spacing:.08em; }

.cg-panel { background: var(--surface-1); border:1px solid var(--border);
            border-radius: var(--radius-lg); padding: 16px 18px; }
.cg-empty { background: var(--surface-1); border:1px dashed var(--border-strong);
            border-radius: var(--radius-lg); padding: 30px 22px; text-align:center; }
.cg-empty .e-title { font-weight:600; color: var(--text-1); font-size:14px; }
.cg-empty .e-body  { color: var(--text-3); font-size:12.5px; margin-top:4px; }

/* ---------- Table-ish rows ---------- */
.col-header { color: var(--text-3); font-size: 10px; font-weight: 700;
              letter-spacing: .09em; text-transform: uppercase; }
.cg-cell { font-size:13px; color: var(--text-1); line-height:1.45; }
.cg-cell .sub { font-size:11.5px; color: var(--text-3); }
.cg-rowhead { padding: 0 14px 6px; }

/* Hoverable row containers (st.container(border=True) wrapping a .cg-row marker) */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div > div > .cg-row),
[data-testid="stVerticalBlockBorderWrapper"]:has(.cg-row) {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 2px 12px; margin-bottom: 6px;
  transition: background .13s ease, border-color .13s ease;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.cg-row):hover {
  background: var(--surface-2); border-color: var(--border-strong);
}
.cg-row { display:none; }

/* ---------- Audit log rows ---------- */
.audit-row-ok, .audit-row-err, .audit-row-skip {
  padding: 7px 11px; border-radius: 7px; font-size: 12.5px; margin-bottom: 4px;
  display:flex; align-items:center; gap:8px; border:1px solid transparent;
}
.audit-row-ok   { background: rgba(61,214,140,.07); border-color: rgba(61,214,140,.20); }
.audit-row-err  { background: rgba(242,85,90,.07);  border-color: rgba(242,85,90,.20); color: #FF9BA0; }
.audit-row-skip { background: rgba(245,181,68,.07); border-color: rgba(245,181,68,.20); color: #F5D08A; }
.audit-row-ok b, .audit-row-err b, .audit-row-skip b { font-weight:600; }

/* ---------- Streamlit component overrides ---------- */
[data-testid="stMetric"] {
  background: var(--surface-1); border: 1px solid var(--border);
  padding: 13px 16px; border-radius: var(--radius-lg);
}
[data-testid="stMetricLabel"] p { color: var(--text-3) !important; font-size:10.5px !important;
  text-transform: uppercase; letter-spacing:.08em; font-weight:650 !important; }
[data-testid="stMetricValue"] { color: var(--text-1); font-size: 26px; letter-spacing:-.02em; }

[data-testid="stExpander"] {
  border: 1px solid var(--border) !important; border-radius: var(--radius) !important;
  background: var(--surface-1); overflow: hidden;
}
[data-testid="stExpander"] summary { font-size:13.5px; font-weight:600; color: var(--text-1); }
[data-testid="stExpander"] summary:hover { color: #fff; }

[data-testid="stProgressBar"] > div > div > div { background-color: var(--accent) !important; }
[data-testid="stProgressBar"] > div > div { background-color: var(--surface-3) !important; }

.stAlert { border-radius: var(--radius); font-size: 13px; }
[data-testid="stNotification"] { border-radius: var(--radius); }

.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--border); }
.stTabs [data-baseweb="tab"] { font-size: 13px; font-weight: 500; color: var(--text-2); }
.stTabs [aria-selected="true"] { color: var(--text-1) !important; }

/* Expander chrome — Streamlit paints the <summary> from its own theme, so it
   has to be overridden explicitly or it renders white on a dark page. */
[data-testid="stExpander"] details { background: var(--surface-1) !important; border: none !important; }
[data-testid="stExpander"] summary { background: var(--surface-2) !important; color: var(--text-1) !important; }
[data-testid="stExpander"] summary:hover { background: var(--surface-3) !important; }
[data-testid="stExpanderDetails"] { background: var(--surface-1) !important; }

/* Comboboxes / dropdowns (react-aria in new Streamlit, baseweb in older) */
.stSelectbox div[role="group"], .stMultiSelect div[role="group"],
.stDateInput div[data-baseweb="input"], [data-baseweb="select"] > div {
  background: var(--surface-2) !important;
  border-color: var(--border) !important;
  color: var(--text-1) !important;
  border-radius: 8px !important;
}
.stSelectbox input, .stDateInput input { background: transparent !important; color: var(--text-1) !important; }
.react-aria-Popover, [data-baseweb="popover"] > div, [role="listbox"] {
  background: var(--surface-2) !important;
  border: 1px solid var(--border) !important;
  color: var(--text-1) !important;
  border-radius: 10px !important;
  box-shadow: var(--shadow-2) !important;
}
[role="option"] { color: var(--text-1) !important; font-size: 13px !important; }
[role="option"]:hover, [role="option"][data-focused], [aria-selected="true"][role="option"] {
  background: var(--surface-3) !important;
}

/* Chart / element toolbars */
[data-testid="stElementToolbar"] {
  background: var(--surface-2) !important; border: 1px solid var(--border) !important;
  border-radius: 8px !important;
}
[data-testid="stElementToolbar"] button { color: var(--text-2) !important; }
.vega-embed .vega-actions {
  background: var(--surface-2) !important; border: 1px solid var(--border) !important;
  border-radius: 8px !important;
}
.vega-embed .vega-actions a { color: var(--text-1) !important; }
.vega-embed .vega-actions a:hover { background: var(--surface-3) !important; }
.vega-embed summary { color: var(--text-3) !important; }

/* Tighten the vertical rhythm inside hoverable rows */
[data-testid="stVerticalBlockBorderWrapper"]:has(.cg-row) [data-testid="stVerticalBlock"] { gap: 0.25rem; }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--surface-3); border-radius: 999px;
                            border: 2px solid var(--bg); }
::-webkit-scrollbar-thumb:hover { background: var(--border-strong); }
</style>
"""


def inject_css():
    """Apply the stylesheet. Call once, after st.set_page_config()."""
    st.markdown(CSS, unsafe_allow_html=True)
