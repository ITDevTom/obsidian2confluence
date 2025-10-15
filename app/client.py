"""
Confluence REST API client with retry and rate-limit handling.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests
from requests import Response, Session
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .models import RemotePage

LOG = logging.getLogger(__name__)


class ConfluenceError(RuntimeError):
    """Base exception for Confluence-related errors."""


class ConfluenceRetryableError(ConfluenceError):
    """Exceptions that should be retried."""


@dataclass
class AttachmentResponse:
    filename: str
    download_url: Optional[str]


class ConfluenceClient:
    """Minimal wrapper around the Confluence Cloud REST API."""

    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session: Session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update(
            {
                "Accept": "application/json",
            }
        )
        self._retryer = Retrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential_jitter(initial=1, max=30),
            retry=retry_if_exception_type((ConfluenceRetryableError, requests.RequestException)),
            reraise=True,
        )

    # High-level operations ---------------------------------------------------------

    def ensure_root_page(self, space_key: str, title: str) -> RemotePage:
        existing = self.find_page(space_key=space_key, title=title, parent_page_id=None)
        if existing:
            return existing
        LOG.info(
            "Creating Confluence root page",
            extra={"extra_payload": {"space_key": space_key, "title": title}},
        )
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": "<p>Root page</p>", "representation": "storage"}},
        }
        data = self._request_json("POST", "/rest/api/content", json=payload)
        return self.get_page(data["id"])

    def get_page(self, page_id: str) -> RemotePage:
        params = {"expand": "version,ancestors"}
        data = self._request_json("GET", f"/rest/api/content/{page_id}", params=params)
        return _parse_remote_page(data)

    def find_page(
        self, space_key: str, title: str, parent_page_id: Optional[str]
    ) -> Optional[RemotePage]:
        params = {
            "spaceKey": space_key,
            "title": title,
            "expand": "version,ancestors",
            "limit": 25,
        }
        data = self._request_json("GET", "/rest/api/content", params=params)
        for result in data.get("results", []):
            page = _parse_remote_page(result)
            if parent_page_id:
                if page.parent_page_id == parent_page_id:
                    return page
            else:
                if not page.parent_page_id:
                    return page
        return None

    def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        parent_page_id: Optional[str],
        labels: Iterable[str],
    ) -> RemotePage:
        payload: Dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        if parent_page_id:
            payload["ancestors"] = [{"id": parent_page_id}]
        data = self._request_json("POST", "/rest/api/content", json=payload)
        page_id = data["id"]
        self.update_labels(page_id, labels)
        return self.get_page(page_id)

    def update_page(
        self,
        page_id: str,
        title: str,
        body: str,
        parent_page_id: Optional[str],
        labels: Iterable[str],
        version: int,
    ) -> RemotePage:
        payload: Dict[str, Any] = {
            "id": page_id,
            "type": "page",
            "title": title,
            "version": {"number": version},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        if parent_page_id:
            payload["ancestors"] = [{"id": parent_page_id}]
        data = self._request_json("PUT", f"/rest/api/content/{page_id}", json=payload)
        self.update_labels(page_id, labels)
        return _parse_remote_page(data)

    def update_labels(self, page_id: str, labels: Iterable[str]) -> None:
        labels = [label for label in set(labels) if label]
        if not labels:
            return
        payload = [{"prefix": "global", "name": label} for label in labels]
        self._request(
            "POST",
            f"/rest/api/content/{page_id}/label",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
        )

    def upload_attachment(self, page_id: str, file_path: Path) -> AttachmentResponse:
        target = file_path.name
        with file_path.open("rb") as binary:
            files = {"file": (target, binary)}
            headers = {"X-Atlassian-Token": "no-check"}
            data = self._request_json(
                "POST",
                f"/rest/api/content/{page_id}/child/attachment",
                headers=headers,
                files=files,
                data=None,
                json_data=None,
            )
        attachment = data.get("results", [{}])[0]
        links = attachment.get("_links", {})
        download_link = links.get("download")
        if download_link:
            download_url = self.base_url + download_link
        else:
            download_url = None
        LOG.info(
            "Uploaded attachment",
            extra={
                "extra_payload": {
                    "page_id": page_id,
                    "filename": target,
                }
            },
        )
        return AttachmentResponse(filename=target, download_url=download_url)

    # Core HTTP machinery -----------------------------------------------------------

    def _request_json(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Any] = None,
        json_data: Optional[Any] = None,
    ) -> Dict[str, Any]:
        response = self._request(
            method,
            path,
            params=params,
            data=data,
            json=json_data or json,
            headers=headers,
            files=files,
        )
        return response.json()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Any] = None,
    ) -> Response:
        url = f"{self.base_url}{path}"
        try:
            response = self._retryer(
                lambda: self._send_request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    json=json,
                    headers=headers,
                    files=files,
                )
            )
        except RetryError as exc:  # pragma: no cover - retryer wraps final error
            raise exc.last_attempt.exception()
        return response

    def _send_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]],
        data: Optional[Any],
        json: Optional[Any],
        headers: Optional[Dict[str, str]],
        files: Optional[Any],
    ) -> Response:
        merged_headers = dict(self.session.headers)
        if headers:
            merged_headers.update(headers)
        if json is not None and "Content-Type" not in merged_headers:
            merged_headers["Content-Type"] = "application/json"
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                data=data,
                json=json,
                headers=merged_headers,
                files=files,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ConfluenceRetryableError(str(exc)) from exc

        if response.status_code in {429, 502, 503, 504}:
            retry_after = response.headers.get("Retry-After")
            LOG.warning(
                "Confluence rate-limited request",
                extra={
                    "extra_payload": {
                        "status_code": response.status_code,
                        "retry_after": retry_after,
                        "url": url,
                    }
                },
            )
            raise ConfluenceRetryableError(f"Rate limit {response.status_code}")

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"message": response.text}
            raise ConfluenceError(
                f"HTTP {response.status_code} for {url}: {payload.get('message', payload)}"
            )

        return response


def _parse_remote_page(data: Dict[str, Any]) -> RemotePage:
    version_info = data.get("version", {})
    parent_id = None
    ancestors = data.get("ancestors")
    if ancestors:
        parent_id = ancestors[-1]["id"]
    when = version_info.get("when")
    last_updated = (
        datetime.fromisoformat(when.replace("Z", "+00:00")) if when else None
    )
    return RemotePage(
        page_id=str(data["id"]),
        title=data["title"],
        parent_page_id=parent_id,
        version=version_info.get("number", 1),
        last_updated=last_updated,
    )
