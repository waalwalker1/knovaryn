"""Bearer-token authentication guard (spec §23.2, §23.4).

A minimal, dependency-free guard that fails **closed**: when an API token is
configured, requests without the matching bearer token are rejected; when no
token is configured the guard reports ``"local"`` so the offline REST demo works
without setup, but publish-style operations remain gated at the service layer
(defense in depth).
"""

from __future__ import annotations

from typing import Any

from ...domain.config import load_config
from ...domain.errors import AuthorizationError
from .handles import constant_time_equal


def expected_token() -> str:
    """The configured server API token, or ``""`` when auth is disabled (local mode)."""
    cfg = load_config()
    return str(cfg.get("server", {}).get("api_token") or "")


def authorize(provided: str | None) -> str:
    """Return the effective principal if ``provided`` satisfies the guard.

    Raises :class:`AuthorizationError` when a token is configured but the
    provided credential does not match. Returns ``"local"`` when no token is
    configured (operator opted out of auth for offline operation).
    """
    expected = expected_token()
    if not expected:
        return "local"
    if provided is None or not constant_time_equal(provided, expected):
        raise AuthorizationError("invalid or missing bearer token")
    return "token"


def principal_from_header(authorization: str | None) -> str:
    """Extract a bearer token from an ``Authorization`` header value.

    Accepts ``"Bearer <token>"`` (case-insensitive) and returns ``None`` for a
    missing header so the guard can apply its configured policy.
    """
    if not authorization:
        return ""
    scheme, _, rest = authorization.partition(" ")
    if scheme.strip().lower() != "bearer":
        return ""
    return rest.strip()


def server_bind() -> tuple[str, int]:
    """Return (host, port) from config for the REST server command."""
    cfg = load_config()
    return str(cfg.get("server", {}).get("host") or "127.0.0.1"), int(
        cfg.get("server", {}).get("port") or 8000
    )


def redact_token_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return config for display with the API token redacted (never echo secrets)."""
    out = dict(data)
    server = dict(out.get("server", {}))
    if "api_token" in server and server["api_token"]:
        server["api_token"] = "••••"
    out["server"] = server
    return out


__all__ = [
    "authorize",
    "expected_token",
    "principal_from_header",
    "server_bind",
    "redact_token_dict",
]
