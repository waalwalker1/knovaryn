"""Canonical product identity (spec §3.5).

All machine-facing identifiers live here so the whole project can be renamed
through one documented manifest. Never hard-code these strings elsewhere in
product code; import from this module. The repository-wide migration test
rejects stale ``OmniTrain``/``omnitrain``/``OMNITRAIN`` identifiers in public
product surfaces.
"""

from __future__ import annotations

from enum import StrEnum

# --- Brand ---
DISPLAY_NAME = "Knovaryn"

# --- Machine identifiers (spec §3.5 table) ---
REPOSITORY = "knovaryn"
PACKAGE = "knovaryn"
CLI_NAME = "knovaryn"
MCP_SERVER_ID = "knovaryn_mcp"
URI_SCHEME = "knovaryn"
ENV_PREFIX = "KNOVARYN_"
STATE_DIR = ".knovaryn"
DEFAULT_CONFIG = "knovaryn.yaml"
CONTAINER_STEM = "knovaryn"

# --- Local state / binding constants ---
HTTP_BIND_DEFAULT = "127.0.0.1"
HTTP_PORT_DEFAULT = 8765
SQLITE_FILENAME = "knovaryn.db"
ARTIFACT_DIR = "artifacts"

# --- Legacy identifiers that must NOT appear in public product surfaces ---
# Listed so the naming test can prove clearance (spec §40). Kept in history/docs only.
LEGACY_IDENTIFIERS = ("OmniTrain", "omnitrain", "OMNITRAIN")


class ResourceScope(StrEnum):
    """Least-privilege OAuth-style scopes (spec §23.2)."""

    PROJECTS_READ = "projects:read"
    PROJECTS_WRITE = "projects:write"
    SOURCES_READ = "sources:read"
    SOURCES_WRITE = "sources:write"
    RUNS_EXECUTE = "runs:execute"
    RUNS_READ = "runs:read"
    REVIEW_WRITE = "review:write"
    DATASETS_READ = "datasets:read"
    DATASETS_WRITE = "datasets:write"
    DATASETS_EXPORT = "datasets:export"
    DATASETS_PUBLISH = "datasets:publish"


# The canonical registry every scope configuration is validated against
# (defect 4.10): ``admin`` is the cross-tenant bypass scope, deliberately
# outside the §23.2 resource vocabulary and never granted by default to a
# remote token.
ADMIN_SCOPE = "admin"
VALID_SCOPE_NAMES = frozenset({s.value for s in ResourceScope} | {ADMIN_SCOPE})


def resource_urn(project_id: str, path: str) -> str:
    """Build a ``knovaryn://`` resource URI."""
    return f"{URI_SCHEME}://projects/{project_id}/{path}"
