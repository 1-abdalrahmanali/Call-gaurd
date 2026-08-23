"""Tolerant JSON extraction from a chat completion.

Reasoning models emit <think> blocks, code fences and stray prose. A strict
json.loads() on the raw content turns any of those into a lost recording.
"""

import json
import re


_THINK_RE = re.compile(r"<think[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_RE = re.compile(r"<think[^>]*>.*", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*|```", re.MULTILINE)


def extract_json(text):
    """Best-effort dict out of a chat completion. None if there isn't one."""
    if not text or not isinstance(text, str):
        return None

    cleaned = _THINK_RE.sub("", text)          # complete <think>...</think>
    cleaned = _OPEN_THINK_RE.sub("", cleaned)  # unterminated <think> at the end
    cleaned = _FENCE_RE.sub("", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass

    # Fall back to brace matching, so prose either side of the object is fine.
    start = cleaned.find("{")
    if start == -1:
        return None
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start:index + 1])
                    return parsed if isinstance(parsed, dict) else None
                except (json.JSONDecodeError, ValueError):
                    return None
    return None
