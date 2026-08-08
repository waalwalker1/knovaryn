# Knovaryn development container.
# Provides a clean, reproducible build/test environment for contributors.
# The project's own runtime images live in deploy/docker/Dockerfile; this
# container is for interactive development (editor + uv + tooling).

# No pinned base digest here on purpose: the devcontainer tracks the user's OS
# toolchain. Release images in deploy/docker/ pin digests instead (spec §29.1).
FROM docker.io/library/ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH="/home/vscode/.local/bin:${PATH}"

# Build/runtime system dependencies: compilers + common ML/base libs so the
# opt-in extras (docling, parquet, s3) can install when the user asks for them.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        ca-certificates \
        curl \
        git \
        htop \
        jq \
        unzip \
        libssl-dev \
        libffi-dev \
        libblas-dev \
        liblapack-dev \
        zlib1g-dev \
        sqlite3 \
        && rm -rf /var/lib/apt/lists/*

# The devcontainer "common-utils" feature creates the vscode user; defer user
# creation to that feature so UID/GID match the host. This image only provides
# the base toolchain image.
USER root

# Install uv (project's canonical environment manager) for the vscode user.
RUN useradd -m -s /bin/bash vscode 2>/dev/null || true
USER vscode
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /workspace

# Default shell.
CMD ["/bin/bash"]
