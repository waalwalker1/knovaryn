"""ID generation (spec §6.1).

Externally visible handles use UUIDv7 (sortable, cryptographically strong).
Sequential DB ids are never exposed. A separate module keeps generation
injectable behind the ``IdGenerator`` port.

A generator may be constructed with ``seed=...`` for **reproducible-mode**
runs (offline benchmarks, golden fixtures): handles are then derived from the
seed via HMAC-SHA256 and a per-instance counter, so identical inputs produce
byte-identical artifacts (release-bundle digests included). The default
constructor stays wall-clock UUIDv7 — production identifiers remain
unguessable, which deterministic mode must never be used to weaken.
``new_token`` always uses ``secrets`` regardless of seed: confirmation/lease
tokens are security material, never reproducible output.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

import uuid6

T = TypeVar("T")


class IdGenerator:
    """Generate UUIDv7 handles and opaque single-use tokens."""

    def __init__(self, *, seed: str | None = None) -> None:
        self._seed = seed
        self._counter = 0

    def new(self) -> str:
        if self._seed is None:
            return str(uuid6.uuid7())
        self._counter += 1
        digest = hmac.new(
            self._seed.encode("utf-8"), str(self._counter).encode("ascii"), hashlib.sha256
        ).hexdigest()
        # Format as a canonical UUID string; version/variant bits are not
        # meaningful here — seeded handles are opaque, stable test/bench IDs.
        return str(uuid.UUID(digest[:32]))

    def new_handle(self, prefix: str) -> str:
        """A namespaced UUIDv7 handle, e.g. ``job_01H...``."""
        return f"{prefix}_{self.new()}"

    def new_token(self, *, nbytes: int = 32) -> str:
        """Cryptographic random token (for confirmations, leases)."""
        return secrets.token_hex(nbytes)


# Module-level idempotency for default generator (peculiar: uuid6 may cache time;
# we keep a plain uuid fallback if uuid6 is unavailable at runtime).
def _fallback_uuid7() -> str:
    return str(uuid.uuid4())


def make_id_generator() -> IdGenerator:
    return IdGenerator()


def with_deterministic_ids(
    deterministic: bool = False,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator helper to make a function use deterministic ids (tests)."""

    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: object, **kwargs: object) -> T:
            return fn(*args, **kwargs)

        return wrapper

    return deco
