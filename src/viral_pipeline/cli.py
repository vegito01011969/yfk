from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from viral_pipeline.config import Settings
from viral_pipeline.domain import StageName
from viral_pipeline.logging import configure_logging
from viral_pipeline.runner import PipelineRunner
from viral_pipeline.stages import authenticate_and_validate_youtube_upload
from viral_pipeline.storage import PipelineStore

app = typer.Typer(help="Automated viral trend compilation pipeline.")
console = Console()


def _settings() -> Settings:
    return Settings()


@app.command()
def init() -> None:
    """Create local data/work directories and initialize the SQLite schema."""
    settings = _settings()
    settings.pipeline_workdir.mkdir(parents=True, exist_ok=True)
    PipelineStore(settings.pipeline_db_path).close()
    console.print(f"Initialized database at {settings.pipeline_db_path}")
    console.print(f"Artifacts will be written under {settings.pipeline_workdir}")


@app.command()
def run(
    run_id: Annotated[str | None, typer.Option(help="Existing run id to resume.")] = None,
    stage: Annotated[StageName | None, typer.Option(help="Run exactly one stage.")] = None,
    no_resume: Annotated[bool, typer.Option(help="Re-run completed stages.")] = False,
    latest: Annotated[
        bool, typer.Option(help="Resume the latest run or create one if none exists.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run the full pipeline or a selected stage."""
    configure_logging(verbose)
    runner = PipelineRunner(_settings())
    if latest:
        store = PipelineStore(_settings().pipeline_db_path)
        latest_run_id = store.latest_run_id()
        context = runner.run(run_id=latest_run_id, only_stage=stage, resume=not no_resume)
    else:
        context = runner.run(run_id=run_id, only_stage=stage, resume=not no_resume)
    console.print(f"Run complete: {context.run_id}")
    if context.publish_package:
        console.print(f"Publish manifest: {context.publish_package.path}")


@app.command()
def status() -> None:
    """Show all known runs and their stage states."""
    store = PipelineStore(_settings().pipeline_db_path)
    runs = store.list_runs()
    if not runs:
        console.print("No runs found.")
        return
    for run_row in runs:
        console.print(f"\n[bold]{run_row['id']}[/bold] {run_row['status']} {run_row['created_at']}")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Stage")
        table.add_column("Status")
        table.add_column("Completed")
        table.add_column("Error")
        for stage_row in store.list_stage_runs(run_row["id"]):
            table.add_row(
                stage_row["stage"],
                stage_row["status"],
                stage_row["completed_at"] or "",
                stage_row["error"] or "",
            )
        console.print(table)


@app.command()
def show(run_id: str = typer.Argument("latest")) -> None:
    """Print the persisted pipeline context for a run."""
    store = PipelineStore(_settings().pipeline_db_path)
    actual_run_id = store.latest_run_id() if run_id == "latest" else run_id
    if actual_run_id is None:
        console.print("No runs found.")
        return
    context = store.load_context(actual_run_id)
    console.print_json(context.model_dump_json())


@app.command()
def paths() -> None:
    """Print configured filesystem paths."""
    settings = _settings()
    payload = {
        "database": str(Path(settings.pipeline_db_path).resolve()),
        "workdir": str(Path(settings.pipeline_workdir).resolve()),
    }
    console.print(json.dumps(payload, indent=2))


@app.command("auth-youtube-upload")
def auth_youtube_upload() -> None:
    """Create/refresh the YouTube upload OAuth token and validate the channel."""
    settings = _settings()
    result = authenticate_and_validate_youtube_upload(settings)
    console.print_json(json.dumps(result, default=str))


@app.command()
def cleanup(
    keep_source_history: Annotated[
        bool,
        typer.Option(help="Keep source history used for cross-run duplicate avoidance."),
    ] = True,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Run without confirmation.")] = False,
) -> None:
    """Remove bulky/resumable pipeline state after a completed scheduled run."""
    settings = _settings()
    paths_to_remove = [
        settings.pipeline_workdir,
        settings.pipeline_db_path,
    ]
    if not keep_source_history:
        paths_to_remove.append(settings.source_history_path)

    if not yes:
        console.print("Cleanup will remove:")
        for path in paths_to_remove:
            console.print(f"- {path}")
        raise typer.Abort()

    removed: list[str] = []
    for path in paths_to_remove:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path))
        elif path.exists():
            path.unlink()
            removed.append(str(path))

    settings.source_history_path.parent.mkdir(parents=True, exist_ok=True)
    if keep_source_history and not settings.source_history_path.exists():
        settings.source_history_path.write_text(
            json.dumps({"videos": {}, "queries": {}}, indent=2),
            encoding="utf-8",
        )
    console.print_json(json.dumps({"removed": removed}))
