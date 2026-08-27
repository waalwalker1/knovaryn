#!/usr/bin/env python3
"""Create/update the repository labels referenced by automation config (§3.12).

Dependabot PRs silently lose their labels when the label doesn't exist in the
repository. This script is the owner-side companion to
``tests/test_dependency_governance.py`` (which proves every configured label
is *declared*): it makes the declared set *exist*, using the GitHub API via
the ``gh`` CLI.

Usage:
    python scripts/ensure_labels.py            # create missing, update colors/descriptions
    python scripts/ensure_labels.py --check    # exit 1 if any label is missing (no writes)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

LABELS_FILE = Path(__file__).resolve().parents[1] / ".github" / "labels.json"


def _gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def _existing_labels(repo: str | None) -> dict[str, dict[str, str]]:
    args = ["api", "repos/:owner/:repo/labels", "--paginate"]
    if repo:
        args += ["-R", repo]
    proc = _gh(args)
    out: dict[str, dict[str, str]] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out[rec["name"]] = {
            "color": rec.get("color", ""),
            "description": rec.get("description") or "",
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None, help="owner/name (default: gh's resolved repo)")
    ap.add_argument("--check", action="store_true", help="only verify presence; no writes")
    args = ap.parse_args()

    wanted = json.loads(LABELS_FILE.read_text(encoding="utf-8"))
    existing = _existing_labels(args.repo)

    missing = [w["name"] for w in wanted if w["name"] not in existing]
    if args.check:
        if missing:
            print(f"FAIL: labels not present in the repository: {missing}", file=sys.stderr)
            print("Run: python scripts/ensure_labels.py", file=sys.stderr)
            return 1
        print(f"OK: all {len(wanted)} automation labels exist")
        return 0

    failed = False
    for label in wanted:
        name, color, desc = label["name"], label["color"], label.get("description", "")
        try:
            if name not in existing:
                _gh(["label", "create", name, "--color", color, "--description", desc])
                print(f"created {name}")
            elif existing[name].get("color") != color.lstrip("#"):
                _gh(["label", "edit", name, "--color", color, "--description", desc])
                print(f"updated {name}")
            else:
                print(f"ok {name}")
        except subprocess.CalledProcessError as exc:
            failed = True
            print(f"FAIL {name}: {exc.stderr.strip()}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
