#!/usr/bin/env python3
"""Branch-coverage gate for the core code (spec WP L3).

Enforces, against the offline suite:

1. An overall branch-coverage floor across the core packages
   (``knovaryn.domain``, ``knovaryn.application``, ``knovaryn.pipeline``,
   ``knovaryn.interfaces``).
2. No *critical* core module below ``MODULE_FLOOR`` percent branch coverage
   without a documented reason in ``EXEMPTIONS``.

The gate reports exact measured numbers and only fails on (a) the overall door
dropping below ``CORE_FLOOR``, or (b) a regression where an exempt module falls
further, or a non-exempt core module is under the floor. It is deliberately
honest: modules currently below the floor carry a documented reason rather than
a fudged count (L3: prioritize semantic tests over raw percentage).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Offline suite only — live/gated services are never required for the gate.
OFFLINE = (
    "-m",
    "not live and not live-provider and not release and not docling and "
    "not docetl and not postgres and not s3 and not browser",
)

CORE_PACKAGES = [
    "knovaryn.domain",
    "knovaryn.application",
    "knovaryn.pipeline",
    "knovaryn.interfaces",
]

CORE_FLOOR = 75.0  # overall branch floor across the core packages
MODULE_FLOOR = 80.0  # per critical-module branch floor

# Modules legitimately below MODULE_FLOOR today, with the documented reason that
# justifies the exemption (L3: "no critical module under 80% without a
# documented reason"). Values are the *measured* baseline; a drop below baseline
# fails the gate.
EXEMPTIONS = {
    "src/knovaryn/domain/config.py": 46.0,  # env/file/admin resolution paths + CLI provenance helpers
    "src/knovaryn/domain/ports.py": 0.0,  # abstract interface definitions (no runtime branches)
    "src/knovaryn/domain/ids.py": 73.0,  # entropy-fallback branches (UUID4 vs random) + legacy id forms
    "src/knovaryn/pipeline/export/exporters.py": 61.0,  # several legacy writer variants superseded by formats.py
    "src/knovaryn/pipeline/generate.py": 70.0,  # provider error/refusal + budget branches (live-gated)
    "src/knovaryn/pipeline/quality/artifact.py": 57.0,  # heuristic artifact classification edge cases
    "src/knovaryn/pipeline/quality/reports.py": 78.0,  # quality-report rendering edge branches
    "src/knovaryn/pipeline/split.py": 73.0,  # grouped/stratified split edge branches
    "src/knovaryn/pipeline/jobs/engine.py": 79.0,  # lease-expiry + crash-recovery branches (gated live/chaos)
    # Entry-point glue: declarative (typer/uvicorn/MCP stdio) wiring whose fixed
    # setup+branch overhead is thin, not semantic — branch % understates its
    # value and is covered structurally by CLI/MCP/REST smoke (L2/L7).
    "src/knovaryn/interfaces/cli/main.py": 41.0,
    "src/knovaryn/interfaces/cli/commands.py": 71.0,
    "src/knovaryn/interfaces/mcp/__main__.py": 26.0,
    "src/knovaryn/interfaces/mcp/server.py": 75.0,
    "src/knovaryn/interfaces/rest/app.py": 60.0,  # live ASGI server + lifespan paths
}


def _run_coverage() -> list[str]:
    cmd: list[str] = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        *OFFLINE,
    ]
    # one --cov flag per package (a comma-joined string is treated as a single
    # module name and coverage emits "never imported")
    for pkg in CORE_PACKAGES:
        cmd += ["--cov", pkg]
    cmd += ["--cov-branch", "--cov-report=term-missing"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        # A coverage number measured over a failing or interrupted suite is not
        # evidence (L3). Exit code 1 was tolerated before, which could hide a
        # red suite behind a green-looking table — the CI run of 2026-08-21
        # measured semantic.py at its pre-fix coverage while the identical
        # unfiltered suite passed, and nothing in the log could say why. The
        # suite must be green for the gate's numbers to count, and the summary
        # must be visible so CI logs show what actually ran.
        print(out[-4000:], file=sys.stderr)
        raise SystemExit(
            f"offline suite did not pass cleanly (pytest rc={proc.returncode}); "
            "coverage numbers from a red suite are not evidence"
        )
    # Always show the pytest summary so CI logs record what ran (passed /
    # skipped / deselected counts) — the gate's own table alone cannot.
    tail = [ln for ln in out.splitlines() if ln.strip()][-15:]
    print("\n".join(tail) + "\n")
    return [ln for ln in out.splitlines() if "%" in ln]


def _parse(table: list[str]) -> dict[str, float]:
    """Return {module_rel_path: branch_cover_pct} from the term-missing table.

    Column layout is ``Name Stmts Miss Branch BrPart Cover Missing``, so the
    coverage percent is the 6th token (index 5) — ``Missing`` line numbers follow
    it and must not be mistaken for the percentage.
    """
    result: dict[str, float] = {}
    for line in table:
        parts = line.split()
        if len(parts) < 6:
            continue
        cover = parts[5]
        if not cover.endswith("%"):
            continue
        try:
            pct = float(cover.rstrip("%"))
        except ValueError:
            continue
        name = parts[0]
        # normalize to `src/knovaryn/...` in case coverage reports a relative depth
        if name.startswith("src/knovaryn/"):
            result[name] = pct
        elif name.startswith("knovaryn/"):
            result["src/" + name] = pct
    return result


def main() -> int:
    print(f"Running offline suite with branch coverage on {', '.join(CORE_PACKAGES)} ...\n")
    table = _run_coverage()
    cov = _parse(table)

    if not cov:
        print("ERROR: no module coverage rows captured.")
        return 1

    # overall door across core packages (from the TOTAL row)
    total_line = scan_total(table)
    overall = total_line[0] if total_line else sum(cov.values()) / len(cov)
    print(f"Core overall branch coverage: {overall:.1f}%  (floor {CORE_FLOOR:.0f}%)\n")

    failures: list[str] = []
    if overall < CORE_FLOOR:
        failures.append(f"overall core branch coverage {overall:.1f}% < {CORE_FLOOR:.0f}%")

    # per-module floor + regression check
    print(f"{'module':55} {'branch%':>8} {'floor':>7}  status")
    for name in sorted(cov):
        pct = cov[name]
        exempt_base = EXEMPTIONS.get(name)
        if exempt_base is not None:
            floor = min(exempt_base, MODULE_FLOOR)  # hold the documented baseline
            status = (
                "ok (documented)" if pct >= floor else f"REGRESSION below documented {floor:.0f}%"
            )
        else:
            floor = MODULE_FLOOR
            status = "ok" if pct >= floor else f"below {floor:.0f}% — no documented exemption"
        print(f"{name:55} {pct:7.1f}% {floor:6.0f}%  {status}")
        if pct < floor:
            failures.append(f"{name}: {pct:.1f}% < {floor:.0f}%")

    print()
    if failures:
        print("Coverage gate FAILED:")
        for f in failures:
            print(f"  - {f}")
        # Show the raw term-missing rows for failing modules: the exact
        # unexecuted lines are the diagnostic (e.g. async test bodies that
        # never ran on a given runner).
        fail_names = {f.split(":")[0] for f in failures}
        print("\nRaw coverage rows (Name ... Cover Missing) for failing modules:")
        for ln in table:
            parts = ln.split()
            if parts and parts[0] in fail_names:
                print(f"  {ln.strip()}")
        return 1
    print("Coverage gate passed.")
    return 0


def scan_total(table: list[str]) -> list[float]:
    """Return [overall %] if the TOTAL row is present (percent at column 5)."""
    for line in table:
        parts = line.split()
        if parts and parts[0] == "TOTAL" and len(parts) >= 6 and parts[5].endswith("%"):
            try:
                return [float(parts[5].rstrip("%"))]
            except ValueError:
                return []
    return []


if __name__ == "__main__":
    sys.exit(main())
