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

Release-metadata coherence (v0.2.2 contract §4.3) — checked against the same
sources, never against a network service:

* Release date authority         — ``CHANGELOG.md`` entry for the current
  version carries a ``YYYY-MM-DD`` date; ``CITATION.cff`` ``date-released``
  and ``codemeta.json`` ``datePublished`` must equal it.
* Maturity label                 — on the ``0.x`` line, pyproject's
  ``Development Status`` classifier and codemeta ``developmentStatus`` must
  both say the same thing (alpha), and README/docs "alpha (X)" claims must
  carry the current version.
* Project URLs                   — pyproject ``[project.urls]`` Homepage/
  Documentation point at the docs site; Repository/Issues/Changelog/Security
  at the canonical repository.
* Website URL                    — MkDocs ``site_url``, CITATION.cff ``url``,
  and codemeta ``codeRepository``/``relatedLink`` agree with the canonical
  site and repo.
* Social-preview asset path      — the OpenGraph/Twitter image in the MkDocs
  override resolves to the generated brand preview file on disk.
* Changelog link                 — ``CHANGELOG.md`` defines the compare/tag
  link for the current version.

Historical changelog entries and migration notes MAY retain old versions;
this check never scans changelogs for *versions*, only for the current one's
own entry and link.

Exit code 0 = all surfaces synchronized; nonzero prints each offending
surface and the fix. Run ``--fix`` to rewrite the mechanical surfaces
(cff/codemeta versions and release dates, pyproject/labels/mkdocs/app/server
constants, deploy pins, social-preview path) automatically.
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
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
REST_APP = REPO_ROOT / "src" / "knovaryn" / "interfaces" / "rest" / "app.py"
MCP_SERVER = REPO_ROOT / "src" / "knovaryn" / "interfaces" / "mcp" / "server.py"
README = REPO_ROOT / "README.md"
OVERRIDES_MAIN = REPO_ROOT / "overrides" / "main.html"
DOCKERFILES = [REPO_ROOT / "Dockerfile", *sorted((REPO_ROOT / "deploy").glob("**/Dockerfile"))]

# Canonical public URLs (owner configuration; not fetched — only compared).
REPO_URL = "https://github.com/waalwalker1/knovaryn"
SITE_URL = "https://waalwalker1.github.io/knovaryn/"
PYPI_URL = "https://pypi.org/project/knovaryn/"
SOCIAL_PREVIEW_REL = "assets/brand/docs-social-preview.png"


def authoritative_version() -> str:
    text = INIT_PY.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"', text, re.M)
    if not match:
        raise SystemExit(f"FAIL: no __version__ literal in {INIT_PY.relative_to(REPO_ROOT)}")
    return match.group(1)


def authoritative_release_date(version: str) -> str | None:
    """Release date of ``version`` as recorded in CHANGELOG.md.

    The changelog is the mechanically authoritative release-date source
    (Keep a Changelog: every released version carries its date). Returns
    ``None`` when the entry or its date is missing — callers report that.
    """
    if not CHANGELOG.exists():
        return None
    cl = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"^##\s*\[{re.escape(version)}\]\s*-\s*(\d{{4}}-\d{{2}}-\d{{2}})\s*$", cl, re.M)
    return m.group(1) if m else None


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
    hatch_hook = (
        re.search(
            r"\[tool\.hatch\.version\][^\[]*path\s*=\s*\"src/knovaryn/__init__\.py\"", py, re.S
        )
        is not None
    )
    literal = re.search(r'^version\s*=\s*"([^"]+)"', py, re.M)
    if not (has_dynamic and hatch_hook):
        _check(
            "pyproject.toml version wiring",
            literal.group(1) if literal else "<not dynamic>",
            version,
            errors,
            'use dynamic = ["version"] + [tool.hatch.version] path="src/knovaryn/__init__.py"',
        )

    # CITATION.cff
    if CITATION.exists():
        cf = CITATION.read_text(encoding="utf-8")
        m = re.search(r"^version:\s*(\S+)\s*$", cf, re.M)
        _check(
            "CITATION.cff version",
            m.group(1) if m else None,
            version,
            errors,
            f'set "version: {version}"',
        )

    # codemeta.json
    if CODEMETA.exists():
        cm = json.loads(CODEMETA.read_text(encoding="utf-8"))
        _check(
            "codemeta.json version",
            cm.get("version"),
            version,
            errors,
            f'set "version": "{version}"',
        )

    # REST / OpenAPI metadata — must use the authoritative symbol, never a
    # literal (a literal equal to today's version still rots tomorrow).
    ra = REST_APP.read_text(encoding="utf-8")
    uses_symbol = re.search(r"version\s*=\s*__version__\b", ra) is not None
    literal = re.search(r'version\s*=\s*"([^"]+)"', ra)
    if not uses_symbol:
        _check(
            "REST FastAPI(version=...)",
            literal.group(1) if literal else "<missing>",
            version,
            errors,
            "import __version__ from knovaryn and pass version=__version__",
        )

    # MCP server metadata — same rule.
    ms = MCP_SERVER.read_text(encoding="utf-8")
    mcp_alias = re.search(r"import\s+__version__\s+as\s+SERVER_VERSION\b", ms) is not None
    mcp_literal = re.search(r'^SERVER_VERSION\s*=\s*"([^"]+)"', ms, re.M)
    if not mcp_alias:
        _check(
            "MCP SERVER_VERSION",
            mcp_literal.group(1) if mcp_literal else "<missing>",
            version,
            errors,
            "add `from ... import __version__ as SERVER_VERSION`",
        )

    # container labels
    for dk in DOCKERFILES:
        if not dk.exists():
            continue
        dt = dk.read_text(encoding="utf-8")
        m = re.search(r'org\.opencontainers\.image\.version[= ]"?([0-9][^"\s]*)"?', dt)
        _check(
            f"{dk.relative_to(REPO_ROOT)} image.version label",
            m.group(1) if m else None,
            version,
            errors,
            f"label org.opencontainers.image.version={version}",
        )

    # deployed image pins (compose + kubernetes): every knovaryn image tag in
    # deploy/ must equal the release version — a stale pin ships an old image
    # to operators who trust the manifest.
    pin_re = re.compile(r"(ghcr\.io/knovaryn/knovaryn:)([0-9][^\s\"']*)")
    deploy_files = sorted(
        p for pattern in ("deploy/**/*.yml", "deploy/**/*.yaml") for p in REPO_ROOT.glob(pattern)
    )
    for df in deploy_files:
        dt = df.read_text(encoding="utf-8")
        for pm in pin_re.finditer(dt):
            _check(
                f"{df.relative_to(REPO_ROOT)} image pin",
                pm.group(2),
                version,
                errors,
                f"pin ghcr.io/knovaryn/knovaryn:{version}",
            )

    # documentation home (mkdocs extra.version)
    mk = _mkdocs_config().read_text(encoding="utf-8")
    m = re.search(r"^\s+version:\s*[\"']?([0-9][^\"'\s]*)[\"']?\s*$", mk, re.M)
    _check(
        "mkdocs extra.version",
        m.group(1) if m else None,
        version,
        errors,
        f"add to mkdocs.yml:\n  extra:\n    version: {version}",
    )

    # README current-version marker (must exist AND match)
    if README.exists():
        rd = README.read_text(encoding="utf-8")
        m = re.search(r"<!--\s*knovaryn-version:\s*([0-9.]+)\s*-->", rd)
        _check(
            "README current-version marker",
            m.group(1) if m else None,
            version,
            errors,
            f'add/update "<!-- knovaryn-version: {version} -->" near the top',
        )

        # "alpha (X)" prose claims must carry the current version (same rule
        # as the test suite; the script is the CI gate, the test the guard).
        for m in re.finditer(r"[Aa]lpha \(`(\d+\.\d+\.\d+)`\)", rd):
            _check(
                "README alpha claim",
                m.group(1),
                version,
                errors,
                f'update the alpha claim to "{version}"',
            )
        di = REPO_ROOT / "docs" / "index.md"
        if di.exists():
            dt = di.read_text(encoding="utf-8")
            # docs landing page carries its own current-version marker (same
            # rule as README): the hero maturity pill is generated from it.
            m = re.search(r"<!--\s*knovaryn-version:\s*([0-9.]+)\s*-->", dt)
            _check(
                "docs/index.md current-version marker",
                m.group(1) if m else None,
                version,
                errors,
                f'add/update "<!-- knovaryn-version: {version} -->" near the top',
            )
            for m in re.finditer(r"[Aa]lpha \(`(\d+\.\d+\.\d+)`\)", dt):
                _check(
                    "docs/index.md alpha claim",
                    m.group(1),
                    version,
                    errors,
                    f'update the alpha claim to "{version}"',
                )

    # --- release-metadata coherence (v0.2.2 contract §4.3) -----------------

    # release date authority chain: changelog -> CITATION.cff / codemeta
    rel_date = authoritative_release_date(version)
    if rel_date is None:
        errors.append(
            f"CHANGELOG.md: no dated entry '## [{version}] - YYYY-MM-DD'\n"
            "  fix: add the release entry with its real publication date "
            "(the changelog date is the authoritative release date)"
        )
    else:
        if CITATION.exists():
            cf = CITATION.read_text(encoding="utf-8")
            m = re.search(r"^date-released:\s*(\S+)\s*$", cf, re.M)
            _check(
                "CITATION.cff date-released",
                m.group(1) if m else None,
                rel_date,
                errors,
                f'set "date-released: {rel_date}"',
            )
        if CODEMETA.exists():
            cm = json.loads(CODEMETA.read_text(encoding="utf-8"))
            _check(
                "codemeta.json datePublished",
                cm.get("datePublished"),
                rel_date,
                errors,
                f'set "datePublished": "{rel_date}"',
            )

    # maturity label: on the 0.x line both declared statuses must agree and
    # say alpha (the public wording everywhere already says alpha).
    if version.startswith("0."):
        want_status = "alpha"
        if PYPROJECT.exists():
            py = PYPROJECT.read_text(encoding="utf-8")
            m = re.search(r'"Development Status :: (\d) - (\w+)"', py)
            found = m.group(2).lower() if m else None
            _check(
                "pyproject Development Status classifier",
                found,
                want_status,
                errors,
                f'set classifier "Development Status :: 3 - {want_status.capitalize()}" '
                "(0.x line is alpha)",
            )
        if CODEMETA.exists():
            cm = json.loads(CODEMETA.read_text(encoding="utf-8"))
            _check(
                "codemeta.json developmentStatus",
                str(cm.get("developmentStatus", "")).lower(),
                want_status,
                errors,
                f'set "developmentStatus": "{want_status}"',
            )

    # project URLs: canonical repo/site wiring, no drift or typos
    url_want = {
        "Homepage": SITE_URL,
        "Documentation": SITE_URL,
        "Repository": REPO_URL,
        "Issues": f"{REPO_URL}/issues",
        "Changelog": f"{REPO_URL}/blob/main/CHANGELOG.md",
        "Security": f"{REPO_URL}/blob/main/SECURITY.md",
    }
    if PYPROJECT.exists():
        py = PYPROJECT.read_text(encoding="utf-8")
        sec = re.search(r"^\[project\.urls\]\n(.*?)(?=^\[)", py, re.M | re.S)
        if not sec:
            errors.append(
                "pyproject.toml: missing [project.urls] section\n"
                f"  fix: add [project.urls] with Homepage={SITE_URL}"
            )
        else:
            for key, want in url_want.items():
                um = re.search(rf'^{key}\s*=\s*"([^"]+)"', sec.group(1), re.M)
                _check(
                    f"pyproject [project.urls] {key}",
                    um.group(1) if um else None,
                    want,
                    errors,
                    f'set {key} = "{want}"',
                )

    # website URL agreement: mkdocs site_url, CITATION.cff url, codemeta links
    sm = re.search(r"^site_url:\s*(\S+)\s*$", mk, re.M)
    _check(
        "mkdocs site_url",
        (sm.group(1) if sm else None),
        SITE_URL,
        errors,
        f"set site_url: {SITE_URL}",
    )
    if CITATION.exists():
        cf = CITATION.read_text(encoding="utf-8")
        m = re.search(r'^url:\s*"([^"]+)"\s*$', cf, re.M)
        _check(
            "CITATION.cff url",
            m.group(1) if m else None,
            SITE_URL,
            errors,
            f'set url: "{SITE_URL}"',
        )
    if CODEMETA.exists():
        cm = json.loads(CODEMETA.read_text(encoding="utf-8"))
        _check(
            "codemeta.json codeRepository",
            cm.get("codeRepository"),
            REPO_URL,
            errors,
            f'set "codeRepository": "{REPO_URL}"',
        )
        related = cm.get("relatedLink") or []
        for want in (SITE_URL.rstrip("/"), PYPI_URL):
            if want not in related:
                errors.append(
                    f'codemeta.json relatedLink: missing {want}\n  fix: add "{want}" to relatedLink'
                )

    # social-preview asset path: og/twitter image must be the generated brand
    # preview and must exist on disk (path check only — no network).
    if OVERRIDES_MAIN.exists():
        ov = OVERRIDES_MAIN.read_text(encoding="utf-8")
        imgs = set(
            re.findall(r'(?:og:image|twitter:image)"?\s+content="\{\{ site_url \}\}([^"]+)"', ov)
        )
        if not imgs:
            errors.append(
                "overrides/main.html: no og:image/twitter:image meta found\n"
                "  fix: restore the OpenGraph block pointing at "
                f"{SOCIAL_PREVIEW_REL}"
            )
        for img in sorted(imgs):
            if img != SOCIAL_PREVIEW_REL:
                errors.append(
                    f"overrides/main.html social preview: found {img!r}, expected "
                    f"{SOCIAL_PREVIEW_REL!r}\n"
                    "  fix: point og:image/twitter:image at the generated brand preview"
                )
        preview = REPO_ROOT / "docs" / Path(SOCIAL_PREVIEW_REL)
        if not preview.exists():
            errors.append(
                f"social preview asset missing: docs/{SOCIAL_PREVIEW_REL}\n"
                "  fix: run scripts/visuals/build_brand_assets.py"
            )
        dims = re.findall(r'og:image:(width|height)"\s+content="(\d+)"', ov)
        got = dict(dims)
        if got.get("width") != "1200" or got.get("height") != "630":
            errors.append(
                "overrides/main.html: og:image dimensions must declare 1200x630\n"
                "  fix: set og:image:width=1200 and og:image:height=630"
            )

    # changelog compare/tag link for the current version
    if CHANGELOG.exists():
        cl = CHANGELOG.read_text(encoding="utf-8")
        link_re = (
            rf"^\[{re.escape(version)}\]:\s*{re.escape(REPO_URL)}"
            rf"/(?:compare/\S*v{re.escape(version)}|releases/tag/v{re.escape(version)})\s*$"
        )
        if not re.search(link_re, cl, re.M):
            errors.append(
                f"CHANGELOG.md: missing link definition for [{version}]\n"
                f'  fix: add "[{version}]: {REPO_URL}/compare/v0.0.0...v{version}" '
                "(or releases/tag link for x.0.0)"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="rewrite mechanical surfaces to the authoritative version",
    )
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
        changed = False
        if cm.get("version") != version:
            cm["version"] = version
            changed = True
        # release-date authority: the changelog entry for this version wins
        rel_date = authoritative_release_date(version)
        if rel_date is not None:
            if CITATION.exists():
                sub(CITATION, r"^(date-released:\s*)\S+", rf"\g<1>{rel_date}")
            if cm.get("datePublished") != rel_date:
                cm["datePublished"] = rel_date
                changed = True
        if changed:
            CODEMETA.write_text(json.dumps(cm, indent=2) + "\n", encoding="utf-8")
            fixed.append(str(CODEMETA.relative_to(REPO_ROOT)))
    if OVERRIDES_MAIN.exists():
        sub(
            OVERRIDES_MAIN,
            r'((?:og:image|twitter:image)"\s+content="\{\{ site_url \}\})'
            r"(?!" + re.escape(SOCIAL_PREVIEW_REL) + r')[^"]+',
            rf"\g<1>{SOCIAL_PREVIEW_REL}",
        )

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
            # Quoted form first (`LABEL x.y.version="1.2.3" \`) so the closing
            # quote is preserved; fall back to the bare form.
            sub_first(
                dk, r'(org\.opencontainers\.image\.version=")[0-9][^"]*"', rf'\g<1>{version}"'
            )
            sub_first(
                dk, r"(org\.opencontainers\.image\.version=)[0-9][^\s\\]*", rf"\g<1>{version}"
            )

    def sub_all(path: Path, pattern: str, repl: str) -> None:
        text = path.read_text(encoding="utf-8")
        new = re.sub(pattern, repl, text)  # every occurrence
        if new != text:
            path.write_text(new, encoding="utf-8")
            fixed.append(str(path.relative_to(REPO_ROOT)))

    for df in sorted(
        p for pattern in ("deploy/**/*.yml", "deploy/**/*.yaml") for p in REPO_ROOT.glob(pattern)
    ):
        sub_all(df, r"(ghcr\.io/knovaryn/knovaryn:)[0-9][^\s\"']*(?![0-9.])", rf"\g<1>{version}")
    if README.exists():
        sub_first(README, r"(<!--\s*knovaryn-version:\s*)[0-9.]+(\s*-->)", rf"\g<1>{version}\g<2>")
    return fixed


if __name__ == "__main__":
    sys.exit(main())
