"""Configuration model (spec §20).

Precedence (high→low): admin policy > request > project > user > env > defaults.
Project config cannot weaken admin-enforced security/retention policy.

Configuration is immutable once resolved; values are exposed with provenance
via ``value_provenance()`` so the CLI can print where each value came from.
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from ..identity import ENV_PREFIX
from .errors import ConfigurationError

_SCHEMA_VERSION = "1.0"

_ENV_VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")

_OFFICIAL_PROFILES = {
    "offline-demo",
    "fast-local",
    "balanced",
    "high-quality",
    "air-gapped",
    "enterprise",
    "deepseek_flash_budget",
    # WP D4 runtime profile names (vendor-neutral; DeepSeek not the product)
    "fake",
    "deepseek-budget",
    "local-openai-compatible",
    "anthropic-quality",
    "openai-quality",
    "gemini-quality",
    "custom-litellm",
}
_ADMIN_PROTECTED_KEYS = {
    "sources.url_ingestion",
    "storage.database_url",
    "spy",
}


def _resolve_env(value: Any) -> Any:
    """Resolve ``${ENV}`` placeholders in strings from the environment."""
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            name = m.group(1)
            return os.environ.get(name, m.group(0))

        return _ENV_VAR_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


_DEFAULTS: dict[str, Any] = {
    "schema_version": _SCHEMA_VERSION,
    "project": {"name": "Knovaryn Project", "description": ""},
    "profile": "balanced",
    "sources": {
        "allowed_roots": ["./data/input"],
        "url_ingestion": False,
        "max_file_mb": 200,
        "max_pages": 1500,
        "follow_symlinks": False,
    },
    "storage": {
        "database_url": "sqlite+aiosqlite:///./.knovaryn/knovaryn.db",
        "artifact_backend": "local",
        "artifact_root": "./.knovaryn/artifacts",
    },
    "parsing": {
        "engine": "docling",
        "ocr_mode": "auto",
        "ocr_engine": "auto",
        "accelerator": "auto",
        "threads": "auto",
        "retain_page_images": "sampled",
        "worker_recycle_documents": 25,
    },
    "chunking": {
        "engine": "structure_aware",
        "target_tokens": 900,
        "min_tokens": 180,
        "max_tokens": 1400,
        "neighbor_context_tokens": 350,
        "keep_tables_together": True,
        "keep_lists_together": True,
    },
    "planning": {
        "topologies": ["sft", "preference", "evaluation"],
        "task_families": {
            "factual_explanation": 0.25,
            "procedure": 0.20,
            "troubleshooting": 0.20,
            "comparison": 0.15,
            "extraction": 0.10,
            "unanswerable": 0.10,
        },
        "difficulty": {"basic": 0.25, "intermediate": 0.50, "advanced": 0.25},
        "target_examples": 2000,
        "split": {
            "strategy": "grouped_random",
            "train": 0.80,
            "validation": 0.10,
            "test": 0.10,
            "seed": 42,
        },
    },
    "models": {
        "profile": "balanced",
        "provider_base_url": "${KNOVARYN_DEEPSEEK_BASE_URL}",
        "generator": {
            "model": "${KNOVARYN_GENERATOR_MODEL}",
            "temperature": 0.3,
            "max_output_tokens": 2400,
        },
        "critic": {"model": "${KNOVARYN_CRITIC_MODEL}", "temperature": 0.0},
        "verifier": {"model": "${KNOVARYN_VERIFIER_MODEL}", "temperature": 0.0},
        "embedding": {"model": "${KNOVARYN_EMBEDDING_MODEL}"},
    },
    "quality": {
        "policy": "balanced-v1",
        "minimum_overall": 0.82,
        "minimum_grounding": 0.90,
        "require_evidence": True,
        "judge_disagreement": "review",
        "human_review_sample": 0.05,
        # defect 3.8: explicit semantic validation profile.
        #   offline-fast      — deterministic checks only, no network
        #   certified-semantic — deterministic first, cited-evidence-only
        #                        model judge second (requires a live provider)
        "semantic_profile": "offline-fast",
    },
    "preference": {
        "negative_strategy": "edit_chosen_near_miss",
        "length_ratio_min": 0.80,
        "length_ratio_max": 1.25,
        "detect_superficial_artifacts": True,
        # defect 3.9: "heuristic" (deterministic checks only, default) or
        # "certified-pairwise" (adds the two-order evidence-cited judge;
        # requires a live provider; judge can demote but never upgrade).
        "profile": "heuristic",
    },
    "privacy": {
        "provider_data_allowed": True,
        "store_raw_prompts": True,
        "detect_pii": True,
        "high_confidence_pii_action": "quarantine",
        "retention_days": 90,
    },
    "licensing": {
        "unknown_license_action": "review",
        "public_export_requires_approved_sources": True,
    },
    "budget": {
        "maximum_cost_usd": 50.0,
        "maximum_calls": 10000,
        "maximum_examples": 2500,
    },
    "exports": {
        "formats": ["canonical-jsonl", "parquet", "trl-conversational", "llamafactory-sharegpt"],
        "include_private_audit_metadata": False,
    },
    "telemetry": {
        "content_in_logs": False,
        "opentelemetry": False,
        "metrics": True,
    },
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "api_token": "",  # empty = local mode (REST offline demo); set to enforce auth
        # WP J3 / defect 4.10: granted scopes for a configured token. OMIT the
        # key for the safe default remote set (everything except the publish
        # and admin bypass scopes). An explicit list is validated against the
        # canonical registry and grants exactly that set — an empty list means
        # NO privileges. Unknown names are a configuration error (fail closed).
        # principals exempt from owner-tenant isolation (cross-tenant admin)
        "admin_principals": [],
        # J4: refuse non-loopback bind without a token unless explicitly true
        "allow_insecure_nonloopback": False,
        # J5: strict-Transport / CSP are emitted by middleware; CORS origins
        "cors_origins": [],
        # J7: per-principal rate limits
        "rate_limit": {
            "requests_per_minute": 600,
            "max_upload_bytes": 25 * 1024 * 1024,
            "max_concurrent_jobs": 4,
            "max_provider_calls_per_run": 0,  # 0 = unlimited
            "max_publish_attempts_per_hour": 10,
        },
    },
}


@dataclass
class Configuration:
    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(_DEFAULTS))
    provenance: dict[str, str] = field(default_factory=dict)
    sources_applied: list[str] = field(default_factory=list)

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set(self, dotted: str, value: Any, provenance: str = "programmatic") -> None:
        parts = dotted.split(".")
        cur: Any = self.data
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        if not isinstance(cur, dict):
            raise ConfigurationError(f"cannot set {dotted}: parent is not a mapping")
        cur[parts[-1]] = value
        self.provenance[dotted] = provenance

    def value_provenance(self, dotted: str) -> str | None:
        return self.provenance.get(dotted)

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)


def _parse_yaml(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except OSError as exc:  # pragma: no cover - IO
        raise ConfigurationError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(f"config root in {path} must be a mapping")
    return raw


def load_config(
    *,
    paths: list[str] | None = None,
    env_prefix: str = ENV_PREFIX,
    admin_overrides: dict[str, Any] | None = None,
    project_overrides: dict[str, Any] | None = None,
    request_overrides: dict[str, Any] | None = None,
) -> Configuration:
    cfg = Configuration()
    applied: list[tuple[str, str]] = []  # (label, provenance)

    # 1. defaults
    # 2. user config / project config files (in order)
    for path in paths or []:
        raw = _parse_yaml(path)
        raw = _resolve_env(raw)
        cfg.data = _deep_merge(cfg.data, raw)
        applied.append(("file", path))

    # 3. admin policy (highest; cannot be weakened by project)
    if admin_overrides:
        flat = _flatten(admin_overrides)
        for k in _ADMIN_PROTECTED_KEYS:
            flat.pop(k, None)
        cfg.data = _deep_merge(cfg.data, admin_overrides)
        cfg.provenance.update({f"admin:{k}": "admin" for k in flat})
        applied.append(("admin", "policy"))

    # 4. environment variables (lower than admin, higher than files)
    env_map = _collect_env(env_prefix, cfg.data)
    if env_map:
        cfg.data = _deep_merge(cfg.data, env_map)
        cfg.provenance.update({f"env:{k}": "env" for k in env_map})
        applied.append(("env", env_prefix))

    # 5. request overrides within allowed bounds
    if request_overrides:
        cfg.data = _deep_merge(cfg.data, request_overrides)
        applied.append(("request", "request"))

    cfg.sources_applied = [label for label, _ in applied]
    _validate(cfg)
    return cfg


# Flat aliases for operator-facing variables whose natural name does not
# round-trip through underscore-splitting: the token's section (``server``) is
# implied by the variable name, and the S3/MinIO keys are FLAT ``storage.*``
# leaves (``build_artifact_store`` reads them directly off the storage dict)
# whose names contain underscores. Defect 4.11: KNOVARYN_API_TOKEN used to
# resolve to a nonexistent ``api.token`` path, and KNOVARYN_STORAGE_ENDPOINT_URL
# to ``storage.endpoint.url`` — a container started with the documented
# variables still refused to bind / could not reach its artifact store.
_ENV_ALIASES = {
    "API_TOKEN": "server.api_token",
    "STORAGE_BUCKET": "storage.bucket",
    "STORAGE_ENDPOINT_URL": "storage.endpoint_url",
    "STORAGE_REGION": "storage.region",
    "STORAGE_ACCESS_KEY_ID": "storage.access_key_id",
    "STORAGE_SECRET_ACCESS_KEY": "storage.secret_access_key",
}


def _env_path_for(tree: dict[str, Any], parts: list[str]) -> list[str]:
    """Resolve env-name ``parts`` to a concrete config path (no mutation).

    Compound leaf keys (``storage.database_url`` from
    ``KNOVARYN_STORAGE_DATABASE_URL``) cannot be recovered by naive
    underscore-splitting, so at each level the LONGEST joined remainder that
    names an existing key in the current tree wins; genuinely new paths fall
    back to plain per-part nesting.
    """
    path: list[str] = []
    cur: dict[str, Any] = tree
    i = 0
    while i < len(parts):
        remainder = parts[i:]
        for j in range(len(remainder), 0, -1):
            candidate = "_".join(remainder[:j])
            if candidate not in cur:
                continue
            if j == len(remainder):
                path.append(candidate)
                return path
            if isinstance(cur[candidate], dict):
                path.append(candidate)
                cur = cur[candidate]
                i += j
                break
        else:
            # no existing key matches any join: nest the rest per-part
            path.extend(remainder)
            return path
    return path


def _coerce_env_scalar(val: str) -> Any:
    """Booleans arrive as strings via env; coerce the two spellings only.

    Numbers stay strings on purpose (a numeric API token must not silently
    become an int); callers already coerce numerics where they consume them.
    """
    lowered = val.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return val


def _collect_env(prefix: str, current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collect ``KNOVARYN_*`` variables as a nested config fragment.

    ``current`` (the merged defaults+files+admin tree) guides compound-key
    resolution so documented variables land on real config leaves.
    """
    out: dict[str, Any] = {}
    for key, val in os.environ.items():
        if not key.startswith(prefix):
            continue
        rel = key[len(prefix) :]
        alias = _ENV_ALIASES.get(rel.upper())
        parts = alias.split(".") if alias else _env_path_for(current or {}, rel.lower().split("_"))
        frag: Any = _coerce_env_scalar(val)
        for p in reversed(parts):
            frag = {p: frag}
        assert isinstance(frag, dict)
        out = _deep_merge(out, frag)
    return out


def _validate(cfg: Configuration) -> None:
    profile = cfg.get("profile")
    if profile not in _OFFICIAL_PROFILES:
        # allow custom but warn-level; still valid
        pass
    if cfg.get("telemetry.content_in_logs") is True:
        # allowed but noted
        pass
    # Defect 4.10 (fail closed): an unknown scope name is a configuration
    # error, never a silent filter. v0.1 dropped unknown names and granted the
    # full default set when nothing valid remained — a typo escalated to
    # admin. The canonical registry is the spec §23.2 ResourceScope vocabulary
    # plus the cross-tenant bypass scope.
    from ..identity import VALID_SCOPE_NAMES as _VALID_SCOPE_NAMES

    scopes = cfg.get("server", {}).get("scopes") if isinstance(cfg.get("server"), dict) else None
    if scopes is not None:
        unknown = sorted({str(s) for s in scopes} - _VALID_SCOPE_NAMES)
        if unknown:
            raise ConfigurationError(
                f"unknown scope names in server.scopes: {unknown}; "
                f"valid scopes: {sorted(_VALID_SCOPE_NAMES)}"
            )
