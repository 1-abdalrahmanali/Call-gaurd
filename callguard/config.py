"""Configuration: secrets, provider endpoints and pipeline tuning.

Every tunable in the application is resolved here and nowhere else, so there
is a single place to look when behaviour depends on deployment settings.
"""

import os

import streamlit as st


APP_NAME = "CallGuard"
APP_TAGLINE = "Quality Assurance Platform"
BUILT_BY = "Abdalruhman Ali"


def secret(name: str, default: str = "") -> str:
    """Read from st.secrets, then the environment. Never raises."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default) or "")


def first_secret(*names, default=""):
    """First non-empty secret from `names`, else `default`.

    Lets the newer provider-neutral names take precedence while the older
    GROQ_* names keep working, so an existing deployment does not break.
    """
    for name in names:
        value = secret(name)
        if value:
            return value
    return default


APP_PASSWORD = secret("APP_PASSWORD")

# ==========================================================================
# PROVIDERS
# --------------------------------------------------------------------------
# Transcription and auditing are two independent OpenAI-compatible endpoints,
# because they are NOT interchangeable:
#
#   * OpenRouter exposes chat completions only — it has no /audio/transcriptions
#     endpoint, so speech-to-text CANNOT run there.
#   * Groq hosts Whisper, so transcription stays there (or any other Whisper
#     host you point it at).
#
# Each side gets its own key, base URL and model. Set only what you use.
# ==========================================================================

# ---- Speech to text ------------------------------------------------------
TRANSCRIBE_API_KEY = first_secret("TRANSCRIBE_API_KEY", "GROQ_API_KEY")
TRANSCRIBE_BASE_URL = first_secret("TRANSCRIBE_BASE_URL", "GROQ_BASE_URL",
                                   default="https://api.groq.com/openai/v1")
TRANSCRIBE_MODEL = first_secret("TRANSCRIBE_MODEL", "GROQ_TRANSCRIBE_MODEL",
                                default="whisper-large-v3")

# ---- The auditing LLM ----------------------------------------------------
# Defaults to OpenRouter + Qwen3 235B A22B. Set AUDIT_BASE_URL/AUDIT_MODEL to
# point anywhere else that speaks the OpenAI chat-completions API.
AUDIT_API_KEY = first_secret("AUDIT_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY")
AUDIT_BASE_URL = first_secret("AUDIT_BASE_URL",
                              default="https://openrouter.ai/api/v1")
AUDIT_MODEL = first_secret("AUDIT_MODEL", "GROQ_AUDIT_MODEL",
                           default="qwen/qwen3-235b-a22b")

IS_OPENROUTER = "openrouter.ai" in AUDIT_BASE_URL.lower()

# Optional OpenRouter attribution headers — they put your app on the
# OpenRouter leaderboards. Harmless and ignored by every other provider.
APP_PUBLIC_URL = secret("CALLGUARD_APP_URL")
AUDIT_HEADERS = {}
if IS_OPENROUTER:
    if APP_PUBLIC_URL:
        AUDIT_HEADERS["HTTP-Referer"] = APP_PUBLIC_URL
    AUDIT_HEADERS["X-Title"] = "CallGuard"

# Qwen3 235B A22B is 32K context by default (131K with YaRN). A very long call
# plus the prompt could overflow it, which fails the whole file. Trim what is
# SENT to the auditor; the full transcript is always stored in the database.
try:
    MAX_TRANSCRIPT_CHARS = int(secret("CALLGUARD_MAX_TRANSCRIPT_CHARS", "48000") or 48000)
except ValueError:
    MAX_TRANSCRIPT_CHARS = 48000

# The working directory is ephemeral on most hosts (Streamlit Community Cloud
# included). Point CALLGUARD_DATA_DIR at a mounted volume to keep data.
DATA_DIR = secret("CALLGUARD_DATA_DIR", ".")
DB_FILE = os.path.join(DATA_DIR, "enterprise_qa.db")
BANNED_WORDS_FILE = os.path.join(DATA_DIR, "banned_words.json")
AUDIO_DIR = os.path.join(DATA_DIR, "audio_store")
os.makedirs(AUDIO_DIR, exist_ok=True)

# ---- Pipeline tuning -----------------------------------------------------
# Workers = calls in flight at once. Keep at or below your Groq RPM budget
# divided by 2 (each file costs 1 Whisper request + 1 LLM request).
# This is a throughput setting, not a user choice — it lives here, not in the
# UI. Override it with the CALLGUARD_WORKERS secret if your Groq plan allows
# more concurrency. Keep it at or below your requests-per-minute budget
# divided by two (each file costs 1 Whisper request + 1 LLM request).
MAX_WORKERS = 12
# OpenRouter caps *concurrent in-flight spend*, not just the total balance, so
# four big-model requests at once can 402 on an account that has credit. Start
# lower there; raise it with CALLGUARD_WORKERS once you have headroom.
_DEFAULT_WORKERS = "2" if IS_OPENROUTER else "4"
try:
    AUDIT_WORKERS = max(1, min(MAX_WORKERS,
                               int(secret("CALLGUARD_WORKERS", _DEFAULT_WORKERS)
                                   or _DEFAULT_WORKERS)))
except ValueError:
    AUDIT_WORKERS = int(_DEFAULT_WORKERS)

# Longest single sleep we will honour from a server's Retry-After.
MAX_RETRY_WAIT = 180.0
# Cap the audit response. The JSON we want is ~500 tokens; without a ceiling a
# degenerate generation can run to the model's full 8K output limit.
try:
    AUDIT_MAX_TOKENS = int(secret("CALLGUARD_AUDIT_MAX_TOKENS", "2048") or 2048)
except ValueError:
    AUDIT_MAX_TOKENS = 2048
# How many times to re-ask when the model returns something that is not JSON.
JSON_ATTEMPTS = 3
# Files are processed in chunks, each committed before the next starts, so a
# crash or a closed tab loses at most one chunk.
CHUNK_SIZE = 25
MAX_RETRIES = 5
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}
# Groq rejects audio uploads above 25 MB on the free tier. Catch it here
# before we burn a request. Raise it with the CALLGUARD_MAX_AUDIO_MB secret if
# your plan allows more, and raise server.maxUploadSize in config.toml to match.
try:
    MAX_UPLOAD_MB = float(secret("CALLGUARD_MAX_AUDIO_MB", "25") or 25)
except ValueError:
    MAX_UPLOAD_MB = 25.0
ALLOWED_AUDIO = ["mp3", "wav", "m4a", "mp4", "mpeg", "mpga", "webm", "flac", "ogg"]

PAGE_SIZE = 15
QUERY_TTL = 30  # seconds — bounds staleness when several people are logged in

PASS_THRESHOLD = 8.0
WARN_THRESHOLD = 5.0
