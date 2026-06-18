"""All tunable rules live here: seeds, scope boundaries, classification.

Edit this file to change WHAT gets crawled. The rest of the code is mechanism.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# Seeds — where the crawl starts.
# --------------------------------------------------------------------------- #
SEEDS: list[str] = [
    # Topic gateway (the page you gave)
    "https://www.wto.org/english/tratop_e/rulesneg_e/fish_e/fish_e.htm",
    # Sibling pages confirmed to exist (seeding them directly makes the crawl
    # robust even if the gateway's link extraction misses one):
    "https://www.wto.org/english/tratop_e/rulesneg_e/fish_e/fish_intro_e.htm",
    "https://www.wto.org/english/tratop_e/rulesneg_e/fish_e/agreement_fisheries_subsidies_e.htm",
    "https://www.wto.org/english/tratop_e/rulesneg_e/fish_e/fish_acceptances_e.htm",
    "https://www.wto.org/english/tratop_e/rulesneg_e/fish_e/implementfishagreement22_e.htm",
    # The actual legal text lives in a different directory:
    "https://www.wto.org/english/docs_e/legal_e/fish_e.htm",
    # Publications / brochure:
    "https://www.wto.org/english/res_e/publications_e/fishagree_e.htm",
    # Items the broad-but-clean crawl reached via different paths; seeding them
    # directly guarantees coverage (they pass the news / minist relevance gates):
    "https://www.wto.org/english/news_e/news22_e/fish_08nov22_e.htm",
    "https://www.wto.org/english/news_e/news22_e/fish_10oct22_e.htm",
    "https://www.wto.org/english/thewto_e/minist_e/mc13_e/briefing_notes_e/fisheries_subsidies_e.htm",
]

# --------------------------------------------------------------------------- #
# Tier 1 — bounded site crawl on www.wto.org.
# A URL is Tier 1 iff host == www.wto.org AND path starts with one of these.
# --------------------------------------------------------------------------- #
T1_HOST = "www.wto.org"
T1_PATH_PREFIXES: tuple[str, ...] = (
    "/english/tratop_e/rulesneg_e/fish_e/",
    "/english/docs_e/legal_e/fish_e",          # legal text (htm + any fish_*)
    "/english/res_e/publications_e/fish",      # fisheries publications
    "/english/res_e/booksp_e/",                 # books/publications PDFs (gated below)
    "/english/news_e/",                         # news items (gated below)
    "/english/thewto_e/minist_e/",              # ministerial briefings (gated below)
)

# Some prefixes are broad directories with mostly unrelated content. For those,
# additionally require the path to match a relevance regex (a keyword gate).
# prefix -> regex; prefixes not listed here are accepted as-is.
FISH_RELEVANCE = re.compile(r"fish", re.IGNORECASE)
T1_PREFIX_RELEVANCE: dict[str, re.Pattern[str]] = {
    "/english/news_e/": FISH_RELEVANCE,
    "/english/thewto_e/minist_e/": FISH_RELEVANCE,
    "/english/res_e/booksp_e/": FISH_RELEVANCE,
}

# Backward-compat alias (kept so existing references/tests don't break).
NEWS_RELEVANCE = FISH_RELEVANCE

# --------------------------------------------------------------------------- #
# Tier 2 — WTO Documents Online (docs.wto.org). NOT link-followed; these are
# reached via direct document URLs. Only document symbols matching the
# whitelist are accepted. Confirm the Committee series symbol on the live site
# before trusting it (left as a best-effort guess).
# --------------------------------------------------------------------------- #
T2_HOSTS = ("docs.wto.org",)
DOC_SERIES_WHITELIST: tuple[re.Pattern[str], ...] = (
    re.compile(r"WT/MIN", re.IGNORECASE),       # ministerial decisions (incl. MIN(22)/33)
    re.compile(r"WT/L/", re.IGNORECASE),        # legal instruments (incl. L/1144 protocol)
    re.compile(r"TN/RL", re.IGNORECASE),        # Negotiating Group on Rules (fisheries subsidies)
    # re.compile(r"G/FS/", re.IGNORECASE),  # TODO: confirm Committee on Fisheries Subsidies symbol
)

# --------------------------------------------------------------------------- #
# Tier 3 — external. Logged to external_links.jsonl, never crawled.
# Anything not Tier 1 / Tier 2 and not on a wto host is Tier 3.
# --------------------------------------------------------------------------- #
WTO_HOSTS = ("www.wto.org", "docs.wto.org", "wto.org")

# --------------------------------------------------------------------------- #
# English-only filter (URL-based). WTO encodes language in the filename suffix
# (_e/_f/_s) and in the path (/english/ vs /french/ vs /spanish/).
# --------------------------------------------------------------------------- #
LANG_SUFFIX = re.compile(r"_(e|f|s)(?=\.[a-z0-9]+$)", re.IGNORECASE)
NON_ENGLISH_PATH = re.compile(r"/(french|spanish)/", re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Document handling (absorbed from the broad-spider approach).
# Current policy (teacher-review pass): convert only HTML -> Markdown. PDFs and
# all other binary/media formats below are fetched + saved + recorded in the
# manifest WITHOUT conversion, so the teacher can verify the inventory first;
# parsing happens in a later pass. Audio/video (.mp4/.mp3/...) are downloaded
# too, per the teacher-review requirement.
DOC_FETCH_SUFFIXES = (".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
                      ".txt", ".md", ".csv",
                      ".mp4", ".mp3", ".wav", ".mov", ".m4a", ".avi")
# Large archive formats: recorded by URL at discovery WITHOUT downloading
# (potentially huge, rarely useful as corpus). Media moved to fetch above.
DOC_RECORD_ONLY_SUFFIXES = (".zip", ".rar", ".7z", ".tar", ".gz")
# Content-types that signal a binary document even when the URL has no
# revealing extension (dynamic download endpoints).
DOC_CONTENT_TYPES = ("application/pdf", "application/msword",
                     "application/vnd", "application/zip",
                     "application/octet-stream",
                     "video/", "audio/")

# Tracking params to strip during URL normalization.
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                   "utm_content", "gclid", "fbclid"}

# Hard-exclude URLs that match these (checked before tier/English/crawl gates).
# Use for content-less shells that slip through the path whitelist, e.g. the
# interactive map iframe (no body text, misclassifies).
EXCLUDE_URL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"fish_map_iframe", re.IGNORECASE),
    re.compile(r"/error/", re.IGNORECASE),          # 404 shell pages
)

# --------------------------------------------------------------------------- #
# Classification rules — evaluated top-to-bottom, first match wins.
# Each rule: (compiled regex tested against url_norm, category).
# A final title-based pass and a default fallback run in classify.py.
# --------------------------------------------------------------------------- #
URL_CATEGORY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/docs_e/legal_e/fish"),                "legal_text"),
    (re.compile(r"/res_e/booksp_e/"),                    "publication"),  # publication PDFs
    (re.compile(r"agreement_fisheries_subsidies_e"),     "ratification"),
    (re.compile(r"fish_acceptances"),                    "ratification"),
    (re.compile(r"implementfishagreement"),              "implementation"),
    (re.compile(r"fish_fund"),                           "fish_fund"),
    (re.compile(r"/stories[_-]"),                        "case_story"),
    (re.compile(r"fish_intro"),                          "introduction"),
    (re.compile(r"fish_factsheet"),                      "publication"),
    (re.compile(r"information_session"),                 "publication"),
    (re.compile(r"/res_e/publications_e/"),              "publication"),
    (re.compile(r"/res_e/webcas_e/"),                    "publication"),
    # Media files are classified by extension first, so videos under /news_e/ or
    # /minist_e/ (and year-prefixed names like 2024_07_05_..._chair_update.mp4)
    # all group as multimedia rather than scattering across categories.
    (re.compile(r"\.(?:mp4|mp3|wav|mov|m4a|avi)$", re.IGNORECASE), "multimedia"),
    (re.compile(r"/news_e/"),                            "news"),
    (re.compile(r"/minist_e/"),                          "ministerial"),
    # Year-prefixed PDFs in the fish dir are external international instruments
    # republished by WTO (UNCLOS, UNFSA, PSMA, FAO CCRF ...). Keep after the
    # WTO-specific rules so e.g. an info-session PDF stays a publication.
    (re.compile(r"/(?:19|20)\d{2}_"),                    "international_instrument"),
    (re.compile(r"\bWT/MIN", re.IGNORECASE),             "mandate_decision"),
    (re.compile(r"\bWT/L/", re.IGNORECASE),              "mandate_decision"),
    (re.compile(r"\bTN/RL", re.IGNORECASE),              "negotiation_submission"),
    (re.compile(r"ngr_|/ngr"),                           "negotiation_submission"),
    (re.compile(r"\bG/FS", re.IGNORECASE),               "committee"),
    (re.compile(r"committee", re.IGNORECASE),            "committee"),
    (re.compile(r"/fish_e\.htm$"),                       "overview"),
]

TITLE_CATEGORY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"committee on fisheries subsidies", re.IGNORECASE), "committee"),
    (re.compile(r"notification|transparency", re.IGNORECASE),        "implementation"),
    (re.compile(r"negotiat", re.IGNORECASE),                         "negotiation_submission"),
    (re.compile(r"accept|ratif|instrument", re.IGNORECASE),          "ratification"),
]

DEFAULT_CATEGORY = "uncategorized"

# Corpus source tag — written to every record so WTO/IOTC data can share one
# Milvus collection later and be filtered by `source`.
SOURCE = "wto"

# --------------------------------------------------------------------------- #
# Politeness / fetch defaults.
# --------------------------------------------------------------------------- #
USER_AGENT = (
    "wto-fish-corpus-bot/1.0 (research; contact: you@example.com)"
)
DEFAULT_CONCURRENCY = 4
DEFAULT_DELAY_S = 1.0
DEFAULT_MAX_DEPTH = 4
REQUEST_TIMEOUT_S = 60.0
MAX_RETRIES = 3
