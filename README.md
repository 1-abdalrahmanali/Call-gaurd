# CallGuard

Streamlit console for auditing call-centre recordings: Whisper transcribes the
audio, an LLM scores it against your compliance rules, and the results are
browsable per call and per agent.

Run it exactly as before — nothing about deployment changed:

```bash
pip install -r requirements.txt
streamlit run app_web.py
```

## Layout

`app_web.py` is a 74-line entry point. It does six things in the order they
have to happen — page config, stylesheet, database, login gate, routing state,
dispatch — and nothing else. All the code lives in the `callguard` package.

```
app_web.py                      entry point and view router
requirements.txt
.streamlit/config.toml          dark theme
secrets.toml.example            copy to .streamlit/secrets.toml and fill in
smoke_test.py                   77 checks — run before every push

callguard/
    config.py          every secret and tunable, resolved in one place
    theme.py           design tokens + stylesheet (inject_css)
    formatting.py      escaping, badges, chips, value formatting — pure, no I/O
    components.py      rows, pagers, status bar, score-trend chart
    database.py        schema, migrations, cached reads, transactional writes
    providers.py       API clients, model discovery, provider health
    exports.py         the CSV download
    auth.py            password gate
    navigation.py      URL/session routing and the sidebar

    audit/
        jsonparse.py   tolerant JSON extraction from a chat completion
        retry.py       backoff policy, including the OpenRouter 402 rules
        prompt.py      the auditor prompt
        scoring.py     scoring — pure functions, no I/O
        pipeline.py    the per-recording worker (runs in a thread pool)

    views/
        dashboard.py       agents.py        agent_details.py
        call_report.py     auditor.py       settings.py
```

## Where to change things

| You want to change | Open |
|---|---|
| A model, endpoint, key, limit or threshold | `callguard/config.py` |
| A colour, spacing value or CSS rule | `callguard/theme.py` |
| How a score is calculated | `callguard/audit/scoring.py` |
| What the AI is asked to look for | `callguard/audit/prompt.py` |
| Retry behaviour on a provider error | `callguard/audit/retry.py` |
| Anything on one screen | the matching file in `callguard/views/` |
| A table, index or query helper | `callguard/database.py` |

## Two rules worth keeping

**`st.set_page_config()` must stay the first Streamlit call.** `app_web.py`
imports `callguard.config` for the app name, calls `set_page_config`, and only
then imports the views. Moving those imports above it breaks the app.

**Nothing under `callguard/audit/` may touch `st.*` or the database.** That code
runs inside a thread pool where neither is safe. The worker returns a plain
dict; `views/auditor.py` is what writes it and draws it.

## Testing

```bash
python smoke_test.py
```

77 checks: scoring and coercion logic, JSON extraction against reasoning-model
output, the retry policy against real provider error payloads, the CSV export,
and a headless render of every screen against a database seeded with the edge
cases that have broken this app before. It exits non-zero on any failure.

Also worth running before any push, since it catches a truncated file in a
second:

```bash
python -m compileall callguard app_web.py
```
