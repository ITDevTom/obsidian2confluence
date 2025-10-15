"""
Application entry point: orchestrates scheduler and CLI execution.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .client import ConfluenceClient
from .config import Settings, load_settings
from .conflicts import write_conflict_report
from .logging_setup import configure_logging
from .models import SyncPlanEntry
from .state import StateStore
from .sync import SyncEngine, SyncResult

LOG = logging.getLogger(__name__)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Obsidian vault to Confluence Cloud.")
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Execute a single sync run and exit.",
    )
    parser.add_argument(
        "--rebuild-root",
        action="store_true",
        help="Ensure the root page exists before syncing.",
    )
    return parser.parse_args(argv)


def create_client(settings: Settings) -> ConfluenceClient:
    return ConfluenceClient(
        base_url=settings.confluence_base_url,
        email=settings.confluence_email,
        api_token=settings.confluence_api_token,
    )


def perform_sync(engine_factory: Callable[[], SyncEngine], dry_run: bool) -> SyncResult:
    engine = engine_factory()
    result = engine.run(dry_run=dry_run)

    report_path = write_conflict_report(result.conflicts, Path("conflicts"))
    if report_path:
        LOG.warning(
            "Conflicts detected; see report",
            extra={"extra_payload": {"report_path": str(report_path)}},
        )

    if dry_run:
        plan_path = write_plan_report(result.plan, Path("reports"))
        LOG.info(
            "Dry-run plan written",
            extra={"extra_payload": {"report_path": str(plan_path)}},
        )

    return result


def write_plan_report(plan: list[SyncPlanEntry], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"plan_{timestamp}.md"

    lines = [
        "# Dry-run Plan",
        "",
        f"Generated at {datetime.now(tz=timezone.utc).isoformat()}",
        "",
    ]
    for entry in plan:
        lines.extend(
            [
                f"- `{entry.note.relative_path}` → {entry.action.value}",
                f"  - Title: {entry.note.frontmatter.title or entry.note.title}",
                f"  - Target page: {entry.target_page_id or 'new'}",
            ]
        )
        if entry.reason:
            lines.append(f"  - Reason: {entry.reason}")
        if entry.labels:
            lines.append(f"  - Labels: {', '.join(entry.labels)}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    settings = load_settings()
    configure_logging(settings.log_level)

    state_store = StateStore(Path(".state") / "obs2cf.db")
    client = create_client(settings)

    if args.rebuild_root:
        client.ensure_root_page(settings.confluence_space_key, settings.confluence_root_page_title)
        LOG.info("Root page ensured.")

    def engine_factory() -> SyncEngine:
        return SyncEngine(settings=settings, client=client, state_store=state_store)

    dry_run = settings.dry_run

    if args.run_once:
        perform_sync(engine_factory, dry_run=dry_run)
        return 0

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        lambda: perform_sync(engine_factory, dry_run=dry_run),
        trigger=IntervalTrigger(minutes=settings.sync_interval_minutes),
        name="obsidian2confluence-sync",
        next_run_time=datetime.now(tz=timezone.utc),
    )

    LOG.info(
        "Starting scheduler",
        extra={
            "extra_payload": {
                "interval_minutes": settings.sync_interval_minutes,
                "dry_run": dry_run,
            }
        },
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        LOG.info("Scheduler stopped.")
        return 0

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())

