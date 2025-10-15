"""
Vault scanning utilities: walk the Obsidian vault, parse Markdown files, and extract metadata.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, List

import frontmatter

from .models import FrontmatterMetadata, VaultNote

HEADING_REGEX = re.compile(r"^#\\s+(?P<title>.+)$")


def scan_vault(vault_path: Path) -> List[VaultNote]:
    """Return all markdown notes discovered in the vault."""
    vault_path = vault_path.resolve()
    notes: List[VaultNote] = []
    for path in sorted(vault_path.rglob("*.md")):
        if _should_skip_path(path):
            continue
        notes.append(_load_note(vault_path, path))
    return notes


def _load_note(vault_root: Path, note_path: Path) -> VaultNote:
    raw = note_path.read_text(encoding="utf-8")
    sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    post = frontmatter.loads(raw)
    frontmatter_meta = _parse_frontmatter(post.metadata or {})
    title = frontmatter_meta.title or _derive_title(post.content) or note_path.stem

    return VaultNote(
        path=note_path,
        relative_path=str(note_path.relative_to(vault_root)),
        title=title,
        frontmatter=frontmatter_meta,
        content=post.content,
        sha256=sha256,
    )


def _parse_frontmatter(metadata: dict) -> FrontmatterMetadata:
    labels = metadata.get("labels")
    if labels is None:
        labels_list: List[str] = []
    elif isinstance(labels, list):
        labels_list = [str(label).strip() for label in labels if str(label).strip()]
    else:
        labels_list = [str(labels).strip()] if str(labels).strip() else []

    exclude_value = metadata.get("exclude", False)
    if isinstance(exclude_value, str):
        exclude_value = exclude_value.lower() in {"true", "1", "yes"}
    elif not isinstance(exclude_value, bool):
        exclude_value = False

    return FrontmatterMetadata(
        title=_clean(metadata.get("title")),
        labels=labels_list,
        parent=_clean(metadata.get("parent")),
        exclude=exclude_value,
        page_id=_clean(metadata.get("page_id")),
    )


def _derive_title(content: str) -> str | None:
    for line in content.splitlines():
        match = HEADING_REGEX.match(line.strip())
        if match:
            return match.group("title").strip()
    return None


def _should_skip_path(path: Path) -> bool:
    parts = set(path.parts)
    if any(part.startswith(".") for part in parts):
        return True
    return False


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
