"""Stage 2 of Tier-2 (docs.wto.org): browser-driven search-result harvester.

Documents Online is an ASP.NET WebForms app (VIEWSTATE, tab controls,
autocomplete widgets). Reverse-engineering its POST is brittle, so we drive the
real page with Playwright. The harvester ENUMERATES (symbol/title/date/doc-link)
into a manifest — it does NOT download document bodies. Downloading happens
later, after you and your teacher pick which series to keep.

ROBUSTNESS NOTE:
  Result scraping anchors on the `directdoc.aspx` links that every result row
  contains (the same link the probe confirmed works). That avoids depending on
  the deep ctl00$... result-cell selectors. The only selectors you must confirm
  for YOUR session are the SEARCH INPUT and SEARCH BUTTON (and the NEXT-page
  control). Discover them in 30s with:

      playwright codegen "https://docs.wto.org/dol2fe/Pages/FE_Search/FE_S_S001.aspx"

  do one symbol search, and paste the recorded selectors into CONFIG below.

Install:
    pip install playwright
    playwright install chromium

Run:
    # full-text search (uses the field we already identified from your grep)
    python tools/docs_harvest.py --fulltext "fisheries subsidies" --out ./docs_manifest

    # symbol-series search (set SYMBOL_INPUT below first)
    python tools/docs_harvest.py --symbol "TN/RL/" --out ./docs_manifest

    # if search/restricted docs need login, run headed and log in manually:
    python tools/docs_harvest.py --fulltext "fisheries subsidies" --headed --login
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

SEARCH_URL = "https://docs.wto.org/dol2fe/Pages/FE_Search/FE_S_S001.aspx"

# --------------------------------------------------------------------------- #
# CONFIG — confirm these against YOUR rendered page (playwright codegen).
# --------------------------------------------------------------------------- #
# Full-text / title search box — identified from your grep:
FULLTEXT_INPUT = (
    "input[name='ctl00$MainPlaceHolder$tabFE_S_S001$tab001$"
    "DocumentTitleFTSTextBoxWUC1$txt022$txtFts']"
)
# Document-symbol input — NOT yet identified (was below your head -40 cut).
# Find it via codegen and paste here (likely ...$DocumentSymbol...$txt...).
SYMBOL_INPUT = "TODO_SET_SYMBOL_INPUT_SELECTOR"
# Search button — likely btn039 or btn040 from your grep; confirm which:
SEARCH_BUTTON = "input[name='ctl00$MainPlaceHolder$tabFE_S_S001$tab001$btn039']"
# Next-page control in the results pager — confirm via codegen (text 'Next' / '>>').
NEXT_LINK_TEXTS = ("Next", "next", ">", ">>", "›")

RESULTS_READY = "a[href*='directdoc.aspx']"   # a result row exists once these appear

# directdoc filename -> symbol; handles q:/..., q%3A%2F..., and bare WT/L/...
_SYMBOL_RX = re.compile(r"filename=(?:[a-z](?::|%3[Aa]))?(?:/|%2[Ff])?([^&]+?)\.pdf", re.I)


def harvest_page(page: Page) -> list[dict]:
    """Scrape all result rows on the current results page via directdoc anchors."""
    out: list[dict] = []
    anchors = page.locator(RESULTS_READY)
    n = anchors.count()
    for i in range(n):
        a = anchors.nth(i)
        href = a.get_attribute("href") or ""
        # absolute URL
        doc_url = href if href.startswith("http") else f"https://docs.wto.org{href}"
        # symbol from the filename param if present
        m = _SYMBOL_RX.search(doc_url)
        symbol = (m.group(1).replace("%2F", "/").replace("%2f", "/")
                  if m else (a.inner_text() or "").strip())
        # row context: nearest table row text for title/date
        try:
            row_text = a.evaluate(
                "el => { const tr = el.closest('tr'); return tr ? tr.innerText : el.innerText; }"
            ) or ""
        except Exception:  # noqa: BLE001
            row_text = ""
        date = ""
        dm = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b", row_text)
        if dm:
            date = dm.group(1)
        out.append({
            "symbol": symbol.strip("/ "),
            "title": " ".join(row_text.split()),
            "date": date,
            "doc_url": doc_url,
        })
    return out


def click_next(page: Page) -> bool:
    """Try to advance to the next results page. Returns False when no next page."""
    for txt in NEXT_LINK_TEXTS:
        link = page.get_by_role("link", name=re.compile(rf"^\s*{re.escape(txt)}\s*$"))
        if link.count() and link.first.is_enabled():
            try:
                link.first.click()
                page.wait_for_load_state("networkidle", timeout=30000)
                return True
            except PWTimeout:
                return False
    return False


def run(query: str, by_symbol: bool, out_dir: Path, headed: bool,
        login: bool, max_pages: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = (out_dir / "docs_manifest.jsonl").open("w", encoding="utf-8")
    seen: set[str] = set()
    kept = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        page.goto(SEARCH_URL, wait_until="networkidle")

        if login:
            print(">> Log in in the opened browser, then press Enter here...")
            input()

        selector = SYMBOL_INPUT if by_symbol else FULLTEXT_INPUT
        if by_symbol and selector.startswith("TODO"):
            print("ERROR: SYMBOL_INPUT not set. Use --fulltext, or set the selector "
                  "in CONFIG (find it via `playwright codegen`).", file=sys.stderr)
            return 2

        page.fill(selector, query)
        page.click(SEARCH_BUTTON)
        try:
            page.wait_for_selector(RESULTS_READY, timeout=30000)
        except PWTimeout:
            print("No results appeared. Check selectors / login / query.", file=sys.stderr)
            browser.close()
            return 1

        for pg in range(1, max_pages + 1):
            rows = harvest_page(page)
            new = 0
            for r in rows:
                if r["doc_url"] in seen:
                    continue
                seen.add(r["doc_url"])
                manifest.write(json.dumps(r, ensure_ascii=False) + "\n")
                kept += 1
                new += 1
            print(f"  page {pg}: {len(rows)} rows, {new} new (total {kept})")
            if not click_next(page):
                print("  no next page.")
                break
            time.sleep(1.0)  # politeness

        browser.close()

    manifest.close()
    print(f"\nDone. {kept} unique documents listed -> {out_dir/'docs_manifest.jsonl'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Harvest WTO Documents Online search results (list only)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol", help="document-symbol prefix, e.g. 'TN/RL/'")
    g.add_argument("--fulltext", help="full-text query, e.g. 'fisheries subsidies'")
    ap.add_argument("--out", default="./docs_manifest", help="output dir")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--login", action="store_true", help="pause for manual login")
    ap.add_argument("--max-pages", type=int, default=50)
    args = ap.parse_args()

    by_symbol = args.symbol is not None
    query = args.symbol if by_symbol else args.fulltext
    return run(query, by_symbol, Path(args.out), args.headed, args.login, args.max_pages)


if __name__ == "__main__":
    raise SystemExit(main())
