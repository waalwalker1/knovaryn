"""Web-security hardening: secure headers, CORS, body limits, error redaction
(spec §17.4, WP J5).

* A per-response ``SecurityHeadersMiddleware`` emits CSP / X-Content-Type-Options
  / X-Frame-Options / Referrer-Policy / Permissions-Policy and, for loopback
  HTTPS/behind-TLS cases, HSTS is left to the reverse proxy (never asserted
  blindly over plain HTTP).
* CORS is restricted to an explicit allowlist (no ``*`` reflection), and
  credentials are never echoed for arbitrary origins.
* Request bodies are capped so an oversized upload fails early (413).
* Unhandled errors are redacted to a generic message — never the traceback or
  secrets (rule 13 / no secrets in error responses).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from ...domain.config import load_config

# Content-Security-Policy: conservative. The web console is a single self-hosted
# page with inline JS, so we allow 'unsafe-inline' scripts only for nonce-less
# console; everything else is default-deny, and no remote origins are permitted.
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware:
    """ASGI middleware that attaches security headers to every response."""

    def __init__(self, app: Any, *, csp: str | None = None, hsts: bool = False) -> None:
        self.app = app
        self.csp = csp or _DEFAULT_CSP
        self.hsts = hsts  # only meaningful behind TLS; leave False for plain HTTP

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                add = {
                    b"content-security-policy": self.csp.encode("utf-8"),
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"same-origin",
                    b"permissions-policy": (
                        b"camera=(), microphone=(), geolocation=(), interest-cohort=()"
                    ),
                }
                if self.hsts:
                    add[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                existing = {h[0].lower() for h in headers}
                for name, value in add.items():
                    if name not in existing:
                        headers.append((name, value))
            await send(message)

        await self.app(scope, receive, send_wrapper)


def restrict_cors(app: Any, *, allowed_origins: list[str] | None) -> None:
    """Attach a strict CORS policy to ``app`` (config allowlist, no wildcard).

    Applies the middleware in place; never reflects an arbitrary ``Origin``.
    Without an allowlist we deny all cross-origin reads (the conservative
    default), which is the safe behavior for a local-first control plane.
    """
    from fastapi.middleware.cors import CORSMiddleware

    origins = [o for o in (allowed_origins or []) if o and o != "*"]
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,  # bearer tokens are sent explicitly, never cookies
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )


def _request_body_size(scope: dict) -> int | None:
    """Max request/body size in bytes from config (J7 also caps uploads)."""
    cfg = load_config()
    return int((cfg.get("server", {}).get("rate_limit") or {}).get("max_upload_bytes", 0) or 0)


class _PayloadTooLarge(Exception):
    """Internal signal: the request body exceeded the configured cap (413)."""


class BodyLimitMiddleware:
    """Reject request bodies larger than the configured cap (413).

    If the client declares a ``Content-Length`` above the cap we reject up front;
    otherwise we count streaming chunks and raise :class:`_PayloadTooLarge` the
    moment the cap is crossed. The exception is caught before the app writes a
    response head, so an oversized body never reaches the service layer (J5/J7).
    """

    def __init__(self, app: Any, *, max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(
        self, scope: dict, receive: Callable[[], Awaitable[dict]], send: Callable
    ) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        cap = self.max_bytes
        if cap is None:
            cap = _request_body_size(scope)
        if cap is None or cap <= 0:
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])
        }
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > cap:
            await self._respond_413(send)

        total = 0
        original_receive = receive
        responded = False

        async def limited_receive() -> dict:
            nonlocal total, responded
            message = await original_receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > cap:
                    responded = True
                    raise _PayloadTooLarge()
            return message

        async def send_wrapper(message: dict) -> None:
            if not responded:
                await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except _PayloadTooLarge:
            # The app was reading the body and no response head was sent yet;
            # emit a clean 413.
            await self._respond_413(send)

    async def _respond_413(self, send: Callable) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"detail":"payload too large"}'})


async def redacted_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a generic 500 — never the traceback or internal paths (J5)."""
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


__all__ = [
    "SecurityHeadersMiddleware",
    "BodyLimitMiddleware",
    "restrict_cors",
    "redacted_exception_handler",
    "_DEFAULT_CSP",
]
