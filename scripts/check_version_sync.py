"""Authoritative version synchronization check (defect 3.5, v0.2.1).

v0.2.0 shipped with public surfaces still claiming v0.1.0 (CITATION.cff,
codemeta.json, REST OpenAPI metadata, CLI fallback, marketing pages). The
repair contract requires ONE authoritative version source plus a
synchronization check covering every public surface.

**Authoritative source**: ``knovaryn.__version__`` in
``src/knovaryn/__init__.py`` (pyproject consumes it at build time).

Checked surfaces — each must equal the authoritative version exactly:

* ``pyproject.toml``            — ``[project].version``
* ``CITATION.cff``              — top-level ``version:``
* ``codemeta.json``             — ``"version"``
* REST / OpenAPI                — ``FastAPI(version=...)`` in rest/app.py
* MCP server metadata           — ``SERVER_VERSION`` in interfaces/mcp/server.py
* Container labels              — ``org.opencontainers.image.version`` label
* Deploy image pins             — every ``ghcr.io/knovaryn/knovaryn:<v>`` tag in ``deploy/``
* Documentation home            — ``extra.version`` in the MkDocs config
* README current-version marker — ``<!-- knovaryn-version: X.Y.Z -->``

Historical changelog entries and migration notes MAY retain old versions;
this check never scans changelogs or files under ``docs/changelog/``.

Exit code 0 = all surfaces synchronized; nonzero prints each offending
surface and the fix. Run ``--fix`` to rewrite the mechanical surfaces
(cff/codemeta/pyproject/labels/mkdocs/app/server constants) automatically.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT_PY = REPO_ROOT / "src" / "knovaryn" / "__init__.py"
CITATION = REPO_ROOT / "CITATION.cff"
CODEMETA = REPO_ROOT / "codemeta.json"
REST_APP = REPO_ROOT / "src" / "knovaryn" / "interfaces" / "rest" / "app.py"
MCP_SERVER = REPO_ROOT / "src" / "knovaryn" / "interfaces" / "mcp" / "server.py"
README = REPO_ROOT / "README.md"
DOCKERFILES = [REPO_ROOT / "Dockerfile", *sorted((REPO_ROOT / "deploy").glob("**/Dockerfile"))]


def authoritative_version() -> str:
    text = INIT_PY.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"', text, re.M)
    if not match:
        raise SystemExit(f"FAIL: no __version__ literal in {INIT_PY.relative_to(REPO_ROOT)}")
    return match.group(1)


def _check(label: str, found: str | None, want: str, errors: list[str], fix: str) -> str | None:
    if found == want:
        return None
    errors.append(f"{label}: found {found!r}, expected {want!r}\n  fix: {fix}")
    return fix


def _mkdocs_config() -> Path:
    candidates = [REPO_ROOT / "mkdocs.yml", REPO_ROOT / "docs" / "mkdocs.yml"]
    for c in candidates:
        if c.exists():
            return c
    raise SystemExit("FAIL: no mkdocs.yml found at repo root or docs/")


def check(allow_drift: bool) -> list[str]:
    version = authoritative_version()
    errors: list[str] = []

    # pyproject: must consume the authoritative source dynamically
    py = PYPROJECT.read_text(encoding="utf-8")
    has_dynamic = re.search(r'^dynamic\s*=\s*\[.*"version".*\]', py, re.M) is not None
    hatch_hook = re.search(
        r"\[tool\.hatch\.version\][^\[]*path\s*=\s*\"src/knovaryn/__init__\.py\"", py, re.S
    ) is not None
    literal = re.search(r'^version\s*=\s*"([^"]+)"', py, re.M)
    if not (has_dynamic and hatch_hook):
        _check("pyproject.toml version wiring",
               literal.group(1) if literal else "<not dynamic>",
               version, errors,
               'use dynamic = ["version"] + [tool.hatch.version] path="src/knovaryn/__init__.py"')

    # CITATION.cff
    if CITATION.exists():
        cf = CITATION.read_text(encoding="utf-8")
        m = re.search(r"^version:\s*(\S+)\s*$", cf, re.M)
        _check("CITATION.cff version", m.group(1) if m else None, version, errors,
               'set "version: %s"' % version)

    # codemeta.json
    if CODEMETA.exists():
        cm = json.loads(CODEMETA.read_text(encoding="utf-8"))
        _check("codemeta.json version", cm.get("version"), version, errors,
               'set "version": "%s"' % version)

    # REST / OpenAPI metadata — must use the authoritative symbol, never a
    # literal (a literal equal to today's version still rots tomorrow).
    ra = REST_APP.read_text(encoding="utf-8")
    uses_symbol = re.search(r"version\s*=\s*__version__\b", ra) is not None
    literal = re.search(r'version\s*=\s*"([^"]+)"', ra)
    if not uses_symbol:
        _check("REST FastAPI(version=...)",
               literal.group(1) if literal else "<missing>", version, errors,
               "import __version__ from knovaryn and pass version=__version__")

    # MCP server metadata — same rule.
    ms = MCP_SERVER.read_text(encoding="utf-8")
    mcp_alias = re.search(
        r"import\s+__version__\s+as\s+SERVER_VERSION\b", ms
    ) is not None
    mcp_literal = re.search(r'^SERVER_VERSION\s*=\s*"([^"]+)"', ms, re.M)
    if not mcp_alias:
        _check("MCP SERVER_VERSION",
               mcp_literal.group(1) if mcp_literal else "<missing>",
               version, errors,
               "add `from ... import __version__ as SERVER_VERSION`")

    # container labels
    for dk in DOCKERFILES:
        if not dk.exists():
            continue
        dt = dk.read_text(encoding="utf-8")
        m = re.search(r'org\.opencontainers\.image\.version[= ]"?([0-9][^"\s]*)"?', dt)
        _check(f"{dk.relative_to(REPO_ROOT)} image.version label",
               m.group(1) if m else None, version, errors,
               f"label org.opencontainers.image.version={version}")

    # deployed image pins (compose + kubernetes): every knovaryn image tag in
    # deploy/ must equal the release version — a stale pin ships an old image
    # to operators who trust the manifest.
    pin_re = re.compile(r"(ghcr\.io/knovaryn/knovaryn:)([0-9][^\s\"']*)")
    deploy_files = sorted(
        p for pattern in ("deploy/**/*.yml", "deploy/**/*.yaml")
        for p in REPO_ROOT.glob(pattern)
    )
    for df in deploy_files:
        dt = df.read_text(encoding="utf-8")
        for pm in pin_re.finditer(dt):
            _check(f"{df.relative_to(REPO_ROOT)} image pin",
                   pm.group(2), version, errors,
                   f"pin ghcr.io/knovaryn/knovaryn:{version}")

    # documentation home (mkdocs extra.version)
    mk = _mkdocs_config().read_text(encoding="utf-8")
    m = re.search(r"^\s+version:\s*[\"']?([0-9][^\"'\s]*)[\"']?\s*$", mk, re.M)
    _check("mkdocs extra.version", m.group(1) if m else None, version, errors,
           f"add to mkdocs.yml:\n  extra:\n    version: {version}")

    # README current-version marker (must exist AND match)
    if README.exists():
        rd = README.read_text(encoding="utf-8")
        m = re.search(r"<!--\s*knovaryn-version:\s*([0-9.]+)\s*-->", rd)
        _check("README current-version marker", m.group(1) if m else None, version, errors,
               f'add/update "<!-- knovaryn-version: {version} -->" near the top')

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true",
                        help="rewrite mechanical surfaces to the authoritative version")
    args = parser.parse_args()

    version = authoritative_version()
    if args.fix:
        fixed = apply_fixes(version)
        for f in fixed:
            print(f"fixed: {f}")
    errors = check(allow_drift=False)
    if errors:
        print(f"version sync FAILED (authoritative {version}):")
        for e in errors:
            print(f"- {e}")
        return 1
    print(f"version sync OK — all public surfaces at {version}")
    return 0


def apply_fixes(version: str) -> list[str]:
    """Rewrite every mechanical surface to ``version``. Returns fixed paths."""
    fixed: list[str] = []

    def sub(path: Path, pattern: str, repl: str) -> None:
        text = path.read_text(encoding="utf-8")
        new = re.sub(pattern, repl, text, count=1, flags=re.M)
        if new != text:
            path.write_text(new, encoding="utf-8")
            fixed.append(str(path.relative_to(REPO_ROOT)))

    if PYPROJECT.exists():
        sub(PYPROJECT, r'^(version\s*=\s*)"[^"]+"', rf'\1"{version}"')
    if CITATION.exists():
        sub(CITATION, r"^(version:\s*)\S+", rf"\g<1>{version}")
    mk = _mkdocs_config()
    sub(mk, r"^(\s+version:\s*)[\"']?[0-9][^\"'\s]*", rf"\g<1>{version}")
    if CODEMETA.exists():
        cm = json.loads(CODEMETA.read_text(encoding="utf-8"))
        if cm.get("version") != version:
            cm["version"] = version
            CODEMETA.write_text(json.dumps(cm, indent=2) + "\n", encoding="utf-8")
            fixed.append(str(CODEMETA.relative_to(REPO_ROOT)))

    def sub_first(path: Path, pattern: str, repl: str) -> None:
        text = path.read_text(encoding="utf-8")
        new = re.sub(pattern, repl, text, count=1)
        if new != text:
            path.write_text(new, encoding="utf-8")
            fixed.append(str(path.relative_to(REPO_ROOT)))

    if REST_APP.exists():
        sub_first(REST_APP, r'(version\s*=\s*)"[^"]+"', rf'\g<1>"{version}"')
    if MCP_SERVER.exists():
        sub_first(MCP_SERVER, r'^(SERVER_VERSION\s*=\s*)"[^"]+"', rf'\g<1>"{version}"')
    for dk in DOCKERFILES:
        if dk.exists():
            sub_first(dk,
                      r"(org\.opencontainers\.image\.version[= ])[\"']?[0-9][^\"'\s]*",
                      rf"\g<1>{version}")

    def sub_all(path: Path, pattern: str, repl: str) -> None:
        text = path.read_text(encoding="utf-8")
        new = re.sub(pattern, repl, text)  # every occurrence
        if new != text:
            path.write_text(new, encoding="utf-8")
            fixed.append(str(path.relative_to(REPO_ROOT)))

    for df in sorted(
        p for pattern in ("deploy/**/*.yml", "deploy/**/*.yaml")
        for p in REPO_ROOT.glob(pattern)
    ):
        sub_all(df,
                r"(ghcr\.io/knovaryn/knovaryn:)[0-9][^\s\"']*(?![0-9.])",
                rf"\g<1>{version}")
    if README.exists():
        sub_first(README, r"(<!--\s*knovaryn-version:\s*)[0-9.]+(\s*-->)", rf"\g<1>{version}\g<2>")
    return fixed


if __name__ == "__main__":
    sys.exit(main())
