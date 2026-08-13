"""Knovaryn command-line interface (spec §17.1).

The CLI exposes a fully offline demo plus project/intake commands. It wires the
framework-free :class:`ProjectService` and never requires model credentials for
the default ``demo`` path (fake provider).
"""

from __future__ import annotations

import asyncio
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
    try:
        from importlib.metadata import version

        return version("knovaryn")
    except Exception:  # noqa: BLE001
        return "0.1.0"


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


def main() -> None:
    app()
