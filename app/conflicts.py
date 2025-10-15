"""
Conflict detection and reporting utilities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .models import ConflictRecord, RemotePage
from .state import FileRecord, PageRecord


def has_conflict(
    file_record: Optional[FileRecord],
    page_record: Optional[PageRecord],
    remote_page: Optional[RemotePage],
    current_sha: str,
) -> bool:
    """
    Determine whether a conflict exists for a given note vs. remote page.

    Conflict criteria:
    - The local file has changed since the last sync (hash mismatch).
    - The remote page has changed since the last sync (newer version or timestamp).
    """
    if not file_record or not page_record or not remote_page:
        return False
    if current_sha == file_record.sha256:
        return False

    if remote_page.version and page_record.last_seen_version:
        if remote_page.version > page_record.last_seen_version:
            return True

    if (
        remote_page.last_updated
        and page_record.last_seen_remote_updated_at
        and remote_page.last_updated > page_record.last_seen_remote_updated_at
    ):
        return True

    return False


def build_conflict_record(file_path: Path, page_id: str, reason: str) -> ConflictRecord:
    return ConflictRecord(
        file_path=file_path,
        page_id=page_id,
        reason=reason,
        detected_at=datetime.now(tz=timezone.utc),
    )


def write_conflict_report(conflicts: Iterable[ConflictRecord], directory: Path) -> Optional[Path]:
    conflicts = list(conflicts)
    if not conflicts:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = directory / f"conflicts_{timestamp}.md"
    lines = [
        "# Sync Conflicts",
        "",
        f"Detected conflicts: {len(conflicts)}",
        "",
    ]
    for conflict in conflicts:
        lines.extend(
            [
                f"- File: `{conflict.file_path}`",
                f"  - Page ID: {conflict.page_id}",
                f"  - Reason: {conflict.reason}",
                f"  - Detected at: {conflict.detected_at.isoformat()}",
                "",
            ]
        )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path

