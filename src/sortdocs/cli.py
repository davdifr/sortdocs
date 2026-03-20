from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sortdocs.config import ConfigError, SortdocsConfig, load_config
from sortdocs.executor import ExecutionProgressEvent, ExecutionStage
from sortdocs.logging_utils import configure_logging
from sortdocs.models import ExecutionReport
from sortdocs.onboarding import OnboardingError, maybe_run_first_run_onboarding
from sortdocs.pipeline import PipelinePlan, PipelineProgressEvent, PipelineResult, SortdocsPipeline
from sortdocs.planner import display_path
from sortdocs.scanner import ProjectRootDetectedError
from sortdocs.utils import limit_text


LOGGER = logging.getLogger(__name__)
ACTION_STYLES = {
    "move": "cyan",
    "rename": "blue",
    "move_and_rename": "magenta",
    "review": "yellow",
    "skip": "green",
}


def get_console() -> Console:
    return Console(highlight=False, soft_wrap=True)


def get_error_console() -> Console:
    return Console(stderr=True, highlight=False, soft_wrap=True)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    help=(
        "Scan a folder, classify files, and run a safe organization flow.\n\n"
        "By default, sortdocs scans recursively, shows the plan, and asks for confirmation "
        "before applying changes. Use --dry-run for a preview-only run."
    ),
)


@dataclass
class RuntimeSettings:
    source_dir: Path
    dry_run: bool
    prompt_before_apply: bool
    recursive: bool
    allow_project_root: bool
    config_path: Optional[Path]
    review_dir: Path
    library_dir: Path
    verbose: bool
    max_files: Optional[int]
    yes: bool


@app.command()
def sortdocs(
    path: Path = typer.Argument(
        ...,
        metavar="PATH",
        help="Directory to inspect.",
    ),
    dry_run: Optional[bool] = typer.Option(
        None,
        "--dry-run/--apply",
        show_default=False,
        help="Preview only, or apply the plan after the planning step.",
    ),
    recursive: Optional[bool] = typer.Option(
        None,
        "--recursive/--no-recursive",
        help="Enable or disable recursive scanning. Defaults to recursive.",
    ),
    allow_project_root: bool = typer.Option(
        False,
        "--allow-project-root",
        help="Allow scanning a root folder that looks like a software project.",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        metavar="FILE",
        help="Load CLI defaults from a YAML config file.",
    ),
    review_dir: Optional[Path] = typer.Option(
        None,
        "--review-dir",
        metavar="DIR",
        help="Directory for low-confidence files. Use '.' to keep them in place.",
    ),
    library_dir: Optional[Path] = typer.Option(
        None,
        "--library-dir",
        metavar="DIR",
        help="Base directory for organized files. Use '.' to reorganize directly inside PATH.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable debug logging.",
    ),
    max_files: Optional[int] = typer.Option(
        None,
        "--max-files",
        metavar="N",
        help="Limit the number of discovered files.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt before applying the plan.",
    ),
) -> None:
    try:
        source_dir = validate_source_dir(path)
        loaded_config, resolved_config_path = load_config(config_path)
        settings = build_runtime_settings(
            source_dir=source_dir,
            config=loaded_config,
            config_path=resolved_config_path,
            dry_run=dry_run,
            recursive=recursive,
            allow_project_root=allow_project_root,
            review_dir=review_dir,
            library_dir=library_dir,
            verbose=verbose,
            max_files=max_files,
            yes=yes,
        )
    except ConfigError as exc:
        emit_error(str(exc))
        raise typer.Exit(code=2)
    except ValueError as exc:
        emit_error(str(exc))
        raise typer.Exit(code=2)
    try:
        maybe_run_first_run_onboarding(get_console())
    except OnboardingError as exc:
        emit_error(str(exc))
        raise typer.Exit(code=2)

    configure_logging(level_name=loaded_config.logging.level, verbose=settings.verbose)
    LOGGER.debug("Runtime settings: %s", settings)
    pipeline = SortdocsPipeline(
        loaded_config,
        library_dir=settings.library_dir,
        review_dir=settings.review_dir,
    )

    try:
        plan = run_planning_step(pipeline, settings)
    except ProjectRootDetectedError as exc:
        emit_error(str(exc))
        raise typer.Exit(code=2)
    except OSError as exc:
        LOGGER.debug("Directory scan failed.", exc_info=True)
        emit_error(f"Failed while reading {settings.source_dir}: {exc}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        emit_error("Interrupted.")
        raise typer.Exit(code=130)
    except Exception as exc:
        LOGGER.debug("Unhandled pipeline failure.", exc_info=True)
        emit_error(str(exc))
        raise typer.Exit(code=1)

    render_header(settings)

    if not plan.discovered_files:
        typer.echo("No files found for planning.")
        raise typer.Exit(code=0)

    render_plan(plan, settings)

    if settings.prompt_before_apply:
        should_apply = typer.confirm("Proceed with these actions?", default=False)
        typer.echo("")
        if not should_apply:
            typer.echo("Aborted. No changes were made.")
            raise typer.Exit(code=0)

    try:
        execution_report = run_execution_step(pipeline, plan, settings)
    except KeyboardInterrupt:
        emit_error("Interrupted.")
        raise typer.Exit(code=130)
    except Exception as exc:
        LOGGER.debug("Unhandled execution failure.", exc_info=True)
        emit_error(str(exc))
        raise typer.Exit(code=1)

    pipeline_result = PipelineResult(
        discovered_files=plan.discovered_files,
        actions=plan.actions,
        execution_report=execution_report,
        skipped_directories=plan.skipped_directories,
        cache_hits=plan.cache_hits,
    )

    render_summary(pipeline_result, settings)
    render_errors(pipeline_result)

    exit_code = 1 if pipeline_result.execution_report.counts.failed else 0
    raise typer.Exit(code=exit_code)


def validate_source_dir(path: Path) -> Path:
    source_dir = path.expanduser().resolve()
    if not source_dir.exists():
        raise ValueError(f"Path does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise ValueError(f"Path is not a directory: {source_dir}")
    if not os.access(source_dir, os.R_OK | os.X_OK):
        raise ValueError(f"Path is not readable: {source_dir}")
    return source_dir


def build_runtime_settings(
    *,
    source_dir: Path,
    config: SortdocsConfig,
    config_path: Optional[Path],
    dry_run: Optional[bool],
    recursive: Optional[bool],
    allow_project_root: bool,
    review_dir: Optional[Path],
    library_dir: Optional[Path],
    verbose: bool,
    max_files: Optional[int],
    yes: bool,
) -> RuntimeSettings:
    resolved_max_files = max_files if max_files is not None else config.cli.max_files
    if resolved_max_files is not None and resolved_max_files < 1:
        raise ValueError("--max-files must be greater than zero.")

    resolved_review_dir = resolve_output_dir(
        source_dir=source_dir,
        configured_path=review_dir or config.cli.review_dir,
    )
    resolved_library_dir = resolve_output_dir(
        source_dir=source_dir,
        configured_path=library_dir or config.cli.library_dir,
    )
    resolved_dry_run = config.cli.dry_run if dry_run is None else dry_run
    resolved_recursive = config.cli.recursive if recursive is None else recursive

    return RuntimeSettings(
        source_dir=source_dir,
        dry_run=resolved_dry_run,
        prompt_before_apply=not resolved_dry_run and not yes,
        recursive=resolved_recursive,
        allow_project_root=allow_project_root,
        config_path=config_path,
        review_dir=resolved_review_dir,
        library_dir=resolved_library_dir,
        verbose=verbose,
        max_files=resolved_max_files,
        yes=yes,
    )


def resolve_output_dir(*, source_dir: Path, configured_path: Path) -> Path:
    expanded = configured_path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (source_dir / expanded).resolve()


def render_header(settings: RuntimeSettings) -> None:
    console = get_console()
    if settings.dry_run:
        mode_label = Text("DRY-RUN", style="bold yellow")
    elif settings.prompt_before_apply:
        mode_label = Text("PLAN + CONFIRM", style="bold cyan")
    else:
        mode_label = Text("APPLY", style="bold green")
    review_mode = "in place" if settings.review_dir == settings.library_dir else str(settings.review_dir)
    info_table = Table.grid(padding=(0, 2))
    info_table.add_column(style="bold")
    info_table.add_column()
    info_table.add_row("Mode", mode_label)
    info_table.add_row("Source", str(settings.source_dir))
    info_table.add_row("Config", str(settings.config_path or "defaults"))
    info_table.add_row("Recursive", "yes" if settings.recursive else "no")
    info_table.add_row("Project root", "allowed" if settings.allow_project_root else "protected")
    info_table.add_row("Target root", str(settings.library_dir))
    info_table.add_row("Review dir", review_mode)
    info_table.add_row("Max files", str(settings.max_files or "unlimited"))
    console.print(Panel(info_table, title=f"sortdocs {mode_label.plain}", border_style="cyan"))
    console.print()


def run_planning_step(pipeline: SortdocsPipeline, settings: RuntimeSettings) -> PipelinePlan:
    console = get_console()
    console.print("[bold cyan]Analyzing files...[/bold cyan] Scanning, extracting, and classifying documents.")
    with console.status("Scanning files...", spinner="dots", spinner_style="cyan") as status:
        def on_progress(event: PipelineProgressEvent) -> None:
            if event.stage == "scanning":
                status.update(status="Scanning files...")
                return
            if event.stage == "scan_complete":
                discovered = event.total or 0
                status.update(status=f"Found {discovered} files. Starting classification...")
                return
            if event.stage == "classifying":
                current_name = event.current_path.name if event.current_path is not None else "current file"
                status.update(
                    status=_build_status_message(
                        prefix=f"Classifying {event.current}/{event.total or 0}",
                        detail=current_name,
                        suffix=f"cache hits {event.cache_hits}",
                        console=console,
                    )
                )
                return
            if event.stage == "planning_complete":
                status.update(status=f"Finalizing plan for {event.current} files...")

        plan = pipeline.plan_directory(
            settings.source_dir,
            recursive=settings.recursive,
            max_files=settings.max_files,
            allow_project_root=settings.allow_project_root,
            progress_callback=on_progress,
        )
    completion_bits = [
        f"{len(plan.discovered_files)} files analyzed",
        f"{len(plan.actions)} planned actions",
    ]
    if plan.cache_hits:
        completion_bits.append(f"{plan.cache_hits} cache hits")
    if plan.skipped_directories:
        completion_bits.append(f"{len(plan.skipped_directories)} protected dirs skipped")
    console.print(f"[dim]Analysis complete:[/dim] {' • '.join(completion_bits)}")
    console.print()
    return plan


def run_execution_step(
    pipeline: SortdocsPipeline,
    plan: PipelinePlan,
    settings: RuntimeSettings,
) -> ExecutionReport:
    console = get_console()
    if settings.dry_run:
        return pipeline.execute_plan(plan, dry_run=True)

    console.print("[bold green]Applying changes...[/bold green] Moving and renaming files safely.")
    with console.status("Applying planned actions...", spinner="line", spinner_style="green") as status:
        def on_progress(event: ExecutionProgressEvent) -> None:
            if event.result is None:
                return
            detail = f"{event.action.action_type.value}: {event.action.target_filename}"
            if event.result.error_code:
                detail = f"{detail} | {event.result.error_code.lower()}"
            if event.stage == ExecutionStage.COMPLETE:
                status.update(status="All planned actions processed.")
                return
            status.update(
                status=_build_status_message(
                    prefix=f"Applying {event.current}/{event.total}",
                    detail=detail,
                    console=console,
                )
            )

        report = pipeline.execute_plan(plan, dry_run=False, progress_callback=on_progress)
    console.print(f"[dim]Execution complete:[/dim] {len(plan.actions)} planned actions processed")
    console.print()
    return report


def render_plan(result: PipelinePlan | PipelineResult, settings: RuntimeSettings) -> None:
    console = get_console()
    counts = Counter(action.action_type.value for action in result.actions)
    overview = Table.grid(expand=False, padding=(0, 2))
    overview.add_column(style="bold")
    overview.add_column()
    overview.add_row("Files discovered", str(len(result.discovered_files)))
    overview.add_row("Planned actions", str(len(result.actions)))
    if getattr(result, "cache_hits", 0):
        overview.add_row("Cached classifications", str(result.cache_hits))
    if getattr(result, "skipped_directories", None):
        overview.add_row("Protected dirs skipped", str(len(result.skipped_directories)))
    overview.add_row(
        "Action mix",
        ", ".join(
            f"{label}={counts[label]}"
            for label in ("move", "rename", "move_and_rename", "review", "skip")
            if counts.get(label)
        ) or "none",
    )
    console.print(Panel(overview, title="Plan Overview", border_style="blue"))

    plan_table = Table(
        title="Planned Actions",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        header_style="bold",
    )
    plan_table.add_column("Action", style="bold", no_wrap=True)
    plan_table.add_column("Conf", justify="right", no_wrap=True)
    plan_table.add_column("Source", overflow="fold")
    plan_table.add_column("Target", overflow="fold")
    plan_table.add_column("Why", overflow="fold")
    plan_table.add_column("Notes", overflow="fold")

    for action in result.actions:
        action_label = Text(action.action_type.value, style=ACTION_STYLES.get(action.action_type.value, "white"))
        source_label = display_path(action.source_path, settings.source_dir.parent)
        target_label = display_path(action.target_path, settings.source_dir.parent)
        notes = " | ".join(action.warnings) if action.warnings else "-"
        plan_table.add_row(
            action_label,
            f"{action.confidence:.2f}",
            source_label,
            target_label,
            limit_text(action.reason, 90),
            limit_text(notes, 120),
        )

    console.print(plan_table)
    _render_next_step_panel(result, settings)
    skipped_directories = getattr(result, "skipped_directories", [])
    if skipped_directories:
        skipped_table = Table(
            title="Protected Directories Skipped",
            box=box.SIMPLE,
            header_style="bold yellow",
        )
        skipped_table.add_column("Directory", overflow="fold")
        skipped_table.add_column("Reason", overflow="fold")
        for skipped in skipped_directories[:8]:
            skipped_table.add_row(
                display_path(skipped.absolute_path, settings.source_dir.parent),
                limit_text(skipped.reason, 110),
            )
        if len(skipped_directories) > 8:
            skipped_table.add_row("...", f"{len(skipped_directories) - 8} more protected directories")
        console.print(skipped_table)
    console.print()


def render_summary(result: PipelineResult, settings: RuntimeSettings) -> None:
    console = get_console()
    report = result.execution_report
    run_mode = "dry-run" if settings.dry_run else "apply"
    if settings.prompt_before_apply:
        run_mode = "plan + confirm"
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Run mode", run_mode)
    summary.add_row("Files scanned", str(len(result.discovered_files)))
    if result.cache_hits:
        summary.add_row("Cache hits", str(result.cache_hits))
    if result.skipped_directories:
        summary.add_row("Protected dirs skipped", str(len(result.skipped_directories)))
    summary.add_row("Moved", str(report.counts.moved))
    summary.add_row("Renamed", str(report.counts.renamed))
    summary.add_row("Reviewed", str(report.counts.reviewed))
    summary.add_row("Skipped", str(report.counts.skipped))
    summary.add_row("Failed", str(report.counts.failed))
    summary.add_row("Warnings", str(report.metrics.warnings_total))
    summary.add_row("Guardrail hits", str(report.metrics.guardrail_failures))
    border_style = "green" if report.counts.failed == 0 else "red"
    console.print(Panel(summary, title="Run Summary", border_style=border_style))
    console.print()


def render_errors(result: PipelineResult) -> None:
    if not result.execution_report.errors:
        return

    console = get_console()
    error_table = Table(title="Errors", box=box.SIMPLE, header_style="bold red")
    error_table.add_column("Code", style="red", no_wrap=True)
    error_table.add_column("Source", overflow="fold")
    error_table.add_column("Message", overflow="fold")
    for issue in result.execution_report.errors:
        error_table.add_row(issue.code, str(issue.source_path), issue.message)
    console.print(error_table)
    console.print()


def emit_error(message: str) -> None:
    get_error_console().print(f"[bold red]Error:[/bold red] {message}")


def _render_next_step_panel(result: PipelinePlan | PipelineResult, settings: RuntimeSettings) -> None:
    console = get_console()
    counts = Counter(action.action_type.value for action in result.actions)
    changed_actions = counts.get("move", 0) + counts.get("rename", 0) + counts.get("move_and_rename", 0)
    review_actions = counts.get("review", 0)
    skipped_actions = counts.get("skip", 0)

    if settings.dry_run:
        message = (
            f"Preview complete. {changed_actions} file changes are planned, "
            f"{review_actions} files need review, and {skipped_actions} will stay in place."
        )
        border_style = "yellow"
        title = "Preview"
    else:
        message = (
            f"Ready to apply. {changed_actions} file changes are queued, "
            f"{review_actions} files will be routed to review, and {skipped_actions} will be skipped."
        )
        border_style = "green"
        title = "Next Step"

    console.print(Panel(message, border_style=border_style, title=title))


def _build_status_message(
    *,
    prefix: str,
    detail: str,
    console: Console,
    suffix: Optional[str] = None,
) -> str:
    width = getattr(console.size, "width", 100)
    reserved = len(prefix) + len(suffix or "") + 8
    detail_max_chars = max(20, min(72, width - reserved))
    parts = [prefix, limit_text(detail, detail_max_chars)]
    if suffix:
        parts.append(suffix)
    return " | ".join(part for part in parts if part)
