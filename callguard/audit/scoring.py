"""Scoring. Pure functions over the model's JSON — no I/O, no Streamlit."""

from callguard.config import PASS_THRESHOLD, WARN_THRESHOLD
from callguard.formatting import as_bool, as_list


VALID_SENTIMENT = {"Positive", "Neutral", "Negative"}


def score_result(result):
    """Pure scoring. Same weights as the original — but every field coming
    back from the model is now coerced before it is measured."""
    grammar_errs = [e for e in (result.get("grammar_errors") or []) if isinstance(e, dict)]
    banned_words = as_list(result.get("banned_words_found"))
    offensive_words = as_list(result.get("offensive_words_found"))
    general_profanity = as_list(result.get("general_profanity_found"))
    arabic_detected = as_bool(result.get("arabic_detected"))
    arabic_words = as_list(result.get("arabic_words_found"))
    # Default True (no penalty) when the model omits the field, so a missing
    # key never silently costs the agent a point.
    formal_greeting = as_bool(result.get("formal_greeting_made", True))

    grammar_penalty = min(len(grammar_errs) * 0.15, 2.0)
    offensive_penalty = (len(offensive_words) + len(general_profanity)) * 2.0
    banned_penalty = len(banned_words) * 1.0
    greeting_penalty = 0.0 if formal_greeting else 1.0

    grammar_score = round(max(0.0, 10.0 - grammar_penalty), 1)
    final_score = round(max(
        0.0, 10.0 - grammar_penalty - offensive_penalty - banned_penalty - greeting_penalty), 1)

    call_status = ("Passed" if final_score >= PASS_THRESHOLD
                   else "Warning" if final_score >= WARN_THRESHOLD else "Critical")
    profanity_flag = 1 if (as_bool(result.get("has_profanity"))
                           or offensive_words or general_profanity) else 0

    violations = banned_words + offensive_words + general_profanity
    if not formal_greeting:
        violations.append("Missing formal greeting at the beginning of the call.")
    if arabic_detected:
        # Informational only — does not affect qa_score.
        violations.append(
            f"Arabic language detected: {', '.join(arabic_words)}" if arabic_words
            else "Arabic language detected during the call.")

    sentiment_start = result.get("sentiment_start")
    sentiment_end = result.get("sentiment_end")
    return {
        "final_score": final_score,
        "grammar_score": grammar_score,
        "call_status": call_status,
        "profanity_flag": profanity_flag,
        "all_violations": violations,
        "grammar_errs": grammar_errs,
        "sentiment_start": sentiment_start if sentiment_start in VALID_SENTIMENT else None,
        "sentiment_end": sentiment_end if sentiment_end in VALID_SENTIMENT else None,
    }
