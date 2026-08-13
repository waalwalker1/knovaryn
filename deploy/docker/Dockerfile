# syntax=docker/dockerfile:1
# Knovaryn — training-data foundry container (spec §29).
# Minimal image: runtime deps only (no docling/parquet extras by default; the
# offline fake-provider demo and REST/MCP interfaces run without heavy extras).
# Tag a different base or add `--extras docling` for full parsing.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    KNOVARYN_HOME=/opt/knovaryn

WORKDIR /opt/knovaryn

# ---- build stage: install the wheel with uv ----
FROM base AS builder
RUN pip install --no-cache-dir "uv>=0.4"
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv pip install --system --no-cache --lockfile uv.lock . \
    || uv pip install --system --no-cache .

# ---- run stage ----
FROM base AS runtime
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Strip the pip build/install toolchain packages that Trivy flags as HIGH in the
# base image (wheel CVE-2026-24049, jaraco.context CVE-2026-23949). The runtime
# only executes the pre-built `knovaryn` console script and never installs
# packages; these are build-time-only. Remove the files directly rather than via
# `pip uninstall` because setuptools (kept, not flagged) declares jaraco.context
# as a dependency, which would block a dependency-aware uninstall.
RUN rm -rf \
      /usr/local/lib/python3.11/site-packages/wheel \
      /usr/local/lib/python3.11/site-packages/wheel-*.dist-info \
      /usr/local/lib/python3.11/site-packages/jaraco \
      /usr/local/lib/python3.11/site-packages/jaraco_context-*.dist-info

# Non-root operator by default (defense in depth).
RUN useradd --create-home --uid 10001 knovaryn
USER knovaryn

# Default: serve the REST API (offline demo + web console).
EXPOSE 8000
CMD ["knovaryn", "server", "--host", "0.0.0.0", "--port", "8000"]
