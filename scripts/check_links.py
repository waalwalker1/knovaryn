"""Blocking documentation-link validation (defect 3.3, v0.2.1).

v0.2.0's docs CI ended ``markdown-link-check … || true``, so broken links
could never fail the build. This script is the blocking half of the repair:

* scans **all** public Markdown (README, docs/**, root *.md, CHANGELOG,
  examples/benchmarks fixtures), ``llms.txt`` / ``llms-full.txt`` when
  present, and — when a built site is supplied via ``--site`` — the
  generated MkDocs HTML;
* verifies every **internal** target exists: relative and repo-rooted paths,
  same-page and cross-page ``#fragments`` (GitHub-style slugging for Markdown,
  ``id=`` attributes for HTML), local images, and downloadable example files;
* fails (exit 1) on any broken internal link, missing image, or missing
  generated diagram;

External ``http(s)`` URLs are *not* fetched here — they are covered by
``markdown-link-check`` (retrying, allowlisted via ``.mlc-config.json``),
which CI runs as a separate informational step so provider-side flakiness
cannot mask or excuse a genuinely broken repository link.

Usage:
    python scripts/check_links.py [--site site] [--root .]
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "site",  # generated output is scanned only via --site
    "dist",
    "build",
}

_MD_LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_MD_REFDEF = re.compile(r"^\s*\[[^\]]+\]:\s+(\S+)\s*$", re.M)
_FENCED = re.compile(r"```.*?```|~~~.*?~~~", re.S)


def _strip_fences(text: str) -> str:
    return _FENCED.sub("", text)


def _github_slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s, flags=re.UNICODE)
    return s.replace(" ", "-")


def _md_heading_slugs(md_path: Path) -> set[str]:
    slugs: set[str] = set()
    try:
        raw = md_path.read_text(encoding="utf-8")
    except OSError:
        return slugs
    in_fence = False
    for line in raw.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            slugs.add(_github_slug(m.group(1)))
    return slugs


def _iter_markdown(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        files.append(p)
    for name in ("llms.txt", "llms-full.txt"):
        extra = root / "docs" / name
        if extra.exists():
            files.append(extra)
    return files


class _HTMLLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.srcs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if tag == "a" and d.get("href"):
            self.hrefs.append(d["href"])
        if tag in ("img", "source") and d.get("src"):
            self.srcs.append(d["src"])
        for key in ("id", "name"):
            if d.get(key):
                self.ids.add(d[key])
        # MkDocs Material emits anchors like <a class="headerlink" href="#x">
        if d.get("href", "").startswith("#"):
            self.ids.add(d["href"][1:])


def _html_ids(html_path: Path) -> set[str]:
    parser = _HTMLLinks()
    try:
        parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return set()
    return parser.ids


def check(root: Path, site: Path | None) -> tuple[list[str], int]:
    problems: list[str]
    problems = []
    external = 0
    scanned = 0

    def resolve(base_file: Path, target: str) -> Path | None:
        """Resolve an internal target to a repo/virtual-root file, or None."""
        if target.startswith("/"):
            # MkDocs absolute-style link: try docs/ then repo root then site root.
            rel = target.lstrip("/")
            candidates = [root / "docs" / rel, root / rel, (site / rel) if site else None]
            for c in candidates:
                if c is not None and c.exists():
                    return c
            return None
        resolved = (base_file.parent / target).resolve()
        if resolved.exists():
            return resolved
        # inside a built-site tree, links are relative to the page directory
        if site is not None:
            try:
                page_rel = base_file.resolve().relative_to(site.resolve())
                alt = (site / page_rel.parent / target).resolve()
                if alt.exists():
                    return alt
            except ValueError:
                pass
        return None

    # ---- Markdown sources -------------------------------------------------
    for md in _iter_markdown(root):
        scanned += 1
        body = _strip_fences(md.read_text(encoding="utf-8", errors="replace"))
        targets: list[str] = []
        for rx in (_MD_LINK, _MD_REFDEF):
            targets += rx.findall(body)
        image_targets = _MD_IMAGE.findall(body)

        def check_target(t: str, *, kind: str) -> None:
            nonlocal external
            t = t.strip()
            if not t or t.startswith(("<", "mailto:", "{{")):
                return
            if re.match(r"^https?://", t):
                external += 1
                return
            path_part, _, frag = t.partition("#")
            if not path_part:
                # same-file fragment
                if frag and frag not in _md_heading_slugs(md):
                    problems.append(f"{md.relative_to(root)}: missing fragment #{frag}")
                return
            resolved = resolve(md, path_part)
            if resolved is None:
                problems.append(
                    f"{md.relative_to(root)}: {kind} target not found: {t}"
                )
                return
            if frag:
                if resolved.suffix == ".html":
                    if frag not in _html_ids(resolved):
                        problems.append(f"{md.relative_to(root)}: #{frag} missing in {t}")
                elif resolved.suffix == ".md":
                    if frag not in _md_heading_slugs(resolved):
                        problems.append(f"{md.relative_to(root)}: #{frag} missing in {t}")

        for t in targets:
            check_target(t, kind="link")
        for t in image_targets:
            check_target(t, kind="image")

    # ---- Generated MkDocs HTML --------------------------------------------
    if site is not None and site.exists():
        for html in sorted(site.rglob("*.html")):
            scanned += 1
            parser = _HTMLLinks()
            try:
                parser.feed(html.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            page_ids = parser.ids

            def check_html(t: str, *, kind: str) -> None:
                nonlocal external
                if t.startswith(("http://", "https://", "mailto:", "#!", "javascript:", "{{")):
                    if t.startswith(("http://", "https://")):
                        external += 1
                    return
                path_part, _, frag = t.partition("#")
                if not path_part:
                    if frag and frag not in page_ids:
                        problems.append(
                            f"{html.relative_to(site)}: missing fragment #{frag}"
                        )
                    return
                resolved = resolve(html, path_part)
                if resolved is None:
                    problems.append(
                        f"{html.relative_to(site)}: {kind} target not found: {t}"
                    )
                    return
                if frag and resolved.suffix == ".html":
                    ids = page_ids if resolved == html else _html_ids(resolved)
                    if frag not in ids:
                        problems.append(f"{html.relative_to(site)}: #{frag} missing in {t}")

            for t in parser.hrefs:
                check_html(t, kind="link")
            for t in parser.srcs:
                check_html(t, kind="image")

    return problems, external


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="repository root (default: cwd)")
    ap.add_argument("--site", default=None, help="generated MkDocs site/ directory")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    site = Path(args.site).resolve() if args.site else None

    problems, external = check(root, site)

    if problems:
        print(f"FAIL: {len(problems)} broken internal link(s)/fragment(s)/image(s):\n")
        for p in sorted(set(problems)):
            print(f"  - {p}")
        print(
            "\nExternal URLs are checked separately (informational): "
            f"{external} encountered.",
            file=sys.stderr,
        )
        return 1

    print(f"link check OK: all internal links/fragments/images resolve "
          f"({external} external URLs deferred to markdown-link-check)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
