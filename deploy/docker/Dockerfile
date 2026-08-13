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
# Upgrade the pip build-toolchain that ships with the base image; Trivy flags
# older `wheel` (CVE-2026-24049) and `jaraco.context` (CVE-2026-23949) as HIGH.
# These are build/install-time only, but patching them in-image keeps the runtime
# image free of those toolchain vulnerabilities with zero behavioral change.
RUN python -m pip install --no-cache-dir --upgrade "jaraco.context>=6.1.0" "wheel>=0.46.2"

# ---- run stage ----
FROM base AS runtime
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Non-root operator by default (defense in depth).
RUN useradd --create-home --uid 10001 knovaryn
USER knovaryn

# Default: serve the REST API (offline demo + web console).
EXPOSE 8000
CMD ["knovaryn", "server", "--host", "0.0.0.0", "--port", "8000"]
