"""
Sync orchestration: determine plan, apply changes, record state, and emit reports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from . import attachments, conflicts, convert_md, links, scan
from .client import ConfluenceClient
from .config import Settings
from .models import ConflictRecord, RemotePage, SyncAction, SyncPlanEntry, SyncSummary, VaultNote
from .state import BindingRecord, StateStore

LOG = logging.getLogger(__name__)


@dataclass
class SyncResult:
    summary: SyncSummary
    plan: List[SyncPlanEntry]
    conflicts: List[ConflictRecord]


class SyncEngine:
    """High-level orchestrator for synchronising a vault with Confluence."""

    def __init__(self, settings: Settings, client: ConfluenceClient, state_store: StateStore):
        self.settings = settings
        self.client = client
        self.state = state_store
        self.now = datetime.now(tz=timezone.utc)
        self.page_manager = PageHierarchyManager(
            settings=settings, client=client, state_store=state_store
        )

    def run(self, dry_run: bool) -> SyncResult:
        self.now = datetime.now(tz=timezone.utc)
        notes = scan.scan_vault(self.settings.obsidian_vault_path)
        link_index = links.LinkIndex(self.settings.obsidian_vault_path, notes)

        summary = SyncSummary()
        plan_entries: List[SyncPlanEntry] = []
        conflict_records: List[ConflictRecord] = []

        for note in notes:
            entry, conflict_record = self._process_note(
                note=note,
                link_index=link_index,
                dry_run=dry_run,
            )
            plan_entries.append(entry)
            summary.register(entry.action)
            if conflict_record:
                conflict_records.append(conflict_record)

        LOG.info(
            "Sync summary",
            extra={
                "extra_payload": {
                    "created": summary.created,
                    "updated": summary.updated,
                    "skipped": summary.skipped,
                    "conflicts": summary.conflicts,
                }
            },
        )

        return SyncResult(summary=summary, plan=plan_entries, conflicts=conflict_records)

    # Processing --------------------------------------------------------------------

    def _process_note(
        self,
        note: VaultNote,
        link_index: links.LinkIndex,
        dry_run: bool,
    ) -> Tuple[SyncPlanEntry, Optional[ConflictRecord]]:
        if note.frontmatter.exclude:
            LOG.info(
                "Skipping note marked as excluded",
                extra={"extra_payload": {"path": note.relative_path}},
            )
            return (
                SyncPlanEntry(
                    note=note,
                    action=SyncAction.SKIP,
                    reason="Frontmatter exclude flag",
                    labels=note.frontmatter.labels,
                ),
                None,
            )

        parent_id = self.page_manager.resolve_parent(note, dry_run=dry_run)
        target_page, binding = self._lookup_target_page(note, parent_id)
        page_record = self.state.get_page(target_page.page_id) if target_page else None
        file_record = self.state.get_file(note.relative_path)

        if target_page and conflicts.has_conflict(
            file_record=file_record,
            page_record=page_record,
            remote_page=target_page,
            current_sha=note.sha256,
        ):
            conflict_record = conflicts.build_conflict_record(
                file_path=note.path,
                page_id=target_page.page_id,
                reason="Remote page changed since last sync",
            )
            LOG.warning(
                "Conflict detected",
                extra={
                    "extra_payload": {
                        "file_path": note.relative_path,
                        "page_id": target_page.page_id,
                    }
                },
            )
            return (
                SyncPlanEntry(
                    note=note,
                    action=SyncAction.CONFLICT,
                    reason="Remote page changed; manual review required",
                    target_page_id=target_page.page_id,
                    parent_page_id=parent_id,
                    labels=note.frontmatter.labels,
                ),
                conflict_record,
            )

        if target_page and file_record and file_record.sha256 == note.sha256:
            return (
                SyncPlanEntry(
                    note=note,
                    action=SyncAction.SKIP,
                    reason="No changes detected",
                    target_page_id=target_page.page_id,
                    parent_page_id=parent_id,
                    labels=note.frontmatter.labels,
                ),
                None,
            )

        rewritten = links.rewrite_links(note, link_index)
        working_note = note.model_copy(update={"content": rewritten.content})
        images = attachments.find_local_image_links(working_note, self.settings.obsidian_vault_path)
        planned_attachments = {
            image.target: attachments.UploadedAttachment(filename=image.absolute_path.name, download_url=None)
            for image in images
        }
        working_content = attachments.rewrite_image_targets(working_note.content, planned_attachments)
        storage_body = convert_md.markdown_to_confluence_storage(working_content)

        if target_page:
            updated_page = self._update_page(
                note=note,
                remote_page=target_page,
                parent_id=parent_id,
                storage_body=storage_body,
                labels=note.frontmatter.labels,
                images=images,
                dry_run=dry_run,
            )
            plan_entry = SyncPlanEntry(
                note=note,
                action=SyncAction.UPDATE if not dry_run else SyncAction.UPDATE,
                target_page_id=updated_page.page_id if updated_page else target_page.page_id,
                parent_page_id=parent_id,
                labels=note.frontmatter.labels,
            )
        else:
            created_page = self._create_page(
                note=note,
                parent_id=parent_id,
                storage_body=storage_body,
                labels=note.frontmatter.labels,
                images=images,
                dry_run=dry_run,
            )
            plan_entry = SyncPlanEntry(
                note=note,
                action=SyncAction.CREATE,
                target_page_id=created_page.page_id if created_page else None,
                parent_page_id=parent_id,
                labels=note.frontmatter.labels,
            )

        return plan_entry, None

    def _lookup_target_page(
        self, note: VaultNote, parent_id: Optional[str]
    ) -> Tuple[Optional[RemotePage], Optional[BindingRecord]]:
        # Frontmatter page_id takes precedence.
        if note.frontmatter.page_id:
            try:
                page = self.client.get_page(note.frontmatter.page_id)
                return page, self.state.get_binding_for_page(page.page_id)
            except Exception as exc:  # pragma: no cover - network errors
                LOG.error(
                    "Failed to retrieve page referenced by frontmatter page_id",
                    extra={
                        "extra_payload": {
                            "page_id": note.frontmatter.page_id,
                            "error": str(exc),
                        }
                    },
                )

        binding = self.state.get_binding_for_path(note.relative_path)
        if binding:
            try:
                page = self.client.get_page(binding.page_id)
                return page, binding
            except Exception as exc:  # pragma: no cover
                LOG.warning(
                    "Failed to load page via binding; will attempt fallback search",
                    extra={
                        "extra_payload": {
                            "page_id": binding.page_id,
                            "error": str(exc),
                        }
                    },
                )

        page = self.client.find_page(
            space_key=self.settings.confluence_space_key,
            title=note.frontmatter.title or note.title,
            parent_page_id=parent_id,
        )
        return page, binding

    def _create_page(
        self,
        note: VaultNote,
        parent_id: Optional[str],
        storage_body: str,
        labels: Iterable[str],
        images: List[attachments.ImageLink],
        dry_run: bool,
    ) -> Optional[RemotePage]:
        if dry_run:
            LOG.info(
                "Dry-run: would create page",
                extra={
                    "extra_payload": {
                        "title": note.frontmatter.title or note.title,
                        "parent_id": parent_id,
                    }
                },
            )
            return None

        title = note.frontmatter.title or note.title
        remote_page = self.client.create_page(
            space_key=self.settings.confluence_space_key,
            title=title,
            body=storage_body,
            parent_page_id=parent_id,
            labels=labels,
        )
        self._record_state(note, remote_page)
        self.state.set_binding(note.relative_path, remote_page.page_id)
        if images:
            attachments.upload_attachments(self.client, remote_page.page_id, images, dry_run=False)
        return remote_page

    def _update_page(
        self,
        note: VaultNote,
        remote_page: RemotePage,
        parent_id: Optional[str],
        storage_body: str,
        labels: Iterable[str],
        images: List[attachments.ImageLink],
        dry_run: bool,
    ) -> Optional[RemotePage]:
        if dry_run:
            LOG.info(
                "Dry-run: would update page",
                extra={
                    "extra_payload": {
                        "page_id": remote_page.page_id,
                        "title": note.frontmatter.title or note.title,
                    }
                },
            )
            return None

        updated_page = self.client.update_page(
            page_id=remote_page.page_id,
            title=note.frontmatter.title or note.title,
            body=storage_body,
            parent_page_id=parent_id,
            labels=labels,
            version=remote_page.version + 1,
        )
        self._record_state(note, updated_page)
        self.state.set_binding(note.relative_path, updated_page.page_id)
        if images:
            attachments.upload_attachments(self.client, updated_page.page_id, images, dry_run=False)
        return updated_page

    def _record_state(self, note: VaultNote, remote_page: RemotePage) -> None:
        self.state.upsert_file(note.relative_path, note.sha256, synced_at=self.now)
        self.state.upsert_page(
            page_id=remote_page.page_id,
            title=remote_page.title,
            parent_page_id=remote_page.parent_page_id,
            version=remote_page.version,
            last_updated=remote_page.last_updated,
        )


class PageHierarchyManager:
    """Ensure parent pages exist for notes based on folder structure and overrides."""

    def __init__(self, settings: Settings, client: ConfluenceClient, state_store: StateStore):
        self.settings = settings
        self.client = client
        self.state = state_store
        self._cache: dict[Tuple[str, Optional[str]], str] = {}
        self._dry_counter = 0
        self._root_page: Optional[RemotePage] = None

    def resolve_parent(self, note: VaultNote, dry_run: bool) -> Optional[str]:
        root_page = self._ensure_root(dry_run=dry_run)

        if note.frontmatter.parent:
            title_chain = [note.frontmatter.parent]
        else:
            title_chain = list(self._folder_chain(note))

        parent_id = root_page.page_id if root_page else None
        for title in title_chain:
            parent_id = self._ensure_page(
                title=title,
                parent_id=parent_id,
                dry_run=dry_run,
            )
        return parent_id

    def _folder_chain(self, note: VaultNote) -> Iterable[str]:
        relative_path = Path(note.relative_path)
        for part in relative_path.parts[:-1]:
            yield part

    def _ensure_page(self, title: str, parent_id: Optional[str], dry_run: bool) -> Optional[str]:
        key = (title, parent_id)
        if key in self._cache:
            return self._cache[key]

        if dry_run:
            synthetic_id = self._synthetic_id(title)
            self._cache[key] = synthetic_id
            return synthetic_id

        existing = self.client.find_page(
            space_key=self.settings.confluence_space_key,
            title=title,
            parent_page_id=parent_id,
        )
        if existing:
            self._cache[key] = existing.page_id
            self.state.upsert_page(
                page_id=existing.page_id,
                title=existing.title,
                parent_page_id=existing.parent_page_id,
                version=existing.version,
                last_updated=existing.last_updated,
            )
            return existing.page_id

        LOG.info(
            "Creating parent page",
            extra={"extra_payload": {"title": title, "parent_id": parent_id}},
        )
        new_page = self.client.create_page(
            space_key=self.settings.confluence_space_key,
            title=title,
            body="<p>Folder placeholder</p>",
            parent_page_id=parent_id,
            labels=[],
        )
        self.state.upsert_page(
            page_id=new_page.page_id,
            title=new_page.title,
            parent_page_id=new_page.parent_page_id,
            version=new_page.version,
            last_updated=new_page.last_updated,
        )
        self._cache[key] = new_page.page_id
        return new_page.page_id

    def _ensure_root(self, dry_run: bool) -> Optional[RemotePage]:
        if self._root_page:
            return self._root_page

        if dry_run:
            self._root_page = RemotePage(
                page_id=self._synthetic_id("root"),
                title=self.settings.confluence_root_page_title,
                parent_page_id=None,
                version=1,
                last_updated=None,
            )
            self._cache[(self._root_page.title, None)] = self._root_page.page_id
            return self._root_page

        root_page = self.client.ensure_root_page(
            space_key=self.settings.confluence_space_key,
            title=self.settings.confluence_root_page_title,
        )
        self.state.upsert_page(
            page_id=root_page.page_id,
            title=root_page.title,
            parent_page_id=root_page.parent_page_id,
            version=root_page.version,
            last_updated=root_page.last_updated,
        )
        self._cache[(root_page.title, root_page.parent_page_id)] = root_page.page_id
        self._root_page = root_page
        return root_page

    def _synthetic_id(self, title: str) -> str:
        self._dry_counter += 1
        return f"dryrun-{self._dry_counter}-{title.lower().replace(' ', '-')}"
