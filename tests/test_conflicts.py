from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import conflicts
from app.models import RemotePage
from app.state import FileRecord, PageRecord


def test_conflict_detected_on_remote_and_local_change():
    now = datetime.now(tz=timezone.utc)
    file_record = FileRecord(path="Guides/Example.md", sha256="old", last_synced_at=now - timedelta(days=1))
    page_record = PageRecord(
        page_id="123",
        title="Example",
        parent_page_id=None,
        last_seen_version=3,
        last_seen_remote_updated_at=now - timedelta(days=1),
    )
    remote_page = RemotePage(
        page_id="123",
        title="Example",
        parent_page_id=None,
        version=4,
        last_updated=now,
    )

    assert conflicts.has_conflict(file_record, page_record, remote_page, current_sha="new") is True


def test_no_conflict_when_hash_unchanged():
    now = datetime.now(tz=timezone.utc)
    file_record = FileRecord(path="Guides/Example.md", sha256="same", last_synced_at=now)
    page_record = PageRecord(
        page_id="123",
        title="Example",
        parent_page_id=None,
        last_seen_version=4,
        last_seen_remote_updated_at=now,
    )
    remote_page = RemotePage(
        page_id="123",
        title="Example",
        parent_page_id=None,
        version=4,
        last_updated=now,
    )

    assert conflicts.has_conflict(file_record, page_record, remote_page, current_sha="same") is False

