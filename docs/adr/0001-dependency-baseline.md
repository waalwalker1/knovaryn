# ADR 0001 — Dependency baseline and environment strategy

- **Date:** 2026-08-07
- **Status:** Accepted

## Context

Knovaryn must be an open, local-first, provider-agnostic tool where the offline
demo and full test suite run with **no paid credentials and no heavy ML model
downloads**. Dependencies change fast (MCP/FastMCP, Docling, DocETL, LiteLLM),
so choices must be recorded and isolated.

## Decision

1. **Lean core dependency set** (installed by default): Pydantic v2, YAML, Typer,
   Rich, FastAPI/Uvicorn, SQLAlchemy 2 async, Alembic, aiosqlite, httpx, structlog,
   uuid6, plus dev tooling (pytest, hypothesis, ruff, mypy, mkdocs, pre-commit).
2. **Heavy/opt-in extras** (`docling`, `docetl`, `litellm`, `s3`, `parquet`,
   `hub`, `ml`) are declared in `pyproject.toml` but NOT installed by the default
   `uv sync --dev`. Adapters behind these extras degrade gracefully with an
   explicit, documented guard when the extra is absent — never a silent no-op.
3. **Why this is safe:** spec §0.2 permits safe fallbacks when an upstream
   capability is unavailable, and §2.6 makes DocETL optional. The deterministic
   fake provider is the documented default for CI/offline demo (§11.2, exec rule 2).
4. The versioned prompt library, job engine, intake, validation, exports,
   REST/MCP/CLI, and web console all run on the lean core.

## Consequence

`uv sync --all-extras --dev` remains the documented contribution recipe for users
who want Docling/DocETL; for this build's CI/offline-demo path we use
`uv sync --dev` so the environment is small, fast, and cloud-sync friendly.
Additional ADRs record FastMCP (0002), Docling guard (0003), DocETL (0004),
LiteLLM (0005), and storage (0006).
