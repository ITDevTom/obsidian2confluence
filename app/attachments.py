"""
Attachment management: detect local asset references, upload them, and rewrite links.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import VaultNote

LOG = logging.getLogger(__name__)

IMAGE_PATTERN = r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)"


@dataclass
class ImageLink:
    alt_text: str
    target: str
    absolute_path: Path


@dataclass
class UploadedAttachment:
    filename: str
    download_url: Optional[str]


def find_local_image_links(note: VaultNote, vault_root: Path) -> List[ImageLink]:
    """Extract local image references from a note."""
    import re

    matches: List[ImageLink] = []
    pattern = re.compile(IMAGE_PATTERN)
    for match in pattern.finditer(note.content):
        target = match.group("target").strip()
        if "://" in target:
            continue
        absolute_path = (note.path.parent / target).resolve()
        try:
            absolute_path.relative_to(vault_root)
        except ValueError:
            continue
        matches.append(
            ImageLink(
                alt_text=match.group("alt").strip(),
                target=target,
                absolute_path=absolute_path,
            )
        )
    return matches


def upload_attachments(
    client: "ConfluenceClient",
    page_id: str,
    images: Iterable[ImageLink],
    dry_run: bool,
) -> Dict[str, UploadedAttachment]:
    """
    Upload image attachments to Confluence and return a mapping from original target to metadata.

    Parameters
    ----------
    client : ConfluenceClient
        REST client instance.
    page_id : str
        Identifier of the page receiving the attachments.
    images : Iterable[ImageLink]
        Collection of image references discovered in the note.
    dry_run : bool
        When True, do not upload but simulate the outcome.
    """
    mapping: Dict[str, UploadedAttachment] = {}
    for image in images:
        filename = image.absolute_path.name
        if dry_run:
            LOG.info(
                "Dry-run: would upload attachment",
                extra={"extra_payload": {"page_id": page_id, "attachment": filename}},
            )
            mapping[image.target] = UploadedAttachment(filename=filename, download_url=None)
            continue
        response = client.upload_attachment(page_id, image.absolute_path)
        mapping[image.target] = UploadedAttachment(
            filename=response.filename, download_url=response.download_url
        )
    return mapping


def rewrite_image_targets(content: str, attachment_map: Dict[str, UploadedAttachment]) -> str:
    """Replace relative image URLs with attachment placeholders."""
    import re

    if not attachment_map:
        return content

    def replacer(match: re.Match[str]) -> str:
        target = match.group("target").strip()
        if target in attachment_map:
            alt = match.group("alt")
            filename = attachment_map[target].filename
            return f"![{alt}](attachment://{filename})"
        return match.group(0)

    pattern = re.compile(IMAGE_PATTERN)
    return pattern.sub(replacer, content)


# Forward reference type checking ---------------------------------------------------
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover
    from .client import ConfluenceClient

