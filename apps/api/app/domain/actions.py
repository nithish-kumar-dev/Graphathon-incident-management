"""Canonical action specifications and their hashes (Phase 5 builds on this)."""

from __future__ import annotations

import hashlib
import json


def canonical_json(spec: dict) -> str:
    """Byte-stable JSON: sorted keys, no whitespace, UTF-8, NaN/Infinity rejected."""
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def spec_hash(spec_json: str) -> str:
    return hashlib.sha256(spec_json.encode("utf-8")).hexdigest()


def approval_applies(action: dict, approval: dict, now_ms: int) -> bool:
    """An approval authorizes exactly one action version. Any change to the spec breaks it."""
    expires = approval.get("expires_at_ms")
    return (
        approval.get("decision") == "APPROVE"
        and approval.get("spec_hash") == action.get("spec_hash")
        and approval.get("action_version") == action.get("version")
        and expires is not None
        and expires > now_ms
    )
