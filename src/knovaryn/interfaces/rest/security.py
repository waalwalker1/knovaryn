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
from ...identity import ADMIN_SCOPE, VALID_SCOPE_NAMES, ResourceScope
from ...infrastructure.auth.bearer import authorize
from .authguard import bearer_credentials  # re-exported dependency

# ---------------------------------------------------------------- scopes
# Canonical vocabulary (spec §23.2 ``ResourceScope``) — the same names the
# config validator enforces, so operator configuration has exactly one
# vocabulary. ``admin`` is the cross-tenant bypass scope (defect 4.10).
SCOPE: dict[str, str] = {
    ResourceScope.PROJECTS_READ.value: "read workspace + project metadata",
    ResourceScope.PROJECTS_WRITE.value: "create / modify projects",
    ResourceScope.SOURCES_READ.value: "list / read sources",
    ResourceScope.SOURCES_WRITE.value: "add / manage sources",
    ResourceScope.RUNS_EXECUTE.value: "start / run / cancel pipeline jobs",
    ResourceScope.RUNS_READ.value: "read job status and events",
    ResourceScope.REVIEW_WRITE.value: "apply review decisions",
    ResourceScope.DATASETS_READ.value: "read dataset versions",
    ResourceScope.DATASETS_WRITE.value: "create dataset versions",
    ResourceScope.DATASETS_EXPORT.value: "validate / version / export datasets",
    ResourceScope.DATASETS_PUBLISH.value: "publish datasets (requires explicit confirm)",
    ADMIN_SCOPE: "bypass ownership for cross-tenant admin operations",
}

# Full surface — the loopback operator principal (``local``/``system``), which
# is the person running the process. Includes publish and the admin bypass.
DEFAULT_GRANTED_SCOPES = frozenset(VALID_SCOPE_NAMES)

# Default remote surface — a configured token whose ``server.scopes`` key is
# omitted gets everything EXCEPT ``datasets:publish`` and the ``admin``
# bypass (defect 4.10: a leaked remote token must not be a full-admin
# credential; both are explicit opt-in).
DEFAULT_TOKEN_SCOPES = frozenset(DEFAULT_GRANTED_SCOPES) - {
    ResourceScope.DATASETS_PUBLISH.value,
    ADMIN_SCOPE,
}


@dataclass
class Principal:
    """The authenticated identity for a request plus its granted scopes."""

    name: str
    scopes: set[str] = field(default_factory=set)


def _configured_scopes(name: str) -> set[str]:
    """Resolve the principal's granted scopes from config.

    ``local``/``system`` (no token configured — loopback trust boundary) get
    the full surface. A configured token gets the explicitly configured set —
    or the safe remote default when the key is omitted. Unknown scope names
    are a :class:`ConfigurationError` (fail closed): v0.1 silently filtered
    them and granted the full set when nothing valid remained, so a typo
    escalated to admin.
    """
    if name in ("local", "system"):
        return set(DEFAULT_GRANTED_SCOPES)
    cfg = load_config()
    server = cfg.get("server", {}) if isinstance(cfg.get("server"), dict) else {}
    configured = server.get("scopes")
    if configured is None:
        return set(DEFAULT_TOKEN_SCOPES)
    requested = {str(s) for s in configured}
    unknown = sorted(requested - VALID_SCOPE_NAMES)
    if unknown:
        raise ConfigurationError(
            f"unknown scope names in server.scopes: {unknown}; "
            f"valid scopes: {sorted(VALID_SCOPE_NAMES)}"
        )
    return requested  # explicit empty list = no privileges (least privilege)


def resolve_principal(token: str | None) -> Principal:
    """Turn a raw bearer token (or None) into an authenticated :class:`Principal`.

    Mirrors :func:`authorize`'s fail-closed logic; raises ``AuthorizationError``
    on a mismatch.
    """
    name = authorize(token)
    return Principal(name=name, scopes=_configured_scopes(name))


def require_scope(scope: str) -> Callable[..., Principal]:
    """FastAPI dependency factory: return the :class:`Principal` if it holds ``scope``.

    Usage: ``principal: Principal = Depends(require_scope("projects:read"))``.
    Unknown/denied scopes produce ``403`` (never a silent pass — rule 6).
    """

    def _dep(
        creds: HTTPAuthorizationCredentials | None = Depends(bearer_credentials),
    ) -> Principal:
        raw = creds.credentials if creds is not None else None
        try:
            principal = resolve_principal(raw)
        except ConfigurationError as exc:
            # A misconfigured scope registry is a server fault, not an
            # authentication failure (defect 4.10: never launder it into 401).
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            ) from exc
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
