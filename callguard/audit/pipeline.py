"""The per-recording worker: transcribe, audit, score.

Runs inside a thread pool, so nothing here may touch st.* or the database.
"""

import os

from callguard.audit.jsonparse import extract_json
from callguard.audit.prompt import JSON_ONLY_SYSTEM, build_audit_prompt
from callguard.audit.retry import _is_out_of_credits, call_with_backoff
from callguard.audit.scoring import score_result
from callguard.config import (
    AUDIO_DIR,
    AUDIT_MAX_TOKENS,
    AUDIT_MODEL,
    IS_OPENROUTER,
    JSON_ATTEMPTS,
    MAX_TRANSCRIPT_CHARS,
    TRANSCRIBE_MODEL,
)


def audit_request_extras():
    """Provider-specific body fields for the audit call.

    require_parameters      routes only to upstreams that honour response_format.
    reasoning.exclude=True  puts Qwen3's hybrid brain in NON-thinking mode.
                            Auditing is structured extraction, not a maths
                            problem — thinking buys nothing here and is the
                            main source of unparseable output.
    """
    if IS_OPENROUTER:
        return {
            "provider": {"require_parameters": True},
            "reasoning": {"exclude": True, "enabled": False},
        }
    return {}
def request_audit_json(auditor, prompt, on_retry=None):
    """Ask the audit model for JSON, re-asking if it returns something else.

    A hybrid reasoning model occasionally emits a degenerate response — leaked
    reasoning, a runaway number, a bare sentence. That is a sampling failure,
    not a permanent one, so re-ask instead of losing the recording. Each retry
    is stricter: a JSON-only system message, then zero temperature.
    """
    last_preview = ""
    for attempt in range(JSON_ATTEMPTS):
        messages = [{"role": "user", "content": prompt}]
        if attempt:
            messages.insert(0, {"role": "system", "content": JSON_ONLY_SYSTEM})

        response = call_with_backoff(
            auditor.chat.completions.create,
            model=AUDIT_MODEL,
            temperature=0.0 if attempt else 0.1,
            max_tokens=AUDIT_MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=messages,
            extra_body=audit_request_extras() or None,
        )

        choice = response.choices[0] if response.choices else None
        content = (getattr(getattr(choice, "message", None), "content", "") or "")
        result = extract_json(content)
        if result is not None:
            return result, attempt

        last_preview = " ".join(content.split())[:110]
        # A cut-off response means the cap was too low, not bad sampling.
        if getattr(choice, "finish_reason", None) == "length":
            last_preview = (f"response hit the {AUDIT_MAX_TOKENS}-token cap "
                            "(raise CALLGUARD_AUDIT_MAX_TOKENS)")
            break
        if on_retry and attempt < JSON_ATTEMPTS - 1:
            on_retry(attempt + 1, last_preview)

    raise ValueError(
        f"the audit model returned no usable JSON after {JSON_ATTEMPTS} attempts"
        + (f" (last response began: {last_preview})" if last_preview
           else " (empty response)")
    )


def process_one_call(clients, banned_rules, filename, audio_bytes, call_uid):
    """Runs in a worker thread. Returns a plain dict — never touches st.* or the DB.

    `clients` is (transcribe_client, audit_client). They are separate because
    transcription and auditing can live on different providers.
    """
    speech, auditor = clients
    ext = (os.path.splitext(filename)[1] or ".mp3").lower()
    audio_path = os.path.join(AUDIO_DIR, f"{call_uid}{ext}")
    try:
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        def _transcribe():
            # Re-opened per attempt: a spent file handle can't be replayed.
            with open(audio_path, "rb") as fh:
                return speech.audio.transcriptions.create(
                    model=TRANSCRIBE_MODEL, file=fh, response_format="verbose_json")

        transcription = call_with_backoff(_transcribe)
        transcript_text = (getattr(transcription, "text", "") or "").strip()
        duration_seconds = getattr(transcription, "duration", None)

        if not transcript_text:
            raise ValueError("the transcription came back empty — is the audio silent?")

        # The full transcript is stored; only what we SEND is trimmed, so a
        # very long call cannot overflow the audit model's context window.
        prompt_transcript = transcript_text
        truncated = len(transcript_text) > MAX_TRANSCRIPT_CHARS
        if truncated:
            prompt_transcript = (transcript_text[:MAX_TRANSCRIPT_CHARS]
                                 + " [transcript truncated for audit]")

        result, json_retries = request_audit_json(
            auditor, build_audit_prompt(prompt_transcript, banned_rules))

        scored = score_result(result)
        return {
            "ok": True,
            "filename": filename,
            "call_uid": call_uid,
            "audio_path": audio_path,
            "transcript_text": transcript_text,
            "duration_seconds": duration_seconds,
            "truncated": truncated,
            "json_retries": json_retries,
            "language": result.get("language"),
            "audit_summary": result.get("audit_summary"),
            "recommended_coaching": result.get("recommended_coaching"),
            **scored,
        }
    except Exception as exc:
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass
        message = str(exc) or exc.__class__.__name__
        low = message.lower()
        if "model_not_found" in low or "does not exist or you do not have access" in low:
            message = (f"model unavailable — check AUDIT_MODEL ({AUDIT_MODEL}) "
                       f"and TRANSCRIBE_MODEL ({TRANSCRIBE_MODEL}) in your secrets")
        elif "in_flight" in low or "in-flight" in low:
            message = ("provider was still busy after retrying — lower "
                       "CALLGUARD_WORKERS or add OpenRouter credits")
        elif _is_out_of_credits(exc):
            message = ("out of OpenRouter credits — top up at "
                       "openrouter.ai/settings/credits")
        return {"ok": False, "filename": filename, "audio_path": audio_path,
                "error": message,
                "budget_error": ("in_flight" in low or "in-flight" in low
                                 or _is_out_of_credits(exc))}


def audio_store_stats():
    total_bytes, count = 0, 0
    try:
        for name in os.listdir(AUDIO_DIR):
            path = os.path.join(AUDIO_DIR, name)
            if os.path.isfile(path):
                total_bytes += os.path.getsize(path)
                count += 1
    except OSError:
        pass
    return count, total_bytes / (1024 * 1024)
