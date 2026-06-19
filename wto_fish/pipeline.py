"""Crawl orchestration.

Flow per URL:
    fetch -> (html) extract md + harvest links -> enqueue in-scope links
          -> (pdf)  convert via MinerU
    -> content-hash dedup -> classify -> write markdown + manifest row.

Outputs (under --out):
    raw/{html,pdf}/      raw payloads, named by raw sha256
    markdown/            converted docs, named by content_hash[:16].md, with YAML front matter
    manifest.jsonl       one row per kept resource
    external_links.jsonl Tier-3 links seen (not crawled)
    dedup_report.csv     content-level duplicates dropped
    crawl.log            run log
"""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import json
import logging
from collections import deque
from pathlib import Path

from . import classify, config, dedup, extract, urlrules
from .fetch import Fetcher
from .models import PageRecord, Tier

log = logging.getLogger("wto_fish")


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _front_matter(rec: PageRecord) -> str:
    fields = {
        "url": rec.url,
        "url_norm": rec.url_norm,
        "source": rec.source,
        "category": rec.category,
        "lang": rec.lang,
        "tier": rec.tier,
        "title": rec.title or "",
        "content_hash": rec.content_hash or "",
        "source_url": rec.source_url or "",
        "fetched_at": rec.fetched_at or "",
    }
    lines = ["---"]
    for k, v in fields.items():
        v = str(v).replace("\n", " ").replace('"', "'")
        lines.append(f'{k}: "{v}"')
    lines.append("---\n")
    return "\n".join(lines)


class Crawler:
    def __init__(self, out_dir: Path, *, max_depth: int, concurrency: int,
                 delay_s: float, include_docs: bool, max_pages: int | None,
                 pdf_backend: str) -> None:
        self.out = out_dir
        self.max_depth = max_depth
        self.concurrency = concurrency
        self.delay_s = delay_s
        self.include_docs = include_docs
        self.max_pages = max_pages
        self.pdf_backend = pdf_backend

        self.dedup = dedup.Dedup()
        self.frontier: deque[tuple[str, int, str | None]] = deque()
        self.manifest_fp = None
        self.external_fp = None
        self.kept = 0

        for sub in ("raw/html", "raw/pdf", "markdown"):
            (self.out / sub).mkdir(parents=True, exist_ok=True)

    # ---------------- frontier management ---------------- #

    def _enqueue(self, url: str, depth: int, source: str | None) -> None:
        norm = urlrules.normalize_url(url)
        if self.dedup.seen_url(norm):
            return
        tier = urlrules.decide_tier(norm)
        if tier is Tier.T3_EXTERNAL:
            self._log_external(norm, source)
            self.dedup.mark_url(norm)
            return
        if tier is Tier.T2_DOCS and not self.include_docs:
            return
        if not urlrules.should_crawl(norm):
            return
        if urlrules.is_record_only_doc(norm):
            return  # recorded at discovery, never fetched
        self.dedup.mark_url(norm)
        self.frontier.append((norm, depth, source))

    def _record_doc_ref(self, url_norm: str, source: str | None) -> None:
        """Record a large/media document by URL without downloading it."""
        if self.dedup.seen_url(url_norm):
            return
        self.dedup.mark_url(url_norm)
        ext = url_norm.lower().split("?", 1)[0].rsplit(".", 1)[-1][:5]
        rec = PageRecord(
            url=url_norm, url_norm=url_norm,
            tier=urlrules.decide_tier(url_norm).value,
            depth=0, source=config.SOURCE, source_url=source,
            content_type=ext, lang="en" if urlrules.is_english(url_norm) else "und",
            category=classify.classify(url_norm),
            note="recorded at discovery; large/media, not downloaded",
            fetched_at=_now())
        self._write_manifest(rec)
        log.info("doc-ref [%s] %s (not downloaded)", rec.category, url_norm)

    def _log_external(self, url_norm: str, source: str | None) -> None:
        self.external_fp.write(json.dumps(
            {"url": url_norm, "source_url": source, "seen_at": _now()},
            ensure_ascii=False) + "\n")

    def _is_edge(self, url_norm: str) -> bool:
        """True if this URL is an in-scope fisheries-document reference.

        Used to build the document-reference graph. Tier-2 (docs.wto.org)
        references count even when --include-docs is off, so the graph still
        surfaces them as dangling edges (a "fetch this next" signal).
        """
        tier = urlrules.decide_tier(url_norm)
        if urlrules.is_excluded(url_norm):
            return False
        if tier is Tier.T1_SITE:
            return urlrules.is_english(url_norm)
        return tier is Tier.T2_DOCS

    # ---------------- per-URL handling ---------------- #

    async def _handle(self, fetcher: Fetcher, url_norm: str, depth: int,
                      source: str | None) -> None:
        rec = PageRecord(url=url_norm, url_norm=url_norm,
                         tier=urlrules.decide_tier(url_norm).value,
                         depth=depth, source=config.SOURCE,
                         source_url=source, fetched_at=_now())
        res = await fetcher.fetch(url_norm)
        rec.status = res.status
        rec.content_type = res.content_type
        rec.raw_sha256 = dedup.hash_bytes(res.body) if res.body else None

        if res.error or res.status >= 400 or not res.body:
            rec.error = res.error or f"HTTP {res.status}"
            log.warning("fetch failed: %s (%s)", url_norm, rec.error)
            self._write_manifest(rec)
            return

        rec.lang = "en" if urlrules.is_english(url_norm) else "und"

        # A binary/media URL that comes back as HTML was redirected to a shell:
        # WTO serves an "error=true" login/index page for access-gated media
        # (e.g. the chair-update videos). Record it as blocked — do NOT mistake
        # that shell for the document's content.
        if res.content_type == "html" and urlrules.expected_binary(url_norm):
            rec.content_type = url_norm.lower().split("?", 1)[0].rsplit(".", 1)[-1][:5]
            rec.category = classify.classify(url_norm, rec.title)
            rec.error = "access-gated: direct download blocked (HTML shell returned)"
            rec.note = ("media/binary not retrievable via direct GET; "
                        "needs browser/stream capture")
            log.warning("blocked-media %s -> %s", url_norm, res.final_url)
            self._write_manifest(rec)
            return

        markdown: str | None = None
        if res.content_type == "html":
            html_text = res.body.decode("utf-8", "replace")
            # WTO returns HTTP 200 + a "page not found" shell for dead URLs.
            # Don't keep that shell as content.
            if extract.is_soft_404(html_text):
                rec.error = "soft-404: WTO page-not-found shell"
                log.warning("soft-404 skipped: %s", url_norm)
                self._write_manifest(rec)
                return
            self._save_raw(res.body, rec.raw_sha256, "html")
            rec.title = extract.extract_title(html_text)
            markdown = extract.extract_markdown(html_text, url_norm)
            # Harvest links once. Two independent uses:
            #   (1) rec.links = in-scope document edges -> relationship graph
            #       (recorded even if the target was already crawled or won't be
            #        crawled now; dangling edges are useful corpus-QA signal)
            #   (2) _enqueue -> crawl frontier (respects depth budget + dedup)
            edges: list[str] = []
            seen_edge: set[str] = set()
            for link in extract.extract_links(html_text, url_norm):
                norm = urlrules.normalize_url(link)
                if norm != url_norm and norm not in seen_edge and self._is_edge(norm):
                    seen_edge.add(norm)
                    edges.append(norm)
                # Large/media docs: log by URL, never download (colleague trick,
                # "情况 A" — record without a request).
                if urlrules.is_record_only_doc(norm) and self._is_edge(norm):
                    self._record_doc_ref(norm, url_norm)
                elif depth < self.max_depth:
                    self._enqueue(link, depth + 1, url_norm)
            rec.links = edges
        elif res.content_type == "pdf":
            # Teacher-review pass: download + classify + record, do NOT parse.
            # The teacher verifies the PDF inventory first; conversion to
            # Markdown (MinerU) happens in a later pass. Dedup on the raw-bytes
            # hash so the same PDF reached via different URLs is dropped.
            self._save_raw(res.body, rec.raw_sha256, "pdf")
            rec.content_hash = rec.raw_sha256
            canonical = (self.dedup.check_content(url_norm, rec.content_hash)
                         if rec.content_hash else None)
            if canonical is not None:
                rec.duplicate_of = canonical
                log.info("dup-pdf: %s == %s", url_norm, canonical)
                self._write_manifest(rec)
                return
            rec.category = classify.classify(url_norm, rec.title)
            rec.note = "PDF downloaded; pending parse (teacher review first)"
            log.info("kept-pdf [%s] %s (downloaded, not parsed)", rec.category, url_norm)
            self._write_manifest(rec)
            return
        elif res.content_type == "doc":
            # Non-PDF binary document (docx/xlsx/pptx/...). Save + record; we do
            # not convert to markdown now, but it is captured for the inventory
            # and can be parsed later. NOT an error.
            ext = url_norm.lower().split("?", 1)[0].rsplit(".", 1)[-1][:5] or "bin"
            self._save_raw(res.body, rec.raw_sha256, "doc", ext=ext)
            rec.category = classify.classify(url_norm, rec.title)
            rec.note = f"binary document ({ext}); saved, not converted to markdown"
            log.info("kept-doc [%s] %s (%s)", rec.category, url_norm, ext)
            self._write_manifest(rec)
            return
        else:
            rec.error = f"unhandled content-type: {res.content_type}"

        if not markdown:
            rec.error = rec.error or "no extractable content"
            self._write_manifest(rec)
            return

        # ---- content-level dedup ----
        rec.content_hash = dedup.hash_text(markdown)
        canonical = self.dedup.check_content(url_norm, rec.content_hash)
        if canonical is not None:
            rec.duplicate_of = canonical
            log.info("dup: %s == %s", url_norm, canonical)
            self._write_manifest(rec)
            return

        # ---- classify + write ----
        rec.category = classify.classify(url_norm, rec.title)
        out_name = f"{rec.content_hash[:16]}.md"
        out_path = self.out / "markdown" / out_name
        out_path.write_text(_front_matter(rec) + markdown, encoding="utf-8")
        rec.out_md_path = f"markdown/{out_name}"
        self.kept += 1
        log.info("kept [%s] %s -> %s", rec.category, url_norm, out_name)
        self._write_manifest(rec)

    def _save_raw(self, body: bytes, sha: str | None, kind: str,
                  ext: str | None = None) -> None:
        if not sha:
            return
        ext = ext or ("html" if kind == "html" else "pdf")
        subdir = self.out / "raw" / kind
        subdir.mkdir(parents=True, exist_ok=True)
        (subdir / f"{sha}.{ext}").write_bytes(body)

    def _write_manifest(self, rec: PageRecord) -> None:
        self.manifest_fp.write(json.dumps(rec.to_manifest(), ensure_ascii=False) + "\n")
        self.manifest_fp.flush()

    # ---------------- main loop ---------------- #

    async def run(self, seeds: list[str]) -> None:
        self.manifest_fp = (self.out / "manifest.jsonl").open("a", encoding="utf-8")
        self.external_fp = (self.out / "external_links.jsonl").open("a", encoding="utf-8")
        try:
            for s in seeds:
                self._enqueue(s, 0, None)

            async with Fetcher(self.concurrency, self.delay_s) as fetcher:
                while self.frontier:
                    if self.max_pages and self.kept >= self.max_pages:
                        log.info("hit max_pages=%s, stopping", self.max_pages)
                        break
                    # process a batch concurrently
                    batch = [self.frontier.popleft()
                             for _ in range(min(self.concurrency, len(self.frontier)))]
                    await asyncio.gather(*(self._handle(fetcher, u, d, s) for u, d, s in batch))
        finally:
            self.manifest_fp.close()
            self.external_fp.close()
            self._write_dedup_report()

    def _write_dedup_report(self) -> None:
        path = self.out / "dedup_report.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["duplicate_url", "canonical_url", "content_hash"])
            w.writeheader()
            w.writerows(self.dedup.report)


def load_visited(out_dir: Path, crawler: Crawler) -> tuple[int, int]:
    """Seed the visited set from an existing manifest for --resume.

    Only records that succeeded (no error) count as visited. Rows that errored
    (e.g. PDFs that failed because MinerU was missing) are intentionally left
    out of the visited set so a resumed run retries them.

    Returns (visited_loaded, retryable_skipped).
    """
    manifest = out_dir / "manifest.jsonl"
    if not manifest.exists():
        return 0, 0
    n = 0
    retry = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("error"):
            retry += 1          # leave out of visited -> will be retried
            continue
        if url := row.get("url_norm"):
            crawler.dedup.mark_url(url)
            if ch := row.get("content_hash"):
                crawler.dedup._content.setdefault(ch, url)
            n += 1
    return n, retry
