"""Provider clients and model discovery.

Transcription and auditing are separate OpenAI-compatible endpoints because
they are not interchangeable: OpenRouter serves chat completions only and has
no /audio/transcriptions route, so speech-to-text cannot run there.
"""

import hashlib
import re

import streamlit as st
from openai import OpenAI

from callguard.config import (
    AUDIT_API_KEY,
    AUDIT_BASE_URL,
    AUDIT_HEADERS,
    AUDIT_MODEL,
    TRANSCRIBE_API_KEY,
    TRANSCRIBE_BASE_URL,
    TRANSCRIBE_MODEL,
)


def _fingerprint(*parts) -> str:
    """Short, non-reversible tag, so caches re-check when a key or endpoint
    changes while the key itself is never stored in the cache key."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def transcribe_client():
    return OpenAI(api_key=TRANSCRIBE_API_KEY, base_url=TRANSCRIBE_BASE_URL, timeout=300.0)


def audit_client():
    return OpenAI(api_key=AUDIT_API_KEY, base_url=AUDIT_BASE_URL,
                  timeout=300.0, default_headers=AUDIT_HEADERS or None)


@st.cache_data(ttl=600, show_spinner=False)
def _list_models(base_url: str, _fp: str, _key: str) -> tuple:
    """Model IDs an endpoint will serve to this key.

    Empty tuple means the check itself failed (offline, bad key, endpoint with
    no /models route) — callers treat that as "couldn't check" and fail open
    rather than blocking a run on a flaky network.
    """
    if not _key:
        return ()
    try:
        client = OpenAI(api_key=_key, base_url=base_url, timeout=30.0)
        return tuple(sorted(m.id for m in client.models.list().data))
    except Exception:
        return ()


PROVIDERS = (
    ("Transcription", "TRANSCRIBE"),
    ("Audit", "AUDIT"),
)


def provider_status():
    """One row per provider: what is configured and whether it is reachable."""
    rows = []
    for label, prefix in PROVIDERS:
        key = TRANSCRIBE_API_KEY if prefix == "TRANSCRIBE" else AUDIT_API_KEY
        base = TRANSCRIBE_BASE_URL if prefix == "TRANSCRIBE" else AUDIT_BASE_URL
        model = TRANSCRIBE_MODEL if prefix == "TRANSCRIBE" else AUDIT_MODEL
        models = _list_models(base, _fingerprint(key, base), key) if key else ()
        rows.append({
            "label": label,
            "prefix": prefix,
            "key_set": bool(key),
            "base_url": base,
            "model": model,
            "models": models,
            # None = could not check. True/False = definitely present/absent.
            "model_ok": None if not models else (model in models),
        })
    return rows


def missing_models(rows=None):
    """Configured models we know for certain the key cannot reach."""
    rows = rows if rows is not None else provider_status()
    return [r for r in rows if r["model_ok"] is False]


def similar_models(candidates, wanted, limit=12):
    """Best-effort suggestions when a model ID is wrong.

    OpenRouter serves 300+ IDs, so dumping the whole list is useless — match
    on the meaningful word-parts of what was asked for instead.
    """
    tokens = [t for t in re.split(r"[^a-z0-9.]+", wanted.lower()) if len(t) > 2]
    scored = []
    for candidate in candidates:
        low = candidate.lower()
        score = sum(1 for t in tokens if t in low)
        if score:
            scored.append((score, candidate))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [c for _, c in scored[:limit]]
