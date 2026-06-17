"""Async HTTP fetcher: polite concurrency, retry/backoff, html/pdf detection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from . import config


@dataclass(slots=True)
class FetchResult:
    url: str
    status: int
    content_type: str           # "html" | "pdf" | raw mime | "error"
    body: bytes
    final_url: str              # after redirects
    error: str | None = None


def _kind(mime: str, url: str) -> str:
    """Classify a fetched response: 'html' | 'pdf' | 'doc' | raw mime.

    'doc' = a non-PDF binary document, detected by file extension OR by a
    document/binary content-type (catches dynamic download links whose URL
    carries no revealing suffix). This is the colleague-spider trick: trust the
    Content-Type header, not just the URL.
    """
    mime = (mime or "").lower()
    u = url.lower().split("?", 1)[0]
    if "pdf" in mime or u.endswith(".pdf"):
        return "pdf"
    if "html" in mime or u.endswith((".htm", ".html")):
        return "html"
    if u.endswith(config.DOC_FETCH_SUFFIXES) or any(
            mime.startswith(t) for t in config.DOC_CONTENT_TYPES):
        return "doc"
    return mime or "unknown"


class Fetcher:
    """Wraps an httpx.AsyncClient with a concurrency gate and a per-request delay."""

    def __init__(self, concurrency: int = config.DEFAULT_CONCURRENCY,
                 delay_s: float = config.DEFAULT_DELAY_S) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._delay = delay_s
        self._client = httpx.AsyncClient(
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.REQUEST_TIMEOUT_S,
            follow_redirects=True,
        )

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> FetchResult:
        async with self._sem:
            last_err: str | None = None
            for attempt in range(1, config.MAX_RETRIES + 1):
                try:
                    resp = await self._client.get(url)
                    await asyncio.sleep(self._delay)  # politeness
                    mime = resp.headers.get("content-type", "")
                    return FetchResult(
                        url=url,
                        status=resp.status_code,
                        content_type=_kind(mime, str(resp.url)),
                        body=resp.content,
                        final_url=str(resp.url),
                    )
                except (httpx.TransportError, httpx.HTTPError) as e:  # noqa: PERF203
                    last_err = f"{type(e).__name__}: {e}"
                    await asyncio.sleep(self._delay * attempt * 2)  # backoff
            return FetchResult(url, 0, "error", b"", url, error=last_err)
