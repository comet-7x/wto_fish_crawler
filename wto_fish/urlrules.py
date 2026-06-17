"""Pure URL logic — no network, no heavy deps. Unit-tested in tests/.

Three responsibilities:
  1. normalize_url   -> canonical string for visited-set + URL-level dedup
  2. is_english      -> URL-based language filter (WTO _e/_f/_s convention)
  3. decide_tier     -> T1_SITE / T2_DOCS / T3_EXTERNAL / REJECT
"""

from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from . import config
from .models import Tier

DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_url(url: str) -> str:
    """Canonicalize a URL so equivalent links collapse to one key.

    - lowercase scheme + host, drop default port
    - drop fragment
    - drop tracking params, sort remaining params (keeps docs.wto.org filename=)
    - collapse duplicate slashes in the path (but not in the scheme)
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    host = parts.hostname or ""
    host = host.lower()
    port = parts.port
    netloc = host
    if port is not None and str(port) != DEFAULT_PORTS.get(scheme, ""):
        netloc = f"{host}:{port}"

    path = parts.path or "/"
    while "//" in path:
        path = path.replace("//", "/")

    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in config.TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_pairs))

    return urlunsplit((scheme, netloc, path, query, ""))


def _filename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def is_english(url: str) -> bool:
    """True if the URL points at the English version (or is language-neutral).

    WTO convention:
      - path contains /english/  -> English; /french/ or /spanish/ -> not.
      - filename suffix _e -> English; _f / _s -> not.
    A resource with no language marker at all is treated as English-eligible
    (e.g. some docs.wto.org PDFs); downstream content checks can refine this.
    """
    parts = urlsplit(url)
    path = parts.path

    if config.NON_ENGLISH_PATH.search(path):
        return False

    m = config.LANG_SUFFIX.search(_filename(path))
    if m:
        return m.group(1).lower() == "e"

    # No explicit marker -> allow (language-neutral).
    return True


def _is_t1(host: str, path: str) -> bool:
    if host != config.T1_HOST:
        return False
    for prefix in config.T1_PATH_PREFIXES:
        if path.startswith(prefix):
            # Some prefixes are broad dirs gated by a keyword relevance regex.
            gate = config.T1_PREFIX_RELEVANCE.get(prefix)
            if gate is not None and not gate.search(path):
                continue
            return True
    return False


def _is_t2(host: str, query: str, path: str) -> bool:
    if host not in config.T2_HOSTS:
        return False
    # Unquote so the whitelist (WT/MIN, TN/RL ...) matches whether the URL is
    # raw (q:/WT/MIN...) or normalized (q%3A%2FWT%2FMIN...).
    haystack = unquote(f"{path}?{query}")
    return any(rx.search(haystack) for rx in config.DOC_SERIES_WHITELIST)


def decide_tier(url: str) -> Tier:
    """Classify a URL into a crawl tier."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    query = parts.query or ""

    if _is_t1(host, path):
        return Tier.T1_SITE
    if _is_t2(host, query, path):
        return Tier.T2_DOCS
    if host and host not in config.WTO_HOSTS:
        return Tier.T3_EXTERNAL
    # A wto host that matched no whitelist (e.g. unrelated /english/ page).
    return Tier.REJECT


def is_excluded(url: str) -> bool:
    """True if the URL matches a hard-exclude pattern (content-less shells)."""
    return any(rx.search(url) for rx in config.EXCLUDE_URL_PATTERNS)


def is_record_only_doc(url: str) -> bool:
    """True for large/media documents we log by URL but do not download."""
    u = url.lower().split("?", 1)[0]
    return u.endswith(config.DOC_RECORD_ONLY_SUFFIXES)


def should_crawl(url: str) -> bool:
    """Final gate for the frontier: not excluded AND crawlable tier AND English."""
    if is_excluded(url):
        return False
    tier = decide_tier(url)
    if tier not in (Tier.T1_SITE, Tier.T2_DOCS):
        return False
    if tier is Tier.T1_SITE and not is_english(url):
        return False
    return True
