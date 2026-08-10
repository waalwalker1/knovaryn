"""Local-path policy (spec §8.3).

Resolve real paths and verify they stay inside configured roots. Reject symlink
escape and path traversal. Never expand shell syntax / env vars / ``~`` from
untrusted arguments.
"""

from __future__ import annotations

from pathlib import Path

from ...domain.errors import PathTraversalError


def resolve_allowed_roots(roots: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for root in roots:
        p = Path(root).expanduser().resolve(strict=False)
        p.mkdir(parents=True, exist_ok=True)
        resolved.append(p)
    return resolved


def is_within(child: Path, roots: list[Path]) -> bool:
    try:
        child = child.resolve(strict=False)
    except OSError:
        return False
    for root in roots:
        try:
            child.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def validate_local_path(
    path_str: str, *, allowed_roots: list[str], follow_symlinks: bool = False
) -> Path:
    """Return the real, allowed path or raise PathTraversalError."""
    # Never expand env vars or shell syntax from untrusted input.
    if "$" in path_str or "`" in path_str or ";" in path_str or "|" in path_str or "\n" in path_str:
        raise PathTraversalError("path contains shell/expansion syntax")
    raw = Path(path_str)
    candidate = raw if raw.is_absolute() else Path.cwd() / raw

    roots = resolve_allowed_roots(allowed_roots)
    if not follow_symlinks:
        # reject any symlink in the path
        _reject_symlink_components(candidate)

    if not is_within(candidate, roots):
        raise PathTraversalError(
            f"path {path_str!r} resolves outside allowed roots",
            details={"roots": [str(r) for r in roots]},
        )
    if candidate.is_symlink() and not follow_symlinks:
        raise PathTraversalError(f"symlink not allowed: {path_str!r}")
    real = candidate.resolve(strict=False)
    if not is_within(real, roots):
        raise PathTraversalError(f"resolved path escapes allowed roots: {path_str!r}")
    if not real.exists():
        raise PathTraversalError(f"path does not exist: {path_str!r}")
    if real.is_char_device() or real.is_block_device() or real.is_socket() or real.is_fifo():
        raise PathTraversalError(f"special file not allowed: {path_str!r}")
    return real


def _reject_symlink_components(candidate: Path) -> None:
    # walk components, reject if any is a symlink pointing outside
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise PathTraversalError(f"symlink component not allowed: {str(current)!r}")
