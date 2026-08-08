#!/usr/bin/env bash
# scripts/ci.sh — local CI-equivalence runner.
# Mirrors the gate run by .github/workflows/ci.yml so contributors can
# reproduce CI locally without pushing. See CONTRIBUTING.md and the Makefile
# `check` target for the canonical gate.
#
# NOTE: reconstructed after the OneDrive outage dehydrated the original.
# Reconcile against the cloud copy once it re-hydrates.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> ruff lint"
uv run ruff check src tests

echo "==> ruff format check"
uv run ruff format --check src tests

echo "==> mypy"
uv run mypy src

echo "==> tests (offline)"
uv run pytest -m "not live" -q -p no:cacheprovider

echo "==> docs build"
uv run mkdocs build

echo "==> package build"
uv build

echo "OK: local CI gate passed"
