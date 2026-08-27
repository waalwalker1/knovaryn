#!/usr/bin/env python3
"""Render every Mermaid diagram source to its committed PNG (contract §6.5).

Deterministic rendering: fixed background, fixed scale, mermaid-cli version
pinned by CI (see .github/workflows/assets.yml). Run after editing any
docs/assets/diagrams/*.mmd, then commit BOTH the source and the re-rendered
PNG in the same change.

Usage:
    python scripts/render_diagrams.py            # render all
    python scripts/render_diagrams.py --check    # verify committed PNGs match a fresh render

Requires ``mmdc`` (``@mermaid-js/mermaid-cli``) on PATH.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "docs" / "assets"
DIAGRAMS = ASSETS / "diagrams"

# stem → where the committed PNG lives
TARGETS = {
    "system-architecture": DIAGRAMS.parent / "system-architecture.png",
    "pipeline-flow": ASSETS / "pipeline-flow.png",
    "durable-jobs": ASSETS / "durable-jobs.png",
    "mcp-session": ASSETS / "mcp-session.png",
    "security": ASSETS / "security.png",
    "value-proposition": ASSETS / "value-proposition.png",
    "provenance-lineage": ASSETS / "provenance-lineage.png",
    "deployment-topology": ASSETS / "deployment-topology.png",
    "release-supply-chain": ASSETS / "release-supply-chain.png",
}


def _render(src: Path, dest: Path) -> None:
    cp = subprocess.run(
        ["mmdc", "-i", str(src), "-o", str(dest), "-b", "white", "-s", "2"],
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        sys.stderr.write(cp.stdout + cp.stderr)
        raise SystemExit(f"mmdc failed for {src.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="compare instead of writing")
    args = ap.parse_args()

    import hashlib
    import tempfile

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="knv-render-") as td:
        tmp = Path(td)
        for stem, target in TARGETS.items():
            # sources live under diagrams/, except pipeline-flow at assets root
            src = next(
                (p for p in (DIAGRAMS / f"{stem}.mmd", ASSETS / f"{stem}.mmd") if p.is_file()),
                None,
            )
            if src is None:
                failures.append(f"missing source diagrams/{stem}.mmd")
                continue
            fresh = tmp / f"{stem}.png"
            _render(src, fresh)
            new = hashlib.sha256(fresh.read_bytes()).hexdigest()
            if args.check:
                old = (
                    hashlib.sha256(target.read_bytes()).hexdigest()
                    if target.is_file()
                    else "<absent>"
                )
                if new != old:
                    failures.append(
                        f"{target.relative_to(target.parents[2])}: drifts from {src.name} "
                        "(run scripts/render_diagrams.py, then commit both)"
                    )
            else:
                target.write_bytes(fresh.read_bytes())
                print(f"rendered {target.relative_to(target.parents[2])}")

    if failures:
        print("\n".join(f"FAIL: {f}" for f in failures), file=sys.stderr)
        return 1
    print(
        "diagrams are in sync with their Mermaid sources" if args.check else "all diagrams rendered"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
