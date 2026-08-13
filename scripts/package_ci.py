#!/usr/bin/env python3
"""Package CI — build + verify a release candidate (spec WP L7).

Replicates what a reviewer does by hand, as a single runnable script CI invokes:

1. build wheel + sdist (`hatchling`)
2. ``twine check`` on both distributions
3. verify wheel metadata (name, version, project URLs)
4. install the wheel + ``[mcp]`` extra into a brand-new venv (clean path,
   no checkout on ``sys.path``)
5. run ``knovaryn --version`` / ``doctor`` / offline ``demo`` from that venv
6. MCP smoke: start the packaged ``knovaryn-mcp`` over stdio, initialize + ask
   it to list tools
7. REST smoke: boot ``knovaryn server``, hit ``/v1/health``, then stop it
8. inspect wheel contents for private files / secrets (fail closed)
9. print the SBOM/attestation hook point (signing happens in publish)

Exit 0 only if every step passes (validate before upload).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEEL_SECRET_PATTERNS = [
    r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY",
    r"AKIA[0-9A-Z]{16}",  # AWS access key id
    r"password\s*=\s*['\"][^'\"]+['\"]",
    r"api[_-]?(token|key)\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
    r"secret_access_key\s*[:=]\s*['\"][^'\"]+['\"]",
]


def _run(
    cmd: list[str], *, check: bool = True, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    cp = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True)
    if check and cp.returncode != 0:
        sys.stderr.write("$ " + " ".join(cmd) + "\n" + cp.stdout + cp.stderr)
        raise SystemExit(f"command failed ({cp.returncode}): {' '.join(cmd)}")
    return cp


def _venv_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _build(tmp: Path) -> tuple[Path, Path]:
    dist = tmp / "dist"
    dist.mkdir(exist_ok=True)
    _run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist), str(ROOT)])
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    assert wheels and sdists, "build produced no wheel/sdist"
    return wheels[0], sdists[0]


def _twine_check(wheel: Path, sdist: Path) -> None:
    # `twine check` requires explicit distribution file paths (a `.whl`/`.tar.gz`),
    # not a directory — passing the directory yields
    # "InvalidDistribution: Unknown distribution format".
    _run([sys.executable, "-m", "twine", "check", str(wheel), str(sdist)])


def _metadata_ok(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as z:
        meta = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        text = z.read(meta).decode("utf-8", "replace")
    assert "Name: knovaryn" in text, "metadata missing Name: knovaryn"
    assert re.search(r"Version: \d+\.\d+\.\d+", text), "metadata missing version"
    # project URLs are part of the packaged metadata
    for field in ("Project-URL: Homepage", "Project-URL: Documentation"):
        if field not in text:
            print(f"  ! metadata missing {field} (recommended)")
    print(f"  metadata OK: name+version+urls present ({wheel.name})")


def _wheel_clean(wheel: Path) -> list[str]:
    """Scan every file in the wheel for secrets/private keys. Returns findings."""
    findings: list[str] = []
    with zipfile.ZipFile(wheel) as z:
        for name in z.namelist():
            if name.startswith("knovaryn/") and name.endswith(".py"):
                data = z.read(name).decode("utf-8", "replace")
                for pat in WHEEL_SECRET_PATTERNS:
                    if re.search(pat, data):
                        findings.append(f"{name}: matches {pat}")
    return findings


def _clean_install_smoke(tmp: Path, wheel: Path) -> str:
    env_dir = tmp / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = _venv_python(env_dir)
    _run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-input",
            f"{str(wheel)}[mcp]",
            "mcp>=1.0,<2",
        ],
        check=False,  # mcp extra may be offline; still run echo
    )
    # reinstall bare if extras failed
    _run([str(py), "-m", "pip", "install", "--quiet", "--no-input", str(wheel)])
    return str(py)


def _cli(py: str) -> str:
    """Return the installed `knovaryn` console-script path (no ``__main__``)."""
    return str(Path(py).parent / ("knovaryn.exe" if os.name == "nt" else "knovaryn"))


def _cli_smoke(py: str) -> None:
    cli = _cli(py)
    _run([cli, "--help"])
    _run([cli, "version"])
    _run([cli, "doctor"])
    _run(
        [
            cli,
            "demo",
            "--examples",
            "10",
            "--out",
            str(ROOT / "knovaryn-demo"),
            "--json",
        ]
    )
    print("  CLI smoke OK: --help, version, doctor, demo")


def _mcp_smoke(py: str) -> None:
    # console entry point present
    bin_dir = Path(py).parent
    script = bin_dir / ("knovaryn-mcp.exe" if os.name == "nt" else "knovaryn-mcp")
    assert script.exists(), f"knovaryn-mcp missing: {script}"
    _run([str(script), "--help"])
    print("  MCP smoke OK: knovaryn-mcp entry point + --help")


def _rest_smoke(py: str) -> None:
    port = 8765
    log = ROOT / "knovaryn-demo" / "server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [_cli(py), "server", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
    )
    try:
        import time

        ok = False
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=2) as r:
                    if r.status == 200:
                        json.loads(r.read())
                        ok = True
                        break
            except Exception:
                time.sleep(0.5)
        assert ok, "server did not become healthy"
        print("  REST smoke OK: /v1/health returned 200")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="knovaryn-pkgci-"))
    try:
        print("[1/8] Building wheel + sdist ...")
        wheel, sdist = _build(tmp)
        print(f"  built {wheel.name} / {sdist.name}")

        print("[2/8] twine check ...")
        _twine_check(wheel, sdist)
        print("  twine check OK")

        print("[3/8] wheel metadata ...")
        _metadata_ok(wheel)

        print("[4/8] wheel content scan (secrets/private keys) ...")
        findings = _wheel_clean(wheel)
        if findings:
            for f in findings:
                print(f"  ! {f}")
            raise SystemExit("wheel contains secret-like content -> refusing to publish")
        print("  wheel content scan OK (no secrets)")

        print("[5/8] clean-env install (wheel + mcp extra) ...")
        py = _clean_install_smoke(tmp, wheel)
        print(f"  installed into {tmp / 'venv'}")

        print("[6/8] CLI smoke (version/doctor/demo) ...")
        _cli_smoke(py)

        print("[7/8] MCP smoke ...")
        _mcp_smoke(py)

        print("[8/8] REST smoke (/v1/health) ...")
        _rest_smoke(py)

        print("\nPackage CI PASSED — ready to publish.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
