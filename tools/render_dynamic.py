"""Re-render JS-heavy pages with a headless browser and rewrite their Markdown.

Our static crawler can't see content built by JavaScript at runtime (DataTables
tables, interactive maps, dynamic member lists). For the handful of such pages,
this tool loads them in headless Chromium (Playwright), waits for the scripts to
finish, then writes Markdown = trafilatura prose + every rendered <table>
converted to a Markdown table. It overwrites the page's existing .md in the
crawl dir (keeping the YAML front matter), so build_site_library picks it up.

Requires: playwright + chromium  (python -m playwright install chromium)

Run:
    python tools/render_dynamic.py --out ./site_out \
        --url https://www.wto.org/english/tratop_e/rulesneg_e/fish_e/fish_acceptances_e.htm
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from wto_fish import extract

UA = "wto-fish-corpus-bot/1.0 (research; contact: zhihao7946@gmail.com)"
# Pages on the fisheries site whose key content is JS-rendered.
DEFAULT_URLS = [
    "https://www.wto.org/english/tratop_e/rulesneg_e/fish_e/fish_acceptances_e.htm",
]


def _tables_md(page) -> list[str]:
    out = []
    for t in page.query_selector_all("table"):
        heads = [th.inner_text().strip() for th in t.query_selector_all("thead th")]
        rows = []
        for tr in t.query_selector_all("tbody tr"):
            cells = [td.inner_text().strip().replace("\n", " ").replace("|", "\\|")
                     for td in tr.query_selector_all("td")]
            if any(cells):
                rows.append(cells)
        if not rows:
            continue
        if not heads:
            heads = [""] * len(rows[0])
        md = ("| " + " | ".join(heads) + " |\n|" + "|".join(["---"] * len(heads)) + "|\n"
              + "\n".join("| " + " | ".join(r) + " |" for r in rows))
        out.append(md)
    return out


def render(url: str, browser) -> str:
    pg = browser.new_page(user_agent=UA)
    try:
        pg.goto(url, wait_until="networkidle", timeout=60000)
        try:
            pg.wait_for_selector("table tbody tr", timeout=15000)
        except Exception:  # noqa: BLE001  — page may have no table
            pass
        html = pg.content()
        tables = _tables_md(pg)
    finally:
        pg.close()
    prose = extract.extract_markdown(html, url) or ""
    body = prose
    if tables:
        body += "\n\n" + "\n\n".join(tables)
    return body


def md_path_for(out: Path, url: str) -> Path | None:
    for line in (out / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("url") == url and r.get("out_md_path"):
            return out / r["out_md_path"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-render JS pages and rewrite their Markdown")
    ap.add_argument("--out", required=True, help="crawl dir (manifest.jsonl, markdown/)")
    ap.add_argument("--url", action="append", help="page URL (repeatable); default = known dynamic pages")
    args = ap.parse_args()
    out = Path(args.out)
    urls = args.url or DEFAULT_URLS

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for url in urls:
                body = render(url, browser)
                mp = md_path_for(out, url)
                if not mp or not mp.exists():
                    print(f"  [skip] no markdown for {url}")
                    continue
                old = mp.read_text(encoding="utf-8")
                fm = old.split("---\n", 2)
                front = f"---\n{fm[1]}---\n" if len(fm) >= 3 else ""
                mp.write_text(front + body + "\n", encoding="utf-8")
                tbl = body.count("|\n|")
                print(f"  [ok] {url.rsplit('/', 1)[-1]} -> {mp.name}  ({len(body)} chars, ~{tbl} table rows)")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
