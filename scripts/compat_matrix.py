#!/usr/bin/env python3
"""Breaking-dependency compatibility matrix (contract §8.3–§8.4, v0.2.1).

For each dependency group that has broken Knovaryn-class applications before
(MCP SDK, the FastAPI/Starlette/httpx REST stack, SQLAlchemy/aiosqlite,
Docling), install the FLOOR version declared in ``pyproject.toml`` alongside
the current source tree into an isolated venv and run a real smoke probe
against what was installed. Floors are parsed from the live constraints —
there are no hard-coded version numbers here to go stale, and a widened
range must widen its floor test with it.

The latest end of every range is exercised continuously by normal CI plus
Dependabot PRs; this matrix exists so the *minimum* support claim is tested,
not merely asserted.

Usage:
    python scripts/compat_matrix.py                 # every group
    python scripts/compat_matrix.py --group mcp     # one group

Exits non-zero if any floor install or probe fails.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# package name (normalized) → probe run with the group's venv python.
# Probes exercise the real integration surface, not just `import`.
GROUP_PROBES: dict[str, dict[str, str]] = {
    # MCP SDK floor: a real server lifecycle must work end to end.
    "mcp": {
        "mcp": (
            "import asyncio; from knovaryn.interfaces.mcp.server import build_server; "
            "tools = asyncio.run(build_server().list_tools()); assert tools, 'no tools'"
        ),
    },
    # REST stack floor: the app must build its OpenAPI schema and serve over
    # an ASGI transport constructed with the installed httpx.
    "rest": {
        "fastapi": (
            "from knovaryn.interfaces.rest.app import app; "
            "assert app.openapi().get('paths'), 'no OpenAPI paths'"
        ),
        "httpx": (
            "import httpx; from knovaryn.interfaces.rest.app import app; "
            "httpx.AsyncClient(transport=httpx.ASGITransport(app=app))"
        ),
    },
    # Database floor: a real async round-trip through the pinned pair.
    # `async def` is a compound statement — it cannot follow a semicolon in
    # a `-c` one-liner, so the imports get real newlines.
    "database": {
        "sqlalchemy": (
            "import asyncio\n"
            "import sqlalchemy as sa\n"
            "from sqlalchemy.ext.asyncio import create_async_engine\n"
            "async def main():\n"
            "    e = create_async_engine('sqlite+aiosqlite:///:memory:')\n"
            "    async with e.connect() as c:\n"
            "        assert (await c.execute(sa.select(1))).scalar() == 1\n"
            "    await e.dispose()\n"
            "asyncio.run(main())"
        ),
        "aiosqlite": None,  # exercised by the sqlalchemy probe's driver path
    },
    # Parser floor: the adapter module must import against the pinned docling.
    "docling": {
        "docling": (
            "import importlib.util as iu; assert iu.find_spec('docling'), 'docling missing'; "
            "import knovaryn.infrastructure.docling.adapter"
        ),
    },
}

# extras each group needs installed with the project
GROUP_EXTRAS: dict[str, str] = {
    "mcp": "mcp",
    "rest": "",
    "database": "",
    "docling": "docling",
}

_FLOOR_RE = re.compile(r">\s*=\s*([0-9][0-9A-Za-z.\-+*!]*)")


def _declared_constraints() -> dict[str, str]:
    """Normalized package name → its full requirement string from pyproject."""
    with open(ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    project = data["project"]
    reqs: list[str] = list(project.get("dependencies", []))
    for extra_reqs in project.get("optional-dependencies", {}).values():
        reqs.extend(extra_reqs)
    out: dict[str, str] = {}
    for req in reqs:
        m = re.match(r"\s*([A-Za-z0-9_.\-]+)\s*(.*)", req)
        if m:
            out[m.group(1).lower().replace("_", "-")] = req.strip()
    return out


def _floor(requirement: str, package: str) -> str:
    """Extract the declared lower bound as a `name==version` pin."""
    m = _FLOOR_RE.search(requirement)
    if not m:
        raise SystemExit(
            f"FAIL: watched package {package!r} has no explicit floor in "
            f"pyproject.toml ({requirement!r}); the compatibility matrix needs one"
        )
    return f"{package}=={m.group(1).rstrip('.*!')}"


def _run(cmd: list[str]) -> None:
    cp = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if cp.returncode != 0:
        sys.stderr.write("$ " + " ".join(cmd) + "\n" + cp.stdout[-2000:] + cp.stderr[-2000:])
        raise SystemExit(f"command failed ({cp.returncode}): {' '.join(cmd)}")


def _venv_python(env_dir: Path) -> str:
    return str(env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python"))


def check_group(group: str, constraints: dict[str, str], tmp: Path) -> None:
    packages = GROUP_PROBES[group]
    missing = [p for p in packages if p not in constraints]
    if missing:
        raise SystemExit(f"FAIL: group {group} watches undeclared packages: {missing}")

    env_dir = tmp / f"compat-{group}"
    venv.create(env_dir, with_pip=True)
    py = _venv_python(env_dir)

    extra = GROUP_EXTRAS[group]
    spec = f".[{extra}]" if extra else "."
    print(f"[{group}] installing project ({spec}) into {env_dir.name} …")
    _run([py, "-m", "pip", "install", "--quiet", "--no-input", spec])

    for package, _probe in packages.items():
        pin = _floor(constraints[package], package)
        print(f"[{group}] pinning floor {pin}")
        _run([py, "-m", "pip", "install", "--quiet", "--no-input", pin])

    for package, probe in packages.items():
        if probe is None:
            print(f"[{group}] {package}: covered by a sibling probe")
            continue
        cp = subprocess.run([py, "-c", probe], cwd=ROOT, capture_output=True, text=True)
        if cp.returncode != 0:
            sys.stderr.write(cp.stdout[-2000:] + cp.stderr[-2000:])
            raise SystemExit(f"FAIL: probe for {group}/{package} failed at its floor version")
        print(f"[{group}] {package}: floor probe PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--group",
        action="append",
        choices=sorted(GROUP_PROBES),
        help="restrict to one group (repeatable; default all)",
    )
    args = ap.parse_args()

    constraints = _declared_constraints()
    tmp = Path(tempfile.mkdtemp(prefix="knovaryn-compat-"))
    failures: list[str] = []
    for group in args.group or sorted(GROUP_PROBES):
        try:
            check_group(group, constraints, tmp)
        except SystemExit as exc:
            failures.append(f"{group}: {exc}")
    if failures:
        print("\nFAILED groups:\n- " + "\n- ".join(failures), file=sys.stderr)
        return 1
    print("\nAll dependency floors hold: compatibility matrix PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
