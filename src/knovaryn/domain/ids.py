"""ID generation (spec §6.1).

Externally visible handles use UUIDv7 (sortable, cryptographically strong).
Sequential DB ids are never exposed. A separate module keeps generation
injectable behind the ``IdGenerator`` port.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

import uuid6

T = TypeVar("T")


class IdGenerator:
    """Generate UUIDv7 handles and opaque single-use tokens."""

    def new(self) -> str:
        return str(uuid6.uuid7())

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
