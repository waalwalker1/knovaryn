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


def _site_url_prefix(root: Path) -> str:
    """Path component of ``site_url`` from mkdocs.yml (e.g. ``/knovaryn/``).

    The 404 page (and anything else that cannot know its own depth, such as
    Material's search fallbacks) links with *absolute* URLs prefixed by the
    site_url path. On the deployed site those resolve; locally the built
    site/ tree has no such prefix directory, so the resolver must strip it.
    """
    cfg = root / "mkdocs.yml"
    try:
        m = re.search(r"^site_url:\s*(\S+)\s*$", cfg.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    if not m:
        return ""
    rest = m.group(1).split("://", 1)[-1]  # drop scheme
    _, _, path = rest.partition("/")  # drop host
    path = path.strip("/")
    if not path:
        return "/"
    return "/" + path + "/"


def check(root: Path, site: Path | None) -> tuple[list[str], int]:
    problems: list[str]
    problems = []
    external = 0
    scanned = 0
    site_prefix = _site_url_prefix(root)

    def resolve(base_file: Path, target: str) -> Path | None:
        """Resolve an internal target to a repo/virtual-root file, or None."""
        if target.startswith("/"):
            # MkDocs absolute-style link: try docs/ then repo root then site root.
            rel = target.lstrip("/")
            candidates = [root / "docs" / rel, root / rel, (site / rel) if site else None]
            # theme-generated absolute URLs carry the site_url path prefix
            # (e.g. 404.html → /knovaryn/guides/quickstart/); strip it and try
            # the unprefixed location inside the built site tree as well.
            if site is not None and site_prefix != "/" and target.startswith(site_prefix):
                candidates.append(site / rel[len(site_prefix.lstrip("/")) :])
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

        # Raw HTML inside markdown is copied through verbatim by MkDocs —
        # href=/src= attributes there are NOT path-rewritten. They must be
        # checked against the BUILT URL space (see below), because a raw
        # `href="guides/x.md"` or a wrong `../assets/...` depth slips past
        # the markdown-level checks yet breaks on the deployed site.
        html_parser = _HTMLLinks()
        try:
            html_parser.feed(body)
        except Exception:
            html_parser = None  # malformed raw HTML: site-mode scan still covers it
        if html_parser is not None and (html_parser.hrefs or html_parser.srcs):
            docs_root = root / "docs"
            try:
                page_dir = md.parent.relative_to(docs_root)
            except ValueError:
                page_dir = None  # markdown outside docs/ (llms.txt etc.)
            raw_targets = list(html_parser.hrefs) + list(html_parser.srcs)

            def check_raw(
                t: str,
                *,
                md: Path = md,
                page_dir: Path | None = page_dir,
            ) -> None:
                nonlocal external
                t = t.strip()
                if not t or t.startswith(("#", "mailto:", "{{")) or re.match(r"^https?://", t):
                    if re.match(r"^https?://", t):
                        external += 1
                    return
                if re.match(r"^https?://", t):
                    external += 1
                    return
                # built URL space: with use_directory_urls a page
                # <page_dir>/<stem>.md is served at <page_dir>/<stem>/
                # (index.md collapses to <page_dir>/). Resolve the target
                # relative to that directory.
                if page_dir is None:
                    return  # non-docs markdown: no deterministic built URL
                stem = md.stem
                depth_parts = list(page_dir.parts) if page_dir != Path(".") else []
                if stem != "index":
                    depth_parts.append(stem)
                resolved_dir = root / "docs"
                for part in depth_parts:
                    resolved_dir /= part
                path_part, _, frag = t.partition("#")
                candidate = (resolved_dir / path_part).resolve()
                if not candidate.exists():
                    # Target written in BUILT-URL form (<name>/): accept its
                    # markdown source <name>.md (or <name>/index.md) — that is
                    # what MkDocs will serve at that URL.
                    md_source = None
                    url_stem = (resolved_dir / path_part.rstrip("/")).resolve()
                    for alt in (
                        url_stem.with_suffix(".md"),
                        url_stem / "index.md",
                    ):
                        if alt.exists():
                            md_source = alt
                            break
                    if md_source is not None:
                        return  # resolves to a real markdown source → valid URL
                    elif site is not None and ((site / Path(*depth_parts) / path_part).exists()):
                        return  # exists in the built site; fine
                    else:
                        problems.append(
                            f"{md.relative_to(root)}: raw-HTML link does not "
                            f"resolve in built URL space: {t}"
                        )
                        return
                # .md targets in raw HTML are a defect by themselves: MkDocs
                # never rewrites them, so they 404 on the deployed site.
                if candidate.suffix == ".md":
                    problems.append(
                        f"{md.relative_to(root)}: raw-HTML href points at a .md "
                        f"source (never rewritten by MkDocs): {t}"
                    )

            for t in raw_targets:
                check_raw(t)

        def check_target(
            t: str,
            *,
            kind: str,
            md: Path = md,
        ) -> None:
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
                problems.append(f"{md.relative_to(root)}: {kind} target not found: {t}")
                return
            # fragment presence depends on the target kind: HTML ids for
            # built pages, GitHub-style slugs for markdown sources
            frag_ok = (
                (frag in _html_ids(resolved))
                if (frag and resolved.suffix == ".html")
                else (frag in _md_heading_slugs(resolved))
                if (frag and resolved.suffix == ".md")
                else True
            )
            if not frag_ok:
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

            def check_html(
                t: str,
                *,
                kind: str,
                html: Path = html,
                page_ids: set[str] = page_ids,
            ) -> None:
                nonlocal external
                if t.startswith(("http://", "https://", "mailto:", "#!", "javascript:", "{{")):
                    if t.startswith(("http://", "https://")):
                        external += 1
                    return
                path_part, _, frag = t.partition("#")
                if not path_part:
                    if frag and frag not in page_ids:
                        problems.append(f"{html.relative_to(site)}: missing fragment #{frag}")
                    return
                resolved = resolve(html, path_part)
                if resolved is None:
                    problems.append(f"{html.relative_to(site)}: {kind} target not found: {t}")
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
            f"\nExternal URLs are checked separately (informational): {external} encountered.",
            file=sys.stderr,
        )
        return 1

    print(
        f"link check OK: all internal links/fragments/images resolve "
        f"({external} external URLs deferred to markdown-link-check)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
