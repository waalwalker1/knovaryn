"""State-handle safety (spec §23.3).

Small, dependency-free helpers for validating opaque handles (project ids,
source ids, resource names) before they are used to build paths or keys, and
for constant-time comparison of bearer tokens. This is the defensive net that
prevents handle injection into filesystem/artifact keys.
"""

from __future__ import annotations

import hmac
import re
import secrets

_HANDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
# Known-good prefix families we mint (see domain/ids.py).
_ALLOWED_PREFIXES = ("proj_", "src_", "span_", "chunk_", "ex_", "ck", "job_", "digest")


def is_valid_handle(value: str) -> bool:
    """Return True only for a safe, bounded handle string."""
    if not isinstance(value, str) or not value:
        return False
    return bool(_HANDLE_RE.match(value))


def assert_safe_handle(value: str, *, what: str = "handle") -> None:
    """Raise ValueError if the handle could be unsafe for path/key construction."""
    if not is_valid_handle(value):
        raise ValueError(f"unsafe {what}: {value!r} — expected [A-Za-z0-9_.-] 1..128 chars")


def safe_key(parts: list[str]) -> str:
    """Join parts into a single filesystem/artifact-safe key."""
    for p in parts:
        assert_safe_handle(p, what="key part")
    return "/".join(parts)


def constant_time_equal(a: str, b: str) -> bool:
    """Compare two strings in constant time (for bearer tokens / secrets)."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def new_handle(mint_prefix: str) -> str:
    """Mint a fresh random handle under a known-safe prefix."""
    if not mint_prefix.startswith(_ALLOWED_PREFIXES):
        raise ValueError(f"invalid prefix {mint_prefix!r} — not in allowed families {_ALLOWED_PREFIXES}")
    token = secrets.token_hex(8)
    return f"{mint_prefix}{token}"


__all__ = ["is_valid_handle", "assert_safe_handle", "safe_key", "constant_time_equal", "new_handle", "_ALLOWED_PREFIXES"]
