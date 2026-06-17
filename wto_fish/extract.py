"""HTML -> Markdown (content) and HTML -> links (frontier).

Markdown extraction prefers trafilatura (keeps links, tables, drops chrome).
Link harvesting uses selectolax to collect every <a href> and resolve it
against the page's base URL.
"""

from __future__ import annotations

from urllib.parse import urljoin

import trafilatura
from selectolax.parser import HTMLParser


def extract_markdown(html: str, url: str) -> str | None:
    """Return main-content Markdown, or None if nothing meaningful was found."""
    md = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=False,   # body text feeds embeddings; links live in manifest edges
        include_tables=True,
        include_comments=False,
        favor_recall=True,
    )
    if md and md.strip():
        return md

    # Fallback: WTO pages keep body text in a #pageContent / .content container.
    tree = HTMLParser(html)
    for sel in ("#pageContent", "div.content", "main", "article", "body"):
        node = tree.css_first(sel)
        if node:
            text = node.text(separator="\n", strip=True)
            if text.strip():
                return text
    return None


def extract_title(html: str) -> str | None:
    tree = HTMLParser(html)
    h1 = tree.css_first("h1")
    if h1 and h1.text(strip=True):
        return h1.text(strip=True)
    t = tree.css_first("title")
    return t.text(strip=True) if t else None


def extract_links(html: str, base_url: str) -> list[str]:
    """All absolute hrefs found on the page (deduped, order-preserving)."""
    tree = HTMLParser(html)
    seen: set[str] = set()
    out: list[str] = []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href")
        if not href:
            continue
        href = href.strip()
        if href.startswith(("mailto:", "javascript:", "#", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out
