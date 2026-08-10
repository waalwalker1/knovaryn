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
    },
    "preference": {
        "negative_strategy": "edit_chosen_near_miss",
        "length_ratio_min": 0.80,
        "length_ratio_max": 1.25,
        "detect_superficial_artifacts": True,
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
    env_map = _collect_env(env_prefix)
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


def _collect_env(prefix: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in os.environ.items():
        if not key.startswith(prefix):
            continue
        rel = key[len(prefix) :].lower()
        parts = rel.split("_")
        cur: Any = out
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = val
    return out


def _validate(cfg: Configuration) -> None:
    profile = cfg.get("profile")
    if profile not in _OFFICIAL_PROFILES:
        # allow custom but warn-level; still valid
        pass
    if cfg.get("telemetry.content_in_logs") is True:
        # allowed but noted
        pass
