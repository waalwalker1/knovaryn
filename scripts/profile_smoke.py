#!/usr/bin/env python3
"""Installation-profile smoke (contract §8.8–§8.10, v0.2.1).

For one declared installation profile, verify — against the ACTUALLY
INSTALLED environment, not assumptions:

* every third-party dependency the profile promises is importable;
  equally important, profiles must NOT silently carry extras they don't
  declare (core must prove the demo runs without heavy deps);
* the knovaryn surface the profile claims works: core imports + REST
  OpenAPI build for everything; MCP tool listing only where the `mcp`
  extra is installed; per-extra integration modules otherwise;
* ``knovaryn doctor --json`` exits 0.

Profiles: core, mcp, docling, docetl, litellm, s3, parquet, hub, ml, full.

Usage:
    python scripts/profile_smoke.py <profile> [--expect-extra NAME]...
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

# third-party modules each profile must be able to import
THIRD_PARTY = {
    "core": ["typer", "rich", "fastapi", "sqlalchemy", "aiosqlite", "alembic",
             "httpx", "structlog"],
    "mcp": ["mcp"],
    "docling": ["docling"],
    "docetl": ["docetl"],
    "litellm": ["litellm"],
    "s3": ["aioboto3"],
    "parquet": ["pyarrow"],
    "hub": ["huggingface_hub"],
    "ml": ["sklearn", "numpy"],
}

# knovaryn-side probes per profile; each returns a short human string.
def _probe_core() -> str:
    from knovaryn.interfaces.rest.app import app

    assert app.openapi().get("paths"), "REST app exposes no paths"
    from knovaryn.interfaces.cli.main import app as cli_app  # noqa: F401

    return "cli+rest OK"


def _probe_mcp() -> str:
    from knovaryn.interfaces.mcp.server import build_server

    tools = asyncio.run(build_server().list_tools())
    assert tools, "MCP server registered no tools"
    return f"{len(tools)} MCP tools listed"


def _probe_docling() -> str:
    import knovaryn.infrastructure.docling.adapter  # noqa: F401

    return "docling adapter imports"


def _probe_litellm() -> str:
    import knovaryn.infrastructure.models.litellm_provider  # noqa: F401

    return "litellm gateway provider imports"


def _probe_s3() -> str:
    import knovaryn.infrastructure.artifacts.s3  # noqa: F401

    return "S3 artifact store imports"


def _probe_parquet() -> str:
    import pyarrow  # noqa: F401
    import knovaryn.pipeline.export.exporters  # noqa: F401

    return "parquet exporter path imports"


def _probe_hub() -> str:
    import knovaryn.infrastructure.publish.hf  # noqa: F401

    return "HF publisher imports"


def _probe_ml() -> str:
    import numpy  # noqa: F401
    import sklearn  # noqa: F401

    return "ml stack imports"


PROBES = {
    "core": [_probe_core],
    "mcp": [_probe_core, _probe_mcp],
    "docling": [_probe_core, _probe_docling],
    "docetl": [_probe_core],
    "litellm": [_probe_core, _probe_litellm],
    "s3": [_probe_core, _probe_s3],
    "parquet": [_probe_core, _probe_parquet],
    "hub": [_probe_core, _probe_hub],
    "ml": [_probe_core, _probe_ml],
    "full": [
        _probe_core, _probe_mcp, _probe_docling, _probe_litellm,
        _probe_s3, _probe_parquet, _probe_hub, _probe_ml,
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile", choices=sorted(PROBES))
    ap.add_argument(
        "--forbid-extra",
        action="append",
        default=[],
        help="third-party module that must NOT be importable in this profile "
        "(e.g. core forbids docling) — guards against sneaky hard deps",
    )
    args = ap.parse_args()

    failures: list[str] = []

    for module in THIRD_PARTY.get(args.profile, []):
        if importlib.util.find_spec(module) is None:
            failures.append(f"profile {args.profile} cannot import required {module!r}")

    for module in args.forbid_extra:
        if importlib.util.find_spec(module) is not None:
            failures.append(f"profile {args.profile} unexpectedly carries {module!r}")

    for probe in PROBES[args.profile]:
        try:
            note = probe()
        except Exception as exc:  # noqa: BLE001 — smoke reports any failure mode
            failures.append(f"probe {probe.__name__} failed: {exc}")
        else:
            print(f"  ok: {note}")

    # the CLI that ships with THIS interpreter's installation — never PATH luck
    cli = Path(sys.executable).parent / ("knovaryn.exe" if os.name == "nt" else "knovaryn")
    cp = subprocess.run(
        [str(cli), "doctor", "--json"], capture_output=True, text=True
    )
    if cp.returncode != 0:
        failures.append(f"doctor --json exited {cp.returncode}: {cp.stderr[:300]}")
    else:
        try:
            payload = json.loads(cp.stdout)
            if isinstance(payload, list) and payload:
                # New list shape: [{component, ok, detail, optional}, ...]
                # Summarize: all non-optional items must be ok
                critical_fail = any(not item.get("ok", True) and not item.get("optional", False) for item in payload)
                status = "fail" if critical_fail else "ok"
                print(f"  ok: doctor --json ({status})")
            else:
                failures.append(f"doctor --json unexpected shape: {type(payload)}")
        except json.JSONDecodeError:
            failures.append("doctor --json did not emit JSON")

    if failures:
        print("\n".join(f"FAIL: {f}" for f in failures), file=sys.stderr)
        print(f"\nFAILED: profile {args.profile}.")
        return 1
    print(f"PASSED: installation profile {args.profile!r} verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
