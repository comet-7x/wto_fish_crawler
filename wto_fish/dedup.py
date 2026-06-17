"""Two-level dedup.

Level 1: url_norm  — same page reached via multiple links.
Level 2: content_hash — same bytes/text served at different URLs
         (very common on WTO: one PDF under several paths / query params).
"""

from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")


def hash_bytes(data: bytes) -> str:
    """SHA-256 of raw bytes (file-level identity)."""
    return hashlib.sha256(data).hexdigest()


def normalize_text(text: str) -> str:
    """Collapse whitespace so trivially-different renderings hash equal."""
    return _WS.sub(" ", text).strip()


def hash_text(text: str) -> str:
    """SHA-256 of normalized extracted text (content-level identity)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


class Dedup:
    """Tracks seen URLs and content; reports duplicates for an audit trail."""

    def __init__(self) -> None:
        self._urls: set[str] = set()
        # content_hash -> first url_norm that produced it
        self._content: dict[str, str] = {}
        self.report: list[dict[str, str]] = []

    def seen_url(self, url_norm: str) -> bool:
        return url_norm in self._urls

    def mark_url(self, url_norm: str) -> None:
        self._urls.add(url_norm)

    def check_content(self, url_norm: str, content_hash: str) -> str | None:
        """Return the canonical url_norm if this content was seen before, else None.

        Records a row in the dedup report when a duplicate is found.
        """
        canonical = self._content.get(content_hash)
        if canonical is None:
            self._content[content_hash] = url_norm
            return None
        self.report.append(
            {"duplicate_url": url_norm, "canonical_url": canonical,
             "content_hash": content_hash}
        )
        return canonical
