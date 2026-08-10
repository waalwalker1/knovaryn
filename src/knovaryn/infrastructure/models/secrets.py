"""Secret handling (spec §11.6).

Never log or persist secrets. Redact bearer/proxy/API tokens in config at the
display boundary, and refuse to write secrets into the cost ledger or audit
record. Kept intentionally small and dependency-free.
"""

from __future__ import annotations

import re
from typing import Any

_SECRET_KEYS = re.compile(
    r"(token|secret|key|password|credential|bearer|authorization)", re.IGNORECASE
)
_TOKEN_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}|AIza[A-Za-z0-9_\\-]{10,})"
)


def is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEYS.search(key))


def redact(value: Any) -> str:
    """Return a redacted form of a potential secret (never the raw value)."""
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if len(text) > 8:
        return text[:4] + "…" + text[-3:]
    return "••••"


def redact_config(data: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    """Deep-redact any key that looks like a secret. Bounded recursion."""
    if depth > 12:
        return {"__truncated__": True}
    out: dict[str, Any] = {}
    for k, v in data.items():
        if is_secret_key(k):
            out[k] = redact(v)
        elif isinstance(v, dict):
            out[k] = redact_config(v, depth=depth + 1)
        elif isinstance(v, list):
            out[k] = [
                redact_config(i, depth=depth + 1)
                if isinstance(i, dict)
                else redact(i)
                if is_secret_key(k)
                else i
                for i in v
            ]
        elif isinstance(v, str) and _TOKEN_PATTERN.search(v):
            out[k] = _TOKEN_PATTERN.sub(_mask_token, v)
        else:
            out[k] = v
    return out


def _mask_token(match: re.Match[str]) -> str:
    token = match.group(0)
    if len(token) <= 12:
        return "••••"
    return token[:6] + "…Redacted…" + token[-4:]


def assert_not_logged(entries: list[dict[str, Any]]) -> list[str]:
    """Return any secret-like key names that would leak if logged."""
    leaks: list[str] = []
    for entry in entries:
        for key in entry:
            if is_secret_key(key):
                leaks.append(key)
    return leaks
