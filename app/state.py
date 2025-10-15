"""
SQLite state management for obsidian2confluence.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass
class FileRecord:
    path: str
    sha256: str
    last_synced_at: Optional[datetime]


@dataclass
class PageRecord:
    page_id: str
    title: str
    parent_page_id: Optional[str]
    last_seen_version: Optional[int]
    last_seen_remote_updated_at: Optional[datetime]


@dataclass
class BindingRecord:
    file_path: str
    page_id: str


class StateStore:
    """Persistence layer tracking file and page metadata for idempotent syncs."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            last_synced_at TEXT
        );

        CREATE TABLE IF NOT EXISTS pages (
            page_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            parent_page_id TEXT,
            last_seen_version INTEGER,
            last_seen_remote_updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS bindings (
            file_path TEXT PRIMARY KEY,
            page_id TEXT UNIQUE NOT NULL,
            FOREIGN KEY (file_path) REFERENCES files(path) ON DELETE CASCADE,
            FOREIGN KEY (page_id) REFERENCES pages(page_id) ON DELETE CASCADE
        );
        """
        with self._connect() as conn:
            conn.executescript(schema)

    # File records ------------------------------------------------------------------

    def upsert_file(self, path: str, sha256: str, synced_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO files(path, sha256, last_synced_at)
                VALUES (?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    last_synced_at = excluded.last_synced_at
                """,
                (path, sha256, synced_at.strftime(ISO_FORMAT)),
            )

    def get_file(self, path: str) -> Optional[FileRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
        if not row:
            return None
        return FileRecord(
            path=row["path"],
            sha256=row["sha256"],
            last_synced_at=_parse_datetime(row["last_synced_at"]),
        )

    def list_files(self) -> Iterable[FileRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM files").fetchall()
        for row in rows:
            yield FileRecord(
                path=row["path"],
                sha256=row["sha256"],
                last_synced_at=_parse_datetime(row["last_synced_at"]),
            )

    # Page records ------------------------------------------------------------------

    def upsert_page(
        self,
        page_id: str,
        title: str,
        parent_page_id: Optional[str],
        version: Optional[int],
        last_updated: Optional[datetime],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pages(page_id, title, parent_page_id, last_seen_version, last_seen_remote_updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(page_id) DO UPDATE SET
                    title = excluded.title,
                    parent_page_id = excluded.parent_page_id,
                    last_seen_version = excluded.last_seen_version,
                    last_seen_remote_updated_at = excluded.last_seen_remote_updated_at
                """,
                (
                    page_id,
                    title,
                    parent_page_id,
                    version,
                    last_updated.strftime(ISO_FORMAT) if last_updated else None,
                ),
            )

    def get_page(self, page_id: str) -> Optional[PageRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pages WHERE page_id = ?", (page_id,)).fetchone()
        if not row:
            return None
        return PageRecord(
            page_id=row["page_id"],
            title=row["title"],
            parent_page_id=row["parent_page_id"],
            last_seen_version=row["last_seen_version"],
            last_seen_remote_updated_at=_parse_datetime(row["last_seen_remote_updated_at"]),
        )

    # Bindings ----------------------------------------------------------------------

    def set_binding(self, file_path: str, page_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO bindings(file_path, page_id)
                VALUES (?, ?)
                ON CONFLICT(file_path) DO UPDATE SET page_id = excluded.page_id
                """,
                (file_path, page_id),
            )

    def get_binding_for_path(self, file_path: str) -> Optional[BindingRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bindings WHERE file_path = ?", (file_path,)).fetchone()
        if not row:
            return None
        return BindingRecord(file_path=row["file_path"], page_id=row["page_id"])

    def get_binding_for_page(self, page_id: str) -> Optional[BindingRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bindings WHERE page_id = ?", (page_id,)).fetchone()
        if not row:
            return None
        return BindingRecord(file_path=row["file_path"], page_id=row["page_id"])

    def remove_binding(self, file_path: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM bindings WHERE file_path = ?", (file_path,))


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, ISO_FORMAT)

