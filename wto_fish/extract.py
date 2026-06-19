"""HTML -> Markdown (content) and HTML -> links (frontier).

Markdown extraction prefers trafilatura (keeps links, tables, drops chrome).
Link harvesting uses selectolax to collect every <a href> and resolve it
against the page's base URL.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import trafilatura
from selectolax.parser import HTMLParser

# Recover `href="..."` values the lenient HTML parser drops inside malformed /
# deeply-nested markup (see extract_links).
_HREF_RE = re.compile(r"""<a\s[^>]*?href=["']([^"']+)["']""", re.IGNORECASE)


# WTO serves a soft-404 (HTTP 200 + a "page not found" shell) for dead URLs.
# This phrase is specific to that shell, so matching it won't hit real content.
_SOFT_404_RE = re.compile(r"page you are looking for might have been removed", re.IGNORECASE)


def is_soft_404(html: str) -> bool:
    """True if this HTML is the WTO 'page cannot be found' shell (a soft 404)."""
    return bool(_SOFT_404_RE.search(html))


def extract_markdown(html: str, url: str) -> str | None:
    """Return main-content Markdown, or None if nothing meaningful was found."""
    md = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,    # keep hrefs: WTO topic pages are link hubs; the
                               # URLs are needed for citations + to follow refs
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
    """All absolute hrefs found on the page (deduped, order-preserving).

    Primary pass: selectolax (<a href>). Supplement: a regex over the raw HTML
    recovers anchors selectolax drops inside malformed/nested markup. On WTO
    topic pages the parser silently loses sidebar links (observed: the
    chair-update .mp4 and the MC12 briefing page), which would otherwise leave
    in-scope English content uncrawled.
    """
    seen: set[str] = set()
    out: list[str] = []

    def _add(href: str | None) -> None:
        if not href:
            return
        href = href.strip()
        if href.startswith(("mailto:", "javascript:", "#", "tel:")):
            return
        absolute = urljoin(base_url, href)
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)

    tree = HTMLParser(html)
    for a in tree.css("a[href]"):
        _add(a.attributes.get("href"))
    for m in _HREF_RE.finditer(html):
        _add(m.group(1))
    return out
