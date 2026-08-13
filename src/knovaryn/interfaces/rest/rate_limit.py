"""Per-principal rate limiting (spec §17.4, WP J7).

A sliding-window rate limiter keyed by the authenticated principal (falling back
to the client IP for unauthenticated/local requests). Excess requests receive a
``429 Too Many Requests`` with the appropriate ``Retry-After`` hint and the
standard headers (RateLimit / Limit / Remaining) so clients can self-throttle.

The upload byte cap and the remaining abuse controls (concurrent jobs, provider
calls, publication attempts) are enforced where the work actually happens — see
the application and infrastructure layers; this module owns only the HTTP-level
per-principal request budget.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from ...domain.config import load_config

# Default window (seconds) and per-principal budget derived from config.
_WINDOW = 60.0


class _Bucket:
    """Sliding-window log of request timestamps for one principal/IP."""

    __slots__ = ("times",)

    def __init__(self) -> None:
        self.times: deque[float] = deque()

    def allow(self, limit: int, now: float) -> bool:
        # Drop timestamps outside the window, then check the remaining count.
        while self.times and now - self.times[0] >= _WINDOW:
            self.times.popleft()
        if len(self.times) >= limit:
            return False
        self.times.append(now)
        return True

    def next_retry(self, now: float) -> float:
        return self.times[0] + _WINDOW - now if self.times else 0.0


# Module-level sliding-window buckets, shared by the middleware instance. Kept
# at module scope so tests can reset them between cases (the FastAPI app and its
# middleware are process singletons).
_BUCKETS: dict[str, _Bucket] = defaultdict(_Bucket)
_LOCK: Any = None  # asyncio.Lock, lazily created


def reset_rate_limit_state() -> None:
    """Clear all rate-limit buckets (used by tests)."""
    global _LOCK, _BUCKETS
    _BUCKETS = defaultdict(_Bucket)
    _LOCK = None


class RateLimitMiddleware:
    """ASGI middleware enforcing a per-principal request budget (429)."""

    def __init__(self, app: Any, *, requests_per_minute: int | None = None) -> None:
        self.app = app
        self.limit = requests_per_minute

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cap = self._configured_limit()
        if cap is None or cap <= 0:  # 0 = disabled
            await self.app(scope, receive, send)
            return

        import asyncio

        global _LOCK
        if _LOCK is None:
            _LOCK = asyncio.Lock()
        now = time.monotonic()

        key = self._identity(scope)

        async with _LOCK:
            bucket = _BUCKETS[key]
            if not bucket.allow(cap, now):
                retry = bucket.next_retry(now)
                await self._respond_429(send, retry, cap)
                return

        # Attach the request budget to the scope so downstream handlers (or
        # tests) can read the computed identity/limit.
        scope["_ratelimit"] = {"key": key, "limit": cap}
        await self.app(scope, receive, send)

    @staticmethod
    def _identity(scope: dict) -> str:
        # Prefer the resolved principal when auth has already populated the
        # scope; otherwise derive the identity from a Bearer token in the
        # Authorization header (the middleware runs before route dependencies,
        # so it parses the header itself). Falls back to the client address for
        # unauthenticated/local requests.
        principal = scope.get("_principal") or scope.get("principal")
        if principal:
            return f"p:{principal}"
        for name, value in scope.get("headers") or []:
            if name.lower() == b"authorization":
                text = value.decode("latin1", "replace")
                if text.lower().startswith("bearer "):
                    return f"p:{text[7:].strip()}"
        client = scope.get("client")
        if client and client[0]:
            return f"ip:{client[0]}"
        return "ip:unknown"

    def _configured_limit(self) -> int | None:
        if self.limit is not None:
            return int(self.limit)
        cfg = load_config()
        rl = (cfg.get("server", {}) or {}).get("rate_limit") or {}
        return int(rl.get("requests_per_minute", 0) or 0)

    async def _respond_429(self, send: Callable, retry: float, limit: int) -> None:
        retry_after = max(1, int(retry) + 1)
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(retry_after).encode()),
                    (b"ratelimit-limit", str(limit).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"detail":"rate limit exceeded"}',
            }
        )


__all__ = ["RateLimitMiddleware", "reset_rate_limit_state"]
