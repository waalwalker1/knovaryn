"""MCP acceptance matrix (defect 3.1, v0.2.1) — the executable proof behind
the ``mcp>=1.28,<3`` dependency claim.

For every pinned SDK version in ``MATRIX`` this script:

1. builds the knovaryn wheel once (``python -m build --wheel``),
2. creates a CLEAN virtualenv per version and installs the wheel plus the
   exact ``mcp`` pin,
3. runs ``scripts/mcp_acceptance_driver.py`` inside that venv through the
   mandatory phases — version check, full stdio lifecycle (tool/resource
   discovery, project, source, pipeline, preview, lineage, thread-leak
   check), authenticated Streamable HTTP round trip + 401 refusal, and the
   non-loopback bind refusal,
4. fails the matrix when any phase fails OR when the installed ``mcp``
   version differs from the pin (the recorded-version requirement).

Exit code 0 means every matrix cell passed. ``--matrix`` limits the pins
(e.g. ``--matrix 2.0.0``), ``--skip-build`` reuses ``--wheel-path``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIVER = Path(__file__).resolve().parent / "mcp_acceptance_driver.py"

# The intended matrix. Must stay in lockstep with SUPPORTED_MCP_MAJORS in
# src/knovaryn/interfaces/mcp/_compat.py and the pyproject range mcp>=1.28,<3.
MATRIX: tuple[str, ...] = ("1.29.0", "2.0.0")


def _bin(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def _run(cmd: list[str], *, timeout: float, env: dict[str, str] | None = None,
         cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, timeout=timeout,
        env=env, cwd=str(cwd) if cwd else None,
    )
    return proc


def build_wheel(outdir: Path) -> Path:
    print(f"[matrix] building wheel into {outdir} ...", flush=True)
    proc = _run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir)],
        timeout=600, cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"[matrix] wheel build failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    wheels = sorted(outdir.glob("knovaryn-*.whl"))
    if not wheels:
        raise SystemExit("[matrix] wheel build produced no wheel")
    wheel = wheels[-1]
    print(f"[matrix] built {wheel.name}", flush=True)
    return wheel


def make_venv(parent: Path, name: str, wheel: Path, pin: str) -> Path:
    venv_dir = parent / name
    builder = venv.EnvBuilder(with_pip=True, clear=True)
    builder.create(venv_dir)
    py = _bin(venv_dir) / "python"
    print(f"[matrix] venv {name}: installing {wheel.name} + mcp=={pin} ...", flush=True)
    proc = _run(
        [str(py), "-m", "pip", "install", "--quiet", "--no-input",
         str(wheel), f"mcp=={pin}"],
        timeout=600,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"[matrix] pip install failed for {name}:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
    return venv_dir


def run_phase(venv_dir: Path, phase: str, extra: list[str], timeout: float,
              env_overrides: dict[str, str] | None = None) -> dict:
    py = str(_bin(venv_dir) / "python")
    env = {**os.environ}
    if env_overrides:
        env.update(env_overrides)
    proc = _run([py, str(DRIVER), phase, *extra], timeout=timeout, env=env)
    if proc.returncode != 0:
        tail = (proc.stdout or "")[-1500:] + (proc.stderr or "")[-1500:]
        return {"ok": False, "error": tail}
    try:
        return {"ok": True, **json.loads(proc.stdout.strip().splitlines()[-1])}
    except (ValueError, IndexError):
        return {"ok": False, "error": f"unparseable driver output: {proc.stdout[-500:]}"}


def run_cell(pin: str, wheel: Path, parent: Path, port: int) -> dict:
    name = f"mcp-{pin}"
    venv_dir = make_venv(parent, name, wheel, pin)
    cell: dict = {"pin": pin, "venv": str(venv_dir), "phases": {}}

    # Phase 1: record the installed SDK version; fail on mismatch (contract:
    # "record the installed mcp version and fail when it differs").
    ver = run_phase(venv_dir, "version", [], 60)
    cell["phases"]["version"] = ver
    installed = ver.get("mcp")
    ver["version_match"] = installed == pin
    if installed != pin:
        ver["ok"] = False
        ver["error"] = f"installed mcp {installed!r} != intended {pin!r}"

    # Phase 2: full stdio lifecycle on a fresh sqlite database.
    db = parent / f"{name}.db"
    stdio = run_phase(
        venv_dir, "stdio",
        ["--database-url", f"sqlite+aiosqlite:///{db}"], 420,
    )
    cell["phases"]["stdio"] = stdio

    # Phase 3: authenticated streamable-http round trip + 401 refusal.
    http = run_phase(
        venv_dir, "http", ["--port", str(port), "--token", f"tok-{pin}"], 180,
    )
    cell["phases"]["http"] = http

    # Phase 4: non-loopback bind refusal without a token.
    bind = run_phase(venv_dir, "bind-refusal", [], 90)
    cell["phases"]["bind-refusal"] = bind

    cell["ok"] = all(p.get("ok") for p in cell["phases"].values())
    return cell


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", nargs="*", default=list(MATRIX),
                        help="Pins to test (default: full matrix).")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--wheel-path", type=Path, default=None)
    parser.add_argument("--keep", action="store_true",
                        help="Keep the scratch venvs for debugging.")
    args = parser.parse_args()

    scratch = Path(tempfile.mkdtemp(prefix="knovaryn-mcp-matrix-"))
    print(f"[matrix] scratch: {scratch}", flush=True)
    try:
        if args.skip_build and args.wheel_path:
            wheel = args.wheel_path.resolve()
        else:
            wheel = build_wheel(scratch / "dist")

        ports = iter(range(8931, 8931 + 10 * len(args.matrix), 10))
        cells = []
        for pin in args.matrix:
            print(f"[matrix] === cell mcp=={pin} ===", flush=True)
            try:
                cells.append(run_cell(pin, wheel, scratch, next(ports)))
            except SystemExit as e:  # pip/build failure inside the cell
                cells.append({"pin": pin, "ok": False, "error": str(e)})
            except subprocess.TimeoutExpired as e:
                cells.append({"pin": pin, "ok": False, "error": f"timeout: {e}"})

        print("\n[matrix] RESULT")
        all_ok = True
        for cell in cells:
            status = "PASS" if cell.get("ok") else "FAIL"
            all_ok &= bool(cell.get("ok"))
            print(f"  mcp=={cell['pin']}: {status}")
            if not cell.get("ok") and not cell.get("phases"):
                # cell-level failure (venv/pip/build) before any phase ran
                print("      " + str(cell.get("error", "unknown error"))[-1200:])
            for phase, result in cell.get("phases", {}).items():
                mark = "ok" if result.get("ok") else "FAILED"
                line = f"    {phase}: {mark}"
                if phase == "version" and result.get("ok"):
                    line += f" (installed {result.get('mcp')}, match={result.get('version_match')})"
                if phase == "stdio" and result.get("ok"):
                    line += (f" (tools={result.get('tool_count')}, "
                             f"templates={result.get('resource_templates')}, "
                             f"examples={result.get('example_count')}, "
                             f"leaked={result.get('leaked_threads')})")
                print(line)
                if not result.get("ok"):
                    print("      " + (result.get("error") or "")[-1200:].replace("\n", "\n      "))
        print(f"[matrix] {'ALL CELLS PASS' if all_ok else 'MATRIX FAILED'}")
        return 0 if all_ok else 1
    finally:
        if args.keep:
            print(f"[matrix] scratch kept: {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
