"""Content hashing (spec §6.3/6.4).

Stable, normalized hashing for content addresses, model-call fingerprints,
chunk identity, and example content hashes. Normalization keeps hashes stable
across runs so jobs can resume without duplicating paid calls.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


class ContentHasher:
    """Deterministic, normalized hashing helpers."""

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def cfg_hash(data: Any) -> str:
        """Stable hash of a configuration/JSON structure (sorted keys)."""
        normalized = json.dumps(data, sort_keys=True, separators=(",", ":"), default=_default_json)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _default_json(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "__dict__"):
        return vars(obj)
    return str(obj)


_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_text(text: str) -> str:
    """Normalize for stable comparison: NFC, casefold, collapse whitespace."""
    text = unicodedata.normalize("NFC", text)
    text = text.casefold()
    text = _WS_RE.sub(" ", text).strip()
    return text


def normalize_hash(text: str) -> str:
    """Hash of normalized text (for exact/near-exact duplicate detection)."""
    return ContentHasher.sha256_text(normalize_text(text))


def content_hash_for_messages(messages: list[dict[str, Any]]) -> str:
    return ContentHasher.cfg_hash(messages)


def fingerprint(
    *,
    messages: list[dict[str, Any]],
    prompt_template_version: str | None,
    model: str,
    sampling: dict[str, Any],
    schema_hash: str | None,
    source_hashes: list[str],
) -> str:
    """Model-call fingerprint (spec §11.5): hash of everything that determines
    a provider response, so a resumed job does not repay for an accepted call.
    """
    canonical = {
        "messages": messages,
        "pt": prompt_template_version,
        "model": model,
        "sampling": sampling,
        "schema": schema_hash,
        "sources": sorted(source_hashes),
    }
    return ContentHasher.cfg_hash(canonical)
