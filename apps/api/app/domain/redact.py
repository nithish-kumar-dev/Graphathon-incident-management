"""Best-effort redaction for free text that gets stored (alert summaries). Defence in depth only:
the demo data is synthetic, but ingest must never persist obvious secrets or personal data."""

from __future__ import annotations

import re

_RULES = [
    (re.compile(r"(?i)\b(bearer|token|api[_-]?key|password|secret)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[NUMBER]"),
]


def redact(text: str) -> str:
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text
