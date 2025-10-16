"""
Shared pydantic models and enumerations used across the application.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class FrontmatterMetadata(BaseModel):
    """Represents parsed YAML frontmatter from an Obsidian note."""

    title: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    parent: Optional[str] = None
    exclude: bool = False
    page_id: Optional[str] = None


class VaultNote(BaseModel):
    """A fully parsed note in the Obsidian vault."""

    path: Path
    relative_path: str
    title: str
    frontmatter: FrontmatterMetadata
    content: str
    sha256: str


class RemotePage(BaseModel):
    """Remote Confluence page metadata."""

    page_id: str
    title: str
    parent_page_id: Optional[str]
    version: int
    last_updated: Optional[datetime]


class SyncAction(str, Enum):
    """Possible outcomes for a note sync operation."""

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"
    CONFLICT = "conflict"


class SyncPlanEntry(BaseModel):
    """Action plan describing how a note should be processed."""

    note: VaultNote
    action: SyncAction
    target_page_id: Optional[str] = None
    parent_page_id: Optional[str] = None
    reason: Optional[str] = None
    labels: List[str] = Field(default_factory=list)


class ConflictRecord(BaseModel):
    """Represents a detected sync conflict for reporting."""

    file_path: Path
    page_id: str
    reason: str
    detected_at: datetime


class SyncSummary(BaseModel):
    """Aggregated statistics for a sync execution."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    conflicts: int = 0

    def register(self, action: SyncAction) -> None:
        if action == SyncAction.CREATE:
            self.created += 1
        elif action == SyncAction.UPDATE:
            self.updated += 1
        elif action == SyncAction.SKIP:
            self.skipped += 1
        elif action == SyncAction.CONFLICT:
            self.conflicts += 1
