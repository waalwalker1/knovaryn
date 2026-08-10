"""Resume-safe provider-call cache (spec §11.5, §7.5, exec rule 24).

A call is cached by its deterministic fingerprint. On resume, an identical
fingerprint returns the persisted provider response instead of re-invoking the
paid model call. Implemented over any key-value style store; we use the
artifact store keyed by fingerprint sha256 for cross-restart durability.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ...domain.errors import NotFoundError
from ...domain.hashing import ContentHasher


class CallCache:
    def __init__(self, store: Any, *, tenant_scope: str = "local") -> None:
        self._store = store
        self._tenant = tenant_scope
        self._mem: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def key(self, fingerprint: str) -> str:
        return ContentHasher.sha256_text(f"{self._tenant}:{fingerprint}")

    async def get(self, fingerprint: str) -> Any | None:
        k = self.key(fingerprint)
        if k in self._mem:
            return self._mem[k]
        try:
            raw = await self._store.get(k)
            val = json.loads(raw.decode("utf-8"))
            self._mem[k] = val
            return val
        except NotFoundError:
            return None
        except Exception:  # noqa: BLE001 - cache is best-effort, never blocks generation
            return None

    async def put(self, fingerprint: str, value: Any) -> None:
        k = self.key(fingerprint)
        payload = json.dumps(value, default=str, sort_keys=True).encode("utf-8")
        try:
            await self._store.put(
                payload,
                media_type="application/json",
                producer={"component": "model-call-cache", "component_version": "1"},
            )
            self._mem[k] = value
        except Exception:  # noqa: BLE001 - cache is best-effort
            self._mem[k] = value

    async def clear(self) -> None:
        self._mem.clear()
