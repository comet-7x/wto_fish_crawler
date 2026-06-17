"""Data models shared across the pipeline."""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field


class Tier(enum.StrEnum):
    """Crawl scope tier for a URL."""

    T1_SITE = "T1_SITE"          # bounded fisheries-subsidies pages on www.wto.org
    T2_DOCS = "T2_DOCS"          # WTO Documents Online (docs.wto.org), series-whitelisted
    T3_EXTERNAL = "T3_EXTERNAL"  # FAO / OECD / World Bank / UN ... logged, not crawled
    REJECT = "REJECT"            # off-topic / non-English / not a wto host


@dataclass(slots=True)
class PageRecord:
    """One fetched resource and everything we derived from it."""

    url: str
    url_norm: str
    tier: str
    depth: int
    source: str = "wto"               # corpus source tag (config.SOURCE)
    source_url: str | None = None

    # populated after fetch
    status: int | None = None
    content_type: str | None = None      # "html" | "pdf" | other mime
    lang: str = "und"                     # "en" | "und"
    raw_sha256: str | None = None         # hash of raw bytes (file-level dedup)
    content_hash: str | None = None       # hash of normalized extracted text

    # populated after extract / classify
    title: str | None = None
    category: str = "uncategorized"
    out_md_path: str | None = None

    fetched_at: str | None = None
    error: str | None = None
    note: str | None = None               # human-readable status (e.g. recorded-only doc)
    duplicate_of: str | None = None       # url_norm of the canonical copy, if dup

    links: list[str] = field(default_factory=list)

    def to_manifest(self) -> dict:
        # `links` is kept: it is the page's in-scope document-reference edge list.
        return asdict(self)
