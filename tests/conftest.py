from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def sample_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    guides = vault / "Guides"
    guides.mkdir(parents=True)
    (vault / "Images").mkdir()

    note = guides / "Example.md"
    note.write_text(
        """---
title: Example Title
labels:
  - docs
  - example
parent: Guides
---

# Example Title

Content body.
""",
        encoding="utf-8",
    )

    return vault

