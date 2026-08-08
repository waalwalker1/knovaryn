.PHONY: install dev install-all lint format type test test-fast test-cov docs build quickstart demo doctor check clean

# ---- Setup ---------------------------------------------------------------
install:
	uv sync --dev

install-all:
	uv sync --all-extras --dev

dev:
	uv run pre-commit install

# ---- Quality -------------------------------------------------------------
lint:
	uv run ruff check src tests

format:
	uv run ruff format --check src tests

fmt:
	uv run ruff format src tests

type:
	uv run mypy src/knovaryn

test:
	uv run pytest -m "not live" -q

test-fast:
	uv run pytest -m "not live and not docling and not docetl and not s3" -q

test-cov:
	uv run pytest -m "not live" --cov=knovaryn --cov-report=term-missing

# ---- Packaging & docs ----------------------------------------------------
build:
	uv build

docs-serve:
	uv run mkdocs serve

docs-build:
	uv run mkdocs build

# ---- Demo / ops ----------------------------------------------------------
demo:
	uv run knovaryn demo --offline

doctor:
	uv run knovaryn doctor

quickstart:
	uv run knovaryn demo --offline --clear

check: lint format type test docs-build build

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache htmlcov site
