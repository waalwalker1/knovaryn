#!/usr/bin/env python3
"""Build the deterministic demo workspace behind every product screenshot.

Creates an isolated temporary workspace, loads two synthetic permitted source
documents (authored for this pipeline, declared Apache-2.0/public), runs the
offline fake-provider pipeline through the real durable Workspace, then
freezes a dataset version and exports a checksummed release bundle. The web
console screenshots (capture_docs_screenshots.py) are taken against the
resulting state — nothing here is mocked or hand-painted.

Usage:
    uv run --no-sync python scripts/visuals/prepare_demo_state.py \
        [--workspace DIR] [--target 8]

Writes ``state.json`` into the workspace so downstream capture scripts (and
the server launched by launch_visual_demo.py) resolve the project, version,
and export handles without parsing CLI output twice.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Two synthetic documents authored for this demo pipeline. The content is
# original fixture text (no real product, provider, or person is described),
# carried in-repo under the project license and declared as such at intake.
SOURCE_HANDBOOK = """# Field handbook

## Collecting material

A foundry is only as trustworthy as its intake. Every document that enters
the workspace carries two declarations: the license it was obtained under,
and the privacy class of its contents. Both are recorded before parsing
begins, and both gate publication later.

## Chunking

Long documents are split at structural boundaries — headings first, then
paragraphs. Each chunk keeps the heading path it came from, an ordinal
position, and a content hash, so any sentence in a generated example can be
traced back to the exact span it was grounded in.

## Review

Rows the deterministic gates cannot confidently accept or reject are routed
to human review. A reviewer sees the prompt, the candidate answers, the
cited span, and the reason codes, then records a decision that is kept as an
immutable revision.
"""

SOURCE_RUNBOOK = """# Incident runbook

## First hour

When a pipeline run stalls, the job ledger is the first place to look: every
stage transition is checkpointed, so the interrupted stage resumes instead of
restarting the whole run. Failed stages quarantine their in-flight rows
rather than dropping them silently.

## Recovery

Recovery is idempotent. Re-running a job replays from the last checkpoint,
and content hashing ensures no row is processed twice. The run report lists
each stage with its counts, so a reviewer can see exactly what the recovery
changed.

## Audit

Every exported bundle ships with detached checksums and a manifest. Verifying
a release means re-hashing the artifact and comparing it to the manifest
sidecar — no trust in the transport required.
"""

# Pipeline shape: one task family, small target, deterministic offline
# profile. Counts are stable run to run; identifiers are time-derived.
FAMILIES = {"factual_explanation": 1.0}


def _cli(workspace: Path) -> list[str]:
    """Resolve the knovaryn CLI (workspace kept for signature symmetry).

    Order: $KNOVARYN_CLI (explicit override), the venv the current
    interpreter runs from, the project checkout's .venv, then $PATH. The
    override exists for checkouts on network-synced filesystems, where a
    local venv (fast imports) can be pointed at while the scripts stay in
    the synced tree.
    """
    override = os.environ.get("KNOVARYN_CLI")
    if override:
        return [override]
    in_venv = Path(sys.prefix) / "bin" / "knovaryn"
    if in_venv.exists():
        return [str(in_venv)]
    candidate = REPO_ROOT / ".venv" / "bin" / "knovaryn"
    if candidate.exists():
        return [str(candidate)]
    found = shutil.which("knovaryn")
    if found:
        return [found]
    raise SystemExit("knovaryn CLI not found — run inside the project venv")


def _run(workspace: Path, *args: str) -> dict:
    """Run one CLI command in the workspace; fail loudly on non-zero exit."""
    cmd = _cli(workspace) + list(args)
    proc = subprocess.run(
        cmd,
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return _json_or_empty(proc.stdout)


def _json_or_empty(stdout: str) -> dict:
    text = stdout.strip()
    if not text:
        return {}
    # CLI --json output is a single JSON document (may be pretty-printed).
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Rich console noise can precede the JSON; take from the first brace.
        start = text.find("{")
        if start == -1:
            raise
        return json.loads(text[start:])


def prepare(workspace: Path, target: int) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "sources").mkdir(exist_ok=True)

    (workspace / "sources" / "field-handbook.md").write_text(SOURCE_HANDBOOK)
    (workspace / "sources" / "incident-runbook.md").write_text(SOURCE_RUNBOOK)

    _run(workspace, "init", "--json")

    created = _run(
        workspace,
        "project",
        "create",
        "visual-demo",
        "--name",
        "Visual demo",
        "--description",
        "Synthetic two-document workspace used for the documented screenshots",
        "--json",
    )
    project_id = created.get("id") or created.get("project", {}).get("id")
    if not project_id:
        raise SystemExit(f"could not resolve project id from: {created}")

    for name in ("field-handbook.md", "incident-runbook.md"):
        _run(
            workspace,
            "source",
            "add",
            project_id,
            f"sources/{name}",
            "--license",
            "Apache-2.0",
            "--privacy",
            "public",
            "--json",
        )

    family_args = []
    for name, weight in FAMILIES.items():
        family_args += ["--family", f"{name}:{weight}"]
    _run(
        workspace,
        "run",
        "--project",
        project_id,
        *family_args,
        "--target",
        str(target),
        "--json",
    )

    validation = _run(workspace, "dataset", "validate", project_id, "--json")
    version = _run(workspace, "dataset", "version", project_id, "--json")
    version_id = version.get("version_id") or version.get("id") or version.get("semantic_version")
    export = _run(workspace, "dataset", "export", project_id, "--json")
    # The publish CLI exits 1 when a gate blocks or the hub extra is absent —
    # both are documented dry-run outcomes, and the JSON (gate verdict
    # included) is exactly what the screenshots narrate. Anything else is a
    # real failure.
    publish_proc = subprocess.run(
        _cli(workspace) + ["dataset", "publish", project_id, "local/visual-demo", "--json"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    publish_plan = _json_or_empty(publish_proc.stdout)
    if "publication_gate" not in publish_plan:
        raise SystemExit(
            f"publish dry-run failed unexpectedly ({publish_proc.returncode})\n"
            f"stdout:\n{publish_proc.stdout}\nstderr:\n{publish_proc.stderr}"
        )

    state = {
        "workspace": str(workspace),
        "project_id": project_id,
        "target_examples": target,
        "validation": validation,
        "version_id": version_id,
        "export": export,
        "publish_plan": publish_plan,
    }
    (workspace / "state.json").write_text(json.dumps(state, indent=2))
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace directory (default: fresh system-temp directory).",
    )
    parser.add_argument("--target", type=int, default=8, help="Target example count.")
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reuse an existing workspace instead of wiping it (development aid).",
    )
    args = parser.parse_args()

    workspace = args.workspace or Path(tempfile.mkdtemp(prefix="knovaryn-visual-"))
    if args.reuse and (workspace / "state.json").exists():
        print(json.dumps({"workspace": str(workspace), "reused": True}))
        return 0
    if workspace.exists():
        # Deterministic re-runs start clean unless explicitly reused.
        shutil.rmtree(workspace)
    state = prepare(workspace, args.target)
    print(json.dumps({"workspace": str(workspace), "project_id": state["project_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
