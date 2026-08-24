"""Knovaryn command-line interface (spec §17.1).

The CLI exposes a fully offline demo plus project/intake commands. It wires the
framework-free :class:`ProjectService` and never requires model credentials for
the default ``demo`` path (fake provider).
"""

from __future__ import annotations

import asyncio
import enum
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ...domain.ids import IdGenerator
from ...domain.schemas import DatasetPlan, Project, SourceDocument, SourceKind

app = typer.Typer(name="knovaryn", help="Open, MCP-native training-data foundry.")
console = Console()

_DEMO_SOURCES = [
    (
        "MLOps lifecycle overview",
        """# MLOps Lifecycle
## Data preparation
Data preparation is the first step of any machine learning project. It involves
collecting raw data, cleaning it, and transforming it into a usable format.
Practitioners must document the provenance of every data source to keep the
dataset auditable.
## Model training
Model training consumes the prepared data. The training process optimizes model
weights against a loss function. Hyperparameters such as the learning rate and
batch size materially affect the final model quality.
## Evaluation
Evaluation measures model performance on held-out data. A held-out test set must
never be used to tune hyperparameters, because doing so leaks signal and inflates
reported accuracy.
## Deployment and monitoring
Once deployed, models require ongoing monitoring for drift. Concept drift occurs
when the statistical properties of the input distribution change over time,
degrading performance even when the model is unchanged.""",
    ),
    (
        "Incident response runbook",
        """# Incident Response Runbook
## Triage
Upon receiving an alert, the on-call engineer first confirms the alert is genuine
and not a false positive. The engineer classifies severity as low, medium, high,
or critical.
## Containment
Containment isolates the affected component to prevent further damage. For a
compromised service, this may mean rotating credentials and removing network
egress.
## Recovery
Recovery restores service from a known-good backup. The team verifies data
integrity before declaring recovery complete.
## Postmortem
A blameless postmortem documents the incident timeline, root cause, and
corrective actions. The report is shared with the whole engineering organization.""",
    ),
]


def _version() -> str:
    """Installed distribution version, falling back to the package constant.

    The stale-hardcoded-"0.1.0"-fallback class of bug (defect 3.5) is gone:
    ``knovaryn.__version__`` is the authoritative source (pyproject consumes
    it at build time), so a missing dist-metadata entry can never resurrect
    an old release number.
    """
    try:
        from importlib.metadata import version

        return version("knovaryn")
    except Exception:  # noqa: BLE001
        from ... import __version__

        return __version__


@app.command("demo")
def demo(
    out: Path = typer.Option(
        Path("knovaryn-demo"), "--out", "-o", help="Output dir for the release bundle."
    ),
    examples: int = typer.Option(1200, "--examples", help="Maximum dataset examples."),
    json_plain: bool = typer.Option(False, "--json", help="Print machine-readable result."),
) -> None:
    """Run the fully-offline end-to-end pipeline on bundled sample documents."""

    from ...application.service import ProjectService

    ids = IdGenerator()
    project = Project(
        id=ids.new_handle("proj"), slug="demo", display_name="Knovaryn Demo", owner_principal="cli"
    )
    plan = DatasetPlan(
        target_audience="ML engineers",
        task_family_proportions={"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2},
        difficulty_distribution={"basic": 0.3, "intermediate": 0.5, "advanced": 0.2},
        maximum_dataset_size=examples,
    )
    sources: list[SourceDocument] = []
    contents: list[str] = []
    for name, text in _DEMO_SOURCES:
        sources.append(
            SourceDocument(
                id=ids.new_handle("src"),
                project_id=project.id,
                original_name=name,
                media_type="text/markdown",
                byte_size=len(text.encode("utf-8")),
                sha256=ids.new_handle("digest"),
                source_kind=SourceKind.local_path,
                group_key=name,
            )
        )
        contents.append(text)

    svc = ProjectService(ids=ids)
    result = asyncio.run(
        svc.run_pipeline(project=project, sources=sources, contents=contents, plan=plan)
    )

    out.mkdir(parents=True, exist_ok=True)
    bundle_path = out / "release.zip"
    bundle_path.write_bytes(result.release_bundle_bytes)
    (out / "result.json").write_text(json.dumps(result.to_dict(), indent=2))

    if json_plain:
        console.print_json(json.dumps(result.to_dict()))
        return

    table = Table(title=f"Knovaryn offline demo — {_version()}")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Sources parsed", str(len(result.parsed)))
    table.add_row("Chunks produced", str(len(result.chunks)))
    table.add_row("Examples generated", str(len(result.examples)))
    table.add_row(
        "Accepted", str(sum(1 for e in result.examples if e.quality_status.value == "accepted"))
    )
    table.add_row("Quality report", json.dumps(result.quality.get("status_counts", {})))
    table.add_row("Version", str(result.version.semantic_version if result.version else "n/a"))
    table.add_row("Release bundle", str(bundle_path))
    table.add_row("Bundle sha256", result.release_sha256)
    console.print(table)
    for note in result.notes:
        console.print(f"[dim]{note}[/dim]")


@app.command("doctor")
def doctor(
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Check environment, configuration, and storage health (non-zero exit on failure)."""
    from .commands import doctor as _doctor

    raise typer.Exit(_doctor(json_plain=json_plain))


@app.command("repair")
def repair(
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Verify database integrity and reconcile missing artifact blobs."""
    from .commands import repair as _repair

    raise typer.Exit(_repair(json_plain=json_plain))


@app.command("backup")
def backup(
    out: Path = typer.Option(
        Path("knovaryn-backups"), "--out", "-o", help="Backup output directory."
    ),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Snapshot the local state directory into a timestamped archive."""
    from .commands import backup as _backup

    raise typer.Exit(_backup(out=out, json_plain=json_plain))


@app.command("restore")
def restore(
    archive: Path = typer.Option(..., "--from", "-f", help="Backup archive to restore."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Restore a ``backup`` archive into the configured state directory.

    Verifies the restored database integrity; refuses to overwrite a non-empty
    state directory (WP K5 backup/restore).
    """
    from .commands import restore as _restore

    raise typer.Exit(_restore(archive=archive, json_plain=json_plain))


@app.command("server")
def server(
    host: str | None = typer.Option(None, "--host", help="Bind host (default from config)."),
    port: int | None = typer.Option(None, "--port", "-p", help="Bind port (default from config)."),
    reload: bool = typer.Option(False, "--reload", help="Enable uvicorn auto-reload (dev)."),
) -> None:
    """Serve the offline REST API + web console (bearer-token aware)."""
    from .commands import server as _server

    raise typer.Exit(_server(host=host, port=port, reload=reload))


@app.command("worker")
def worker(
    worker_id: str = typer.Option("w1", "--id", help="This worker's identifier."),
    poll: float = typer.Option(1.0, "--poll", help="Poll interval in seconds."),
    lease: int = typer.Option(300, "--lease", help="Lease duration in seconds."),
    max_attempts: int = typer.Option(3, "--max-attempts", help="Per-stage retry attempts."),
    once: bool = typer.Option(
        False, "--once", help="Poll once (drain one job) and exit — for scripts/tests."
    ),
    database_url: str | None = typer.Option(
        None, "--database-url", help="Override the database URL."
    ),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Run a durable background worker (claim → lease → checkpoint → resume)."""
    from .commands import worker as _worker

    raise typer.Exit(
        _worker(
            worker_id=worker_id,
            poll_interval_s=poll,
            lease_seconds=lease,
            max_attempts=max_attempts,
            once=once,
            database_url=database_url,
            json_plain=json_plain,
        )
    )


@app.command("mcp")
def mcp_cmd(
    transport: str = typer.Option(
        "stdio", "--transport", help="MCP transport: stdio (default) or streamable-http."
    ),
    host: str | None = typer.Option(None, "--host", help="Bind host for streamable-http."),
    port: int | None = typer.Option(None, "--port", "-p", help="Bind port for streamable-http."),
    database_url: str | None = typer.Option(
        None, "--database-url", help="Override the database URL."
    ),
) -> None:
    """Run the Knovaryn MCP server (stdio by default).

    ``knovaryn-mcp`` is the packaged console entry point (WP F1); this command
    is the equivalent subcommand so a single ``knovaryn`` binary serves both
    the CLI and the MCP surface.
    """
    from ...interfaces.mcp.__main__ import main as _mcp_main

    argv = [f"--transport={transport}"]
    if host is not None:
        argv.append(f"--host={host}")
    if port is not None:
        argv.append(f"--port={port}")
    if database_url is not None:
        argv.append(f"--database-url={database_url}")
    raise typer.Exit(_mcp_main(argv))


@app.command("verify-release")
def verify_release(
    path: Path = typer.Argument(..., help="Path to a release.zip bundle."),
) -> None:
    """Verify a release bundle's detached checksum + per-file manifest (I5)."""
    from .commands import verify_release as _verify_release

    raise typer.Exit(_verify_release(path=str(path)))


@app.command("version")
def version_cmd() -> None:
    """Print the installed version."""
    console.print(f"knovaryn {_version()}")


# ---------------------------------------------------------------------------
# Project lifecycle (defect 3.4): every documented command delegates to the
# same Workspace application services the MCP/REST surfaces use, so the CLI
# can never advertise a pipeline the code does not run.
# ---------------------------------------------------------------------------

class _ReviewChoice(str, enum.Enum):
    approve = "approve"
    reject = "reject"
    needs_work = "needs_work"


@app.command("init")
def init_cmd(
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Initialize the local state directory and verify configuration loads."""
    from .commands import init_state as _init_state

    raise typer.Exit(_init_state(json_plain=json_plain))


project_app = typer.Typer(help="Create and inspect projects.", no_args_is_help=True)
app.add_typer(project_app, name="project")


@project_app.command("create")
def project_create_cmd(
    slug: str = typer.Argument(..., help="Unique project slug."),
    display_name: str = typer.Option("", "--name", help="Human-readable name."),
    description: str = typer.Option("", "--description", help="Project description."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Create a new project."""
    from .commands import project_create as _f

    raise typer.Exit(
        _f(slug=slug, display_name=display_name, description=description, json_plain=json_plain)
    )


@project_app.command("list")
def project_list_cmd(
    limit: int = typer.Option(50, "--limit", help="Maximum projects to show."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List projects visible to the CLI principal."""
    from .commands import project_list as _f

    raise typer.Exit(_f(limit=limit, json_plain=json_plain))


source_app = typer.Typer(help="Register and inspect source documents.", no_args_is_help=True)
app.add_typer(source_app, name="source")


@source_app.command("add")
def source_add_cmd(
    project_id: str = typer.Argument(..., help="Target project handle (proj_…)."),
    path: Path = typer.Argument(..., help="File to ingest (text or binary; type is sniffed)."),
    license: str | None = typer.Option(None, "--license", help="Declared source license (SPDX id)."),
    privacy: str | None = typer.Option(None, "--privacy", help="Privacy classification."),
    group: str | None = typer.Option(None, "--group", help="Source group key."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Register a local file through the secure intake funnel."""
    from .commands import source_add as _f

    raise typer.Exit(
        _f(
            project_id=project_id,
            path=path,
            license=license,
            privacy=privacy,
            group=group,
            json_plain=json_plain,
        )
    )


@source_app.command("list")
def source_list_cmd(
    project_id: str = typer.Argument(..., help="Project handle (proj_…)."),
    limit: int = typer.Option(100, "--limit", help="Maximum sources to show."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List a project's registered source documents."""
    from .commands import source_list as _f

    raise typer.Exit(_f(project_id=project_id, limit=limit, json_plain=json_plain))


@app.command("run")
def run_cmd(
    project_id: str = typer.Option(..., "--project", "-p", help="Project handle (proj_…)."),
    family: str | None = typer.Option(
        None, "--family", help='Task family proportion as NAME:WEIGHT (e.g. factual_explanation:0.5).'
    ),
    target: int | None = typer.Option(None, "--target", help="Target example count."),
    budget_max_usd: float | None = typer.Option(None, "--budget-usd", help="Spend cap (USD)."),
    profile: str | None = typer.Option(None, "--profile", help="Runtime profile override."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Queue a generation job for the project and drive it to completion."""
    from .commands import run_pipeline as _f

    raise typer.Exit(
        _f(
            project_id=project_id,
            family=family,
            target=target,
            budget_max_usd=budget_max_usd,
            profile=profile,
            json_plain=json_plain,
        )
    )


job_app = typer.Typer(help="Inspect durable pipeline jobs.", no_args_is_help=True)
app.add_typer(job_app, name="job")


@job_app.command("status")
def job_status_cmd(
    job_id: str = typer.Argument(..., help="Job handle (job_…)."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Show one job's state, stage, progress, and recent events."""
    from .commands import job_status as _f

    raise typer.Exit(_f(job_id=job_id, json_plain=json_plain))


@job_app.command("list")
def job_list_cmd(
    project_id: str | None = typer.Option(None, "--project", help="Filter by project handle."),
    limit: int = typer.Option(20, "--limit", help="Maximum jobs to show."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List recent jobs (optionally per project)."""
    from .commands import job_list as _f

    raise typer.Exit(_f(project_id=project_id, limit=limit, json_plain=json_plain))


@app.command("review")
def review_cmd(
    example_id: str = typer.Argument(..., help="Example handle (ex_…)."),
    decision: _ReviewChoice = typer.Argument(..., help="Review decision."),
    note: str = typer.Option("", "--note", help="Reviewer note recorded with the decision."),
    reviewer: str = typer.Option("cli", "--reviewer", help="Reviewer principal."),
    revision: int | None = typer.Option(
        None, "--revision", help="Base revision id (default: latest)."
    ),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Record an approve/reject/needs_work decision on an example revision."""
    from .commands import review_decide as _f

    raise typer.Exit(
        _f(
            example_id=example_id,
            decision=decision.value,
            note=note,
            reviewer=reviewer,
            revision=revision,
            json_plain=json_plain,
        )
    )


dataset_app = typer.Typer(help="Validate, version, export, and publish datasets.",
                          no_args_is_help=True)
app.add_typer(dataset_app, name="dataset")


@dataset_app.command("validate")
def dataset_validate_cmd(
    project_id: str = typer.Argument(..., help="Project handle (proj_…)."),
    limit: int = typer.Option(500, "--limit", help="Maximum examples to validate."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Run the configured quality validation over a project's examples."""
    from .commands import dataset_validate as _f

    raise typer.Exit(_f(project_id=project_id, limit=limit, json_plain=json_plain))


@dataset_app.command("version")
def dataset_version_cmd(
    project_id: str = typer.Argument(..., help="Project handle (proj_…)."),
    semantic_version: str | None = typer.Option(
        None, "--set", help="Explicit semantic version (default: auto)."
    ),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Freeze the accepted examples into an immutable dataset version."""
    from .commands import dataset_version as _f

    raise typer.Exit(
        _f(project_id=project_id, semantic_version=semantic_version, json_plain=json_plain)
    )


@dataset_app.command("export")
def dataset_export_cmd(
    project_id: str = typer.Argument(..., help="Project handle (proj_…)."),
    format: str = typer.Option("openai_chat", "--format", help="Export format id."),
    version_id: str | None = typer.Option(None, "--version", help="Version handle (ver_…)."),
    download_dir: str | None = typer.Option(
        None, "--out", help="Directory for the exported artifact."
    ),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Export a versioned dataset bundle (checksummed artifact + manifest)."""
    from .commands import dataset_export as _f

    raise typer.Exit(
        _f(
            project_id=project_id,
            format=format,
            version_id=version_id,
            download_dir=download_dir,
            json_plain=json_plain,
        )
    )


@dataset_app.command("publish")
def dataset_publish_cmd(
    project_id: str = typer.Argument(..., help="Project handle (proj_…)."),
    repo_id: str = typer.Argument(..., help="Target repository id (org/dataset)."),
    live: bool = typer.Option(False, "--live", help="Publish for real (default: dry-run)."),
    principal: str = typer.Option("cli", "--principal", help="Acting principal."),
    json_plain: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Publish through the §15.6 gate (dry-run by default; blocked gates exit 1)."""
    from .commands import dataset_publish as _f

    raise typer.Exit(
        _f(
            project_id=project_id,
            repo_id=repo_id,
            dry_run=not live,
            principal=principal,
            json_plain=json_plain,
        )
    )


def main() -> None:
    app()
