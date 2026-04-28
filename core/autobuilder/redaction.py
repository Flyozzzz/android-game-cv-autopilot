"""Secret redaction for builder artifacts, traces, and reports."""
from __future__ import annotations

import json
import re
from typing import Any


PATTERNS = (
    (re.compile(r"sk-or-v1-[A-Za-z0-9_-]{6,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)(api[_-]?key|token|password|passwd|secret)(\s*[:=]\s*)[^\s,'\"}]+"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key|token|password|passwd|secret)(\s+)[^\s,'\"}]+"), r"\1\2[REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"\+?\d[\d .()-]{7,}\d"), "[REDACTED_PHONE]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_CARD]"),
)


def redact_text(text: str) -> str:
    redacted = str(text or "")
    for pattern, replacement in PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, tuple):
        return [redact_obj(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if re.search(r"(?i)(api[_-]?key|token|password|passwd|secret|cvv)", key_text):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = redact_obj(item)
        return result
    return value


def redacted_json(value: Any) -> str:
    return json.dumps(redact_obj(value), ensure_ascii=False, indent=2)
