"""
Utilities for resolving and rewriting note links into Confluence-compatible references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

from .models import VaultNote

WIKILINK_PATTERN = re.compile(r"(!)?\[\[([^\]]+)\]\]")
MARKDOWN_LINK_PATTERN = re.compile(r"(!)?\[(?P<text>[^\]]+)\]\((?P<url>[^)]+)\)")


def normalize_title(title: str) -> str:
    """Create a normalized key for title-based lookups."""
    return re.sub(r"\s+", " ", title.strip()).lower()


@dataclass
class LinkRewriteResult:
    content: str
    linked_titles: Set[str]


class LinkIndex:
    """Index of vault notes for quick lookup by title or relative path."""

    def __init__(self, vault_root: Path, notes: Iterable[VaultNote]):
        self.vault_root = vault_root.resolve()
        self._by_title: Dict[str, VaultNote] = {}
        self._by_relative_path: Dict[str, VaultNote] = {}
        for note in notes:
            self._by_title[normalize_title(note.title)] = note
            self._by_relative_path[note.relative_path] = note

    def get_by_title(self, title: str) -> Optional[VaultNote]:
        return self._by_title.get(normalize_title(title))

    def get_by_relative_path(self, relative_path: str) -> Optional[VaultNote]:
        return self._by_relative_path.get(relative_path)


def rewrite_links(note: VaultNote, index: LinkIndex) -> LinkRewriteResult:
    """Replace Obsidian-specific links with placeholders suitable for downstream conversion."""
    linked_titles: Set[str] = set()
    content = note.content

    def wikilink_replacer(match: re.Match[str]) -> str:
        raw_target = match.group(2).strip()
        display = raw_target
        if "|" in raw_target:
            target, display = [part.strip() for part in raw_target.split("|", 1)]
        else:
            target = raw_target
        resolved_note = index.get_by_title(target)
        if resolved_note:
            linked_titles.add(resolved_note.title)
            return f"[{display}](wikilink://{_escape_for_url(resolved_note.title)})"
        # Unresolved wikilink falls back to display text.
        return display

    content = WIKILINK_PATTERN.sub(wikilink_replacer, content)

    def markdown_link_replacer(match: re.Match[str]) -> str:
        is_image = bool(match.group(1))
        text = match.group("text")
        url = match.group("url").strip()
        if is_image or _looks_external(url):
            return match.group(0)
        if url.startswith("#"):
            return match.group(0)

        target_note = _resolve_relative_markdown_link(note, url, index)
        if target_note:
            linked_titles.add(target_note.title)
            return f"[{text}](wikilink://{_escape_for_url(target_note.title)})"
        return match.group(0)

    content = MARKDOWN_LINK_PATTERN.sub(markdown_link_replacer, content)

    return LinkRewriteResult(content=content, linked_titles=linked_titles)


def _resolve_relative_markdown_link(
    note: VaultNote, url: str, index: LinkIndex
) -> Optional[VaultNote]:
    if "://" in url:
        return None
    if url.endswith(".md"):
        # Resolve the path relative to the current note.
        candidate = (note.path.parent / url).resolve()
        try:
            relative = str(candidate.relative_to(index.vault_root))
        except ValueError:
            return None
        return index.get_by_relative_path(relative)
    return None


def _looks_external(url: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url))


def _escape_for_url(value: str) -> str:
    return value.replace(" ", "%20")

