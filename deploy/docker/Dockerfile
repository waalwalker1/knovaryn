# syntax=docker/dockerfile:1
# Knovaryn — training-data foundry container (spec §29).
# Minimal image: runtime deps only (no docling/parquet extras by default; the
# offline fake-provider demo and REST/MCP interfaces run without heavy extras).
# Tag a different base or add `--extras docling` for full parsing.

FROM python:3.11-slim AS base

# OCI labels (defect 3.5): version is kept in lockstep with
# knovaryn.__version__ by scripts/check_version_sync.py.
LABEL org.opencontainers.image.title="Knovaryn" \
      org.opencontainers.image.version="0.2.1" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/waalwalker1/knovaryn"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    KNOVARYN_HOME=/opt/knovaryn

WORKDIR /opt/knovaryn

# ---- build stage: install locked deps (with runtime extras) via uv ----
FROM base AS builder
RUN pip install --no-cache-dir "uv>=0.4"
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# Locked install INCLUDING the extras the shipped compose topology needs:
# s3 (aioboto3 artifact store), parquet (exports), mcp (MCP server entry).
# `uv export --frozen` projects the lockfile resolution (extras included)
# into a requirements file; installing THAT keeps every pin from uv.lock.
# (An earlier attempt used a nonexistent `--lockfile` flag and silently fell
# back to an UNLOCKED `pip install .`, defeating the pinning promised here;
# the compose E2E then caught the missing s3 extra as a 400 on upload.)
RUN uv export --frozen --no-dev \
        --extra s3 --extra parquet --extra mcp \
        -o /tmp/requirements.lock \
    && uv pip install --system --no-cache -r /tmp/requirements.lock \
    && uv pip install --system --no-cache --no-deps .

# ---- run stage ----
FROM base AS runtime
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Patch OS packages the slim base ships vulnerable. First caught in CI: the
# util-linux family baked into python:3.11-slim (2.41-5, debian 13.6) carried
# 36 HIGH findings from one disclosure cluster (CVE-2026-53612..53615 — TOCTOU
# in mount(8), SUID bypass, integer overflow in libblkid), fixed upstream in
# 2.41.5-0+deb13u1. Upgrade ALL installed OS packages rather than pinning the
# currently-flagged family: the Trivy gate (--severity CRITICAL,HIGH
# --ignore-unfixed), not this layer, decides what counts as clean, and the
# next disclosure batch should be answered by a rebuild, not an edit here.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# Strip the pip build/install toolchain packages that Trivy flags as HIGH in the
# base image (wheel CVE-2026-24049, jaraco.context CVE-2026-23949). The runtime
# only executes the pre-built `knovaryn` console script and never installs
# packages; these are build-time-only. Scan both possible site-packages roots
# with find so the removal is independent of the exact package path, and print
# each removed path so the build log confirms what was stripped. Removed
# directly rather than via `pip uninstall` because setuptools (kept, not
# flagged) declares jaraco.context as a dependency, which would block a
# dependency-aware uninstall.
RUN find /usr/local/lib/python3.11 /usr/lib/python3.11 \
        \( -name 'wheel*' -o -name 'jaraco*' \) -print -exec rm -rf {} + 2>/dev/null; true

# Non-root operator by default (defense in depth).
RUN useradd --create-home --uid 10001 knovaryn
# Writable scratch for the intake quarantine dir (compose/K8s mount a named
# volume here). Creating it owned by the runtime user means a FRESH named
# volume inherits that ownership on first mount — otherwise the mount lands
# root-owned and uploads fail with EACCES (caught by the compose E2E).
RUN mkdir -p /data && chown knovaryn:knovaryn /data
USER knovaryn

# Default: serve the REST API (offline demo + web console).
EXPOSE 8000
CMD ["knovaryn", "server", "--host", "0.0.0.0", "--port", "8000"]
