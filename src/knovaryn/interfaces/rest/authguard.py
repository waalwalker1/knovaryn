"""Shared bearer dependency for the REST layer (WP J3).

Provides the single :class:`HTTPBearer` (auto_error=False) used by both the
auth-guard routers and the scope-gated dependencies, so identity resolution is
defined once and reused.
"""

from __future__ import annotations

from fastapi.security import HTTPBearer

bearer_credentials = HTTPBearer(auto_error=False)

__all__ = ["bearer_credentials"]
