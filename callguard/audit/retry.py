"""Backoff policy for the two provider APIs."""

import random
import time

from callguard.config import MAX_RETRIES, MAX_RETRY_WAIT, RETRYABLE_STATUS


def _parse_delay(raw):
    text = str(raw).strip().lower()
    try:
        if text.endswith("ms"):
            return float(text[:-2]) / 1000.0
        if text.endswith("m"):
            return float(text[:-1]) * 60.0
        return float(text.rstrip("s"))
    except ValueError:
        return None


def _retry_after_seconds(exc):
    """Seconds the server asked us to wait, from headers OR the error body.

    OpenRouter's 402 puts Retry-After inside error.metadata.headers rather
    than only on the HTTP response, so both places are checked.
    """
    keys = ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests")
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    for key in keys:
        raw = headers.get(key) or headers.get(key.title())
        if raw:
            value = _parse_delay(raw)
            if value is not None:
                return value

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        meta = (body.get("error") or {}).get("metadata") or {}
        nested = meta.get("headers") or {}
        if isinstance(nested, dict):
            for key in keys:
                raw = nested.get(key) or nested.get(key.title()) or nested.get("Retry-After")
                if raw:
                    value = _parse_delay(raw)
                    if value is not None:
                        return value
    return None
_TRANSIENT_402 = ("in_flight_budget_exhausted", "in-flight", "in flight",
                  "retry after in-flight", "would exceed your available credits "
                  "given your current in-flight")


def _is_out_of_credits(exc) -> bool:
    text = str(exc).lower()
    if any(marker in text for marker in _TRANSIENT_402):
        return False
    return "credit" in text or "payment required" in text or "insufficient" in text


def is_retryable(exc, status) -> bool:
    if status in RETRYABLE_STATUS:
        return True
    if status == 402:
        # Retry only the in-flight variety, never a genuinely empty balance.
        return not _is_out_of_credits(exc)
    return False


def call_with_backoff(fn, *args, **kwargs):
    """Exponential backoff with jitter on rate limits and transient 5xx.

    `fn` is called fresh on every attempt, so file handles must be opened
    inside it — a consumed file object cannot be replayed on retry.
    """
    delay = 2.0
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            status = getattr(exc, "status_code", None)
            if status is None:
                status = getattr(getattr(exc, "response", None), "status_code", None)
            if not is_retryable(exc, status) or attempt == MAX_RETRIES - 1:
                raise
            asked = _retry_after_seconds(exc)
            # An explicit Retry-After is an instruction, so allow a longer wait
            # than our own backoff would ever choose (OpenRouter asks for 120s).
            wait = min(asked, MAX_RETRY_WAIT) if asked else min(delay, 60)
            time.sleep(wait + random.uniform(0, 1.5))
            delay = min(delay * 2, 60)
    raise last_exc  # unreachable, but keeps the contract explicit
