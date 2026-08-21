#!/usr/bin/env python3
"""public_surface_audit.py — fail when public surface contains private-build material.

This is a CI/SECURITY gate. It scans tracked files, built packages, and the
generated documentation site for patterns that should never appear in the
public repository or published artifacts.
"""

import os
import re
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Forbidden patterns — match full-text in .md, .py, .html, .toml, .yaml, .yml,
# .json, .cfg, .ini files. Two tiers, on purpose:
#
# * GENERIC patterns ship in this public file. They name build-process
#   *material* (prompt/ledger/audit artifacts, machine paths) and disclose
#   nothing by being listed — the same way a linter's dictionary must contain
#   the misspellings it flags.
#
# * IDENTITY patterns are themselves secrets: writing them into this public
#   file would disclose exactly what this gate exists to protect. They live
#   in a git-excluded pattern file and load only when
#   KNOVARYN_EXTRA_FORBIDDEN_PATTERNS points at it (one regex per line,
#   '#' comments). CI and public checkouts run the generic gate; the private
#   build environment layers the identity patterns on top
#   (run_private_surface_gate.sh).
#
# Keep every pattern a build-process identifier, not a valid runtime product
# term (a provider/model string is legitimate runtime configuration; the same
# string identifying the BUILD toolchain is not).
# ---------------------------------------------------------------------------
GENERIC_FORBIDDEN_PATTERNS: list[re.Pattern] = [
    re.compile(r"one-shot build prompt", re.IGNORECASE),
    re.compile(r"private execution contract", re.IGNORECASE),
    re.compile(r"/private/tmp/"),
    re.compile(r"/Users/\w+/"),
    re.compile(r"C:\\Users\\\w+\\"),
    re.compile(r"Soviet judge", re.IGNORECASE),
    re.compile(r"internal 10/10 audit", re.IGNORECASE),
]

EXTRA_PATTERNS_ENV = "KNOVARYN_EXTRA_FORBIDDEN_PATTERNS"


def _load_extra_patterns(env_var: str = EXTRA_PATTERNS_ENV) -> list[re.Pattern]:
    """Load private (identity) forbidden patterns, if configured.

    Absent the env var — the case in CI and any public checkout — this
    returns [] and the generic gate stands alone.
    """
    raw = os.environ.get(env_var, "")
    if not raw:
        return []
    path = Path(raw)
    if not path.is_file():
        return []
    patterns: list[re.Pattern] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(re.compile(line, re.IGNORECASE))
    return patterns


FORBIDDEN_PATTERNS: list[re.Pattern] = GENERIC_FORBIDDEN_PATTERNS + _load_extra_patterns()

ALLOWED_CONTEXTS = [
    re.compile(r"docs/?reference/build-report-39\.md"),
    # the sanitized public report's rendered site pages + search index
    re.compile(r"(^|/)site/reference/build-report-39/"),
]

# Dot-directories are tool state or private material — never public surface —
# so they are excluded generically (this file names no private path).
# .github is tracked, public workflow configuration and stays in scope.
_SCANNED_DOT_DIRS = {".github"}
_JUNK_DIRS = {"__pycache__", "node_modules"}

# The gate ships inside the sdist; its source holds the generic pattern
# definitions (the linter-dictionary rule above), so archive scans skip the
# gate's own member exactly as the tree scan skips the gate's own file.
_SELF_MEMBER_SUFFIX = "/" + str(Path(__file__).resolve().relative_to(REPO_ROOT))

SKIP_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".zip",
    ".gz",
    ".bz2",
    ".xz",
    ".whl",
}


def _should_check_path(path: Path) -> bool:
    """Return True if the file should be scanned for forbidden patterns."""
    if path.resolve() == Path(__file__).resolve():
        return False  # this gate defines the generic patterns; it cannot scan itself
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return False
    if path.name == ".gitignore":
        return True  # dotfile with no suffix; scan it like any text file
    # Dot-directories hold tool state / private material, never public
    # surface; .github is tracked public configuration and stays in scope.
    # Non-dot junk dirs are build/tool output with nothing to say.
    if any(
        (part.startswith(".") and part not in _SCANNED_DOT_DIRS) or part in _JUNK_DIRS
        for part in path.parts[:-1]
    ):
        return False
    # Only check text-like files
    return path.suffix.lower() in {
        ".md",
        ".py",
        ".html",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".cfg",
        ".ini",
        ".txt",
        ".css",
        ".js",
        ".xml",
    }


def _is_allowed(filepath: str) -> bool:
    return any(pat.search(filepath) for pat in ALLOWED_CONTEXTS)


def scan_tracked_files() -> list[str]:
    """Walk the repository source tree (git-tracked-equivalent) for forbidden patterns."""
    findings: list[str] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        # Prune dot-dirs (tool state / private material) and junk dirs; .github
        # stays in scope as tracked public configuration.
        dirs[:] = [
            d
            for d in dirs
            if (d in _SCANNED_DOT_DIRS or not d.startswith(".")) and d not in _JUNK_DIRS
        ]
        for fn in files:
            fpath = Path(root) / fn
            if not _should_check_path(fpath):
                continue
            rel = fpath.relative_to(REPO_ROOT)
            if _is_allowed(str(rel)):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pattern in FORBIDDEN_PATTERNS:
                for lineno, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        findings.append(f"{rel}:{lineno}: matched {pattern.pattern!r}")
                        break  # one finding per pattern per file
    return findings


def scan_wheel(path: str) -> list[str]:
    """Check a .whl (zip) archive for forbidden patterns."""
    findings: list[str] = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(_SELF_MEMBER_SUFFIX):
                    continue  # the gate does not scan itself
                if _is_allowed(name):
                    continue
                ext = Path(name).suffix.lower()
                if ext in SKIP_EXTENSIONS or ext not in {
                    ".md",
                    ".py",
                    ".html",
                    ".toml",
                    ".txt",
                    ".cfg",
                    ".ini",
                    ".json",
                }:
                    continue
                try:
                    text = zf.read(name).decode("utf-8")
                except Exception:
                    continue
                for pattern in FORBIDDEN_PATTERNS:
                    if pattern.search(text):
                        findings.append(f"wheel:{name}: matched {pattern.pattern!r}")
    except FileNotFoundError:
        findings.append(f"Wheel not found at {path}")
    return findings


def scan_sdist(path: str) -> list[str]:
    """Check a .tar.gz source distribution for forbidden patterns."""
    findings: list[str] = []
    try:
        with tarfile.open(path, "r:gz") as tf:
            for member in tf.getmembers():
                if member.name.endswith(_SELF_MEMBER_SUFFIX):
                    continue  # the gate does not scan itself
                if _is_allowed(member.name):
                    continue
                ext = Path(member.name).suffix.lower()
                if ext in SKIP_EXTENSIONS or ext not in {
                    ".md",
                    ".py",
                    ".html",
                    ".toml",
                    ".txt",
                    ".cfg",
                    ".ini",
                    ".json",
                }:
                    continue
                if not member.isfile():
                    continue
                try:
                    f = tf.extractfile(member)
                    if f is None:
                        continue
                    text = f.read().decode("utf-8")
                except Exception:
                    continue
                for pattern in FORBIDDEN_PATTERNS:
                    if pattern.search(text):
                        findings.append(f"sdist:{member.name}: matched {pattern.pattern!r}")
    except FileNotFoundError:
        findings.append(f"Sdist not found at {path}")
    return findings


def scan_site_dir(site_path: str) -> list[str]:
    """Check the built documentation site."""
    findings: list[str] = []
    site = Path(site_path)
    if not site.is_dir():
        findings.append(f"Site directory not found at {site_path}")
        return findings
    for root, dirs, files in os.walk(site):
        dirs[:] = [
            d
            for d in dirs
            if (d in _SCANNED_DOT_DIRS or not d.startswith(".")) and d not in _JUNK_DIRS
        ]
        for fn in files:
            fpath = Path(root) / fn
            if not _should_check_path(fpath):
                continue
            rel = fpath.relative_to(site)
            if _is_allowed(str(rel)):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(text):
                    findings.append(f"site:{rel}: matched {pattern.pattern!r}")
    return findings


def collect_all_findings() -> tuple[list[str], list[str], list[str], list[str]]:
    """Run every scan; return (tracked, wheel, sdist, site) finding lists.

    Missing artifacts yield empty lists (nothing present = nothing to leak).
    """
    tracked = scan_tracked_files()

    wheel: list[str] = []
    for w in sorted((REPO_ROOT / "dist").glob("*.whl")):
        wheel.extend(scan_wheel(str(w)))
    sdist: list[str] = []
    for sd in sorted((REPO_ROOT / "dist").glob("*.tar.gz")):
        sdist.extend(scan_sdist(str(sd)))

    site_dir = REPO_ROOT / "site"
    site = scan_site_dir(str(site_dir)) if site_dir.is_dir() else []
    return tracked, wheel, sdist, site


def main() -> int:
    all_findings: list[str] = []

    print("=== Scanning tracked files ===")
    tracked = scan_tracked_files()
    if tracked:
        for f in tracked:
            print(f"  FAIL: {f}")
        all_findings.extend(tracked)
    else:
        print("  OK — no private-build patterns in tracked files")

    # Scan built artifacts if they exist
    dist_dir = REPO_ROOT / "dist"
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if wheels:
        for w in wheels:
            print(f"=== Scanning wheel: {w.name} ===")
            wf = scan_wheel(str(w))
            if wf:
                for f in wf:
                    print(f"  FAIL: {f}")
                all_findings.extend(wf)
            else:
                print("  OK")
    if sdists:
        for s in sdists:
            print(f"=== Scanning sdist: {s.name} ===")
            sf = scan_sdist(str(s))
            if sf:
                for f in sf:
                    print(f"  FAIL: {f}")
                all_findings.extend(sf)
            else:
                print("  OK")

    site_dir = REPO_ROOT / "site"
    if site_dir.is_dir():
        print("=== Scanning docs site ===")
        sitef = scan_site_dir(str(site_dir))
        if sitef:
            for f in sitef:
                print(f"  FAIL: {f}")
            all_findings.extend(sitef)
        else:
            print("  OK")

    if all_findings:
        print(f"\nFAILED: {len(all_findings)} forbidden pattern(s) found in public surface.")
        return 1
    print("\nPASSED: public surface is clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
