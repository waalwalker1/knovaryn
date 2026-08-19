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
# .json, .cfg, .ini files. Use raw strings to avoid escaping issues.
# IMPORTANT: keep these as build-process identifiers only, not valid runtime
# product documentation terms (e.g., "DeepSeek" as a supported runtime model
# is fine; "deepinfra/deepseek-v4-flash-0731" as the build tool is not.)
# ---------------------------------------------------------------------------
FORBIDDEN_PATTERNS: list[re.Pattern] = [
    re.compile(r"Claude Code", re.IGNORECASE),
    re.compile(r"one-shot build prompt", re.IGNORECASE),
    re.compile(r"private execution contract", re.IGNORECASE),
    re.compile(r"deepinfra/deepseek[-\s]??v4[-\s]??flash", re.IGNORECASE),
    re.compile(r"\.knovaryn-build-private"),
    re.compile(r"/private/tmp/"),
    re.compile(r"/Users/\w+/"),
    re.compile(r"C:\\Users\\\w+\\"),
    re.compile(r"Soviet judge", re.IGNORECASE),
    re.compile(r"internal 10/10 audit", re.IGNORECASE),
]

ALLOWED_CONTEXTS = [
    re.compile(r"docs/?reference/build-report-39\.md"),
    re.compile(r"\.knovaryn-build-private/"),
]

# Exclude files that are known to contain private-build material but are
# *explicitly excluded from the public surface* (git-excluded or .gitignore'd).
EXCLUDE_DIRS = {".git", ".knovaryn-build-private", "__pycache__", ".venv", "node_modules", ".ruff_cache", ".mypy_cache", ".pytest_cache"}
EXCLUDE_PREFIXES = (".git/", ".knovaryn-build-private/")

SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".zip", ".gz", ".bz2", ".xz", ".whl"}


def _should_check_path(path: Path) -> bool:
    """Return True if the file should be scanned for forbidden patterns."""
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return False
    for prefix in EXCLUDE_PREFIXES:
        if str(path).startswith(str(REPO_ROOT / prefix)):
            return False
    # Only check text-like files
    return path.suffix.lower() in {".md", ".py", ".html", ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini", ".txt", ".css", ".js", ".xml"}


def _is_allowed(filepath: str) -> bool:
    for pat in ALLOWED_CONTEXTS:
        if pat.search(filepath):
            return True
    return False


def scan_tracked_files() -> list[str]:
    """Walk the repository source tree (git-tracked-equivalent) for forbidden patterns."""
    findings: list[str] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
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
                if _is_allowed(name):
                    continue
                ext = Path(name).suffix.lower()
                if ext in SKIP_EXTENSIONS or ext not in {".md", ".py", ".html", ".toml", ".txt", ".cfg", ".ini", ".json"}:
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
                if _is_allowed(member.name):
                    continue
                ext = Path(member.name).suffix.lower()
                if ext in SKIP_EXTENSIONS or ext not in {".md", ".py", ".html", ".toml", ".txt", ".cfg", ".ini", ".json"}:
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
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
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
