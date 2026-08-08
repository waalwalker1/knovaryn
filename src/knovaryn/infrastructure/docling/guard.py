"""Docling resource guard (spec §2.4, ADR 0003).

Prefer a public release/context-manager API; otherwise guarded feature
detection of a private unload; log which path was used; drop references and
invoke gc only after artifacts are persisted; never promise that gc alone
guarantees baseline memory. Worker recycling is a separate containment measure.
"""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("knovaryn.docling.guard")


@dataclass
class CleanupPath:
    name: str
    api_used: str


class DoclingResourceGuard:
    """Wraps a Docling result and releases its resources safely."""

    def __init__(self, result: Any) -> None:
        self.result = result
        self.cleanup_path: CleanupPath | None = None

    async def persist_and_release(self, persist: Any) -> CleanupPath:
        """Persist the artifact first, then release backing resources."""
        # 1. persist (serialize) the canonical output synchronously before release
        persisted = await persist(self.result)
        # 2. release resources
        path = self._release()
        self.cleanup_path = path
        # 3. drop references + gc only after persistence
        result_ref = self.result
        self.result = None
        del result_ref
        gc.collect()
        return path

    def _release(self) -> CleanupPath:
        r = self.result
        # Path A: public API — close/release context
        close = getattr(r, "close", None)
        if callable(close):
            try:
                close()
                return CleanupPath("public_close", "result.close()")
            except Exception:  # noqa: BLE001
                log.debug("public close() failed; continuing")
        # Path B: input backend unload via feature detection (guarded, private)
        backend = getattr(r, "input", None)
        unload = getattr(backend, "unload", None) or getattr(getattr(r, "input", None), "_backend", lambda: None)
        target = getattr(r, "input", None)
        backend_attr = getattr(target, "_backend", None)
        alloc = getattr(backend_attr, "unload", None)
        if callable(alloc):
            try:
                alloc()
                return CleanupPath("feature_detected_unload", "input._backend.unload()")
            except Exception:  # noqa: BLE001
                log.debug("feature-detected unload failed")
        return CleanupPath("dropped_references", "drop+gc")
