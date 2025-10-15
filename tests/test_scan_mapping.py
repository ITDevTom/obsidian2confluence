from __future__ import annotations

from app import scan
from app.config import Settings
from app.sync import PageHierarchyManager
from app.state import StateStore


def test_scan_vault_parses_frontmatter(sample_vault):
    notes = scan.scan_vault(sample_vault)
    assert len(notes) == 1

    note = notes[0]
    assert note.frontmatter.title == "Example Title"
    assert note.frontmatter.parent == "Guides"
    assert note.frontmatter.labels == ["docs", "example"]
    assert note.relative_path.endswith("Guides/Example.md")
    assert "# Example Title" in note.content


class DummyClient:
    def __init__(self) -> None:
        self.called = False

    def ensure_root_page(self, *args, **kwargs):
        self.called = True
        raise AssertionError("Should not be called in dry-run hierarchy test")

    def find_page(self, *args, **kwargs):
        self.called = True
        raise AssertionError("Should not be called in dry-run hierarchy test")

    def create_page(self, *args, **kwargs):
        self.called = True
        raise AssertionError("Should not be called in dry-run hierarchy test")


def test_page_hierarchy_dry_run_uses_synthetic_ids(sample_vault, tmp_path):
    notes = scan.scan_vault(sample_vault)
    note = notes[0]

    settings = Settings.model_validate(
        {
            "CONFLUENCE_BASE_URL": "https://example.atlassian.net/wiki",
            "CONFLUENCE_EMAIL": "user@example.com",
            "CONFLUENCE_API_TOKEN": "token",
            "CONFLUENCE_SPACE_KEY": "KB",
            "CONFLUENCE_ROOT_PAGE_TITLE": "Knowledge Base",
            "OBSIDIAN_VAULT_PATH": str(sample_vault),
            "SYNC_INTERVAL_MINUTES": 60,
            "LOG_LEVEL": "INFO",
            "DRY_RUN": "true",
        }
    )

    state = StateStore(tmp_path / "state.db")
    client = DummyClient()
    manager = PageHierarchyManager(settings=settings, client=client, state_store=state)

    parent_id_one = manager.resolve_parent(note, dry_run=True)
    parent_id_two = manager.resolve_parent(note, dry_run=True)

    assert parent_id_one == parent_id_two
    assert parent_id_one.startswith("dryrun-")
    assert client.called is False
