"""Enumerate a docs.wto.org document series via the scripted-search endpoint.

Documents Online's interactive search is bot-gated, but the legacy
``FE_S_S006.aspx`` "FomerScriptedSearch" view answers a symbol query over plain
HTTP and paginates by ASP.NET postback (carry __VIEWSTATE, fire ``lnkNext``).
This tool walks every page of a symbol query, parses one record per result
(symbol, title, date/meeting line, English directdoc link), and writes the
listing to JSONL. It also flags fisheries-relevant records by title keyword.

ENUMERATION ONLY — it does not download the PDFs. Feed the resulting symbols to
``docs_fetch.py`` once the teacher decides which to keep.

Run:
    python tools/docs_enumerate.py --query "(@Symbol= TN/RL/*)" \
        --out ./docs_manifest/tn_rl_listing.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from urllib.parse import quote

import httpx

BASE = "https://docs.wto.org/dol2fe/Pages/FE_Search/FE_S_S006.aspx"
UA = "wto-fish-corpus-bot/1.0 (research; contact: zhihao7946@gmail.com)"

# Title keywords that mark a record as fisheries-subsidies relevant.
FISH_RE = re.compile(
    r"fish|fisher|fishing|overfish|overcapacit|IUU|illegal[,\s].{0,20}unreported|"
    r"marine\s+capture|subsidies\s+(?:to|for)\s+fish",
    re.IGNORECASE)

HIDDEN_RE = {k: re.compile(r'id="%s"\s+value="([^"]*)"' % k) for k in
             ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")}
TOTAL_RE = re.compile(r'hdntotalresults"\s*value="(\d+)"')
CURPAGE_RE = re.compile(r'ctl00_MainPlaceHolder_hdnCurrentPage"\s*value="(\d+)"')
ACCESS_RE = re.compile(r'Access:\s*(?:<[^>]+>\s*)*(\w+)', re.S)
ENLINK_RE = re.compile(
    r'class="hitEnFileLink".*?directdoc\.aspx\?filename=([^"&]+)', re.S | re.I)


def _hidden(html: str, name: str) -> str:
    m = HIDDEN_RE[name].search(html)
    return m.group(1) if m else ""


def _clean(text: str) -> str:
    return re.sub(r"\s{2,}", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def parse_page(html: str) -> list[dict]:
    """One record per hitContainer: symbol, title line, English directdoc URL.

    Each record's markup runs from its ``hitContainer`` marker to its ``Access:``
    label, so we split on the marker and cut each chunk at Access:.
    """
    recs = []
    for raw in html.split('class="hitContainer"')[1:]:
        am = ACCESS_RE.search(raw)
        chunk = raw[:am.start()] if am else raw
        access = am.group(1) if am else ""
        m = ENLINK_RE.search(raw)            # English link may sit just after Access:
        filename = m.group(1) if m else None
        symbol = re.sub(r"^[A-Za-z]:/", "", filename).replace(".pdf", "") if filename else None
        text = _clean(chunk).lstrip("> ").strip()
        recs.append({
            "symbol": symbol,
            "text": text,
            "english_url": (f"https://docs.wto.org/dol2fe/Pages/SS/directdoc.aspx?"
                            f"filename={quote(filename, safe='')}&Open=True") if filename else None,
            "access": access,
            "fisheries": bool(FISH_RE.search(text)),
        })
    return recs


def enumerate_series(query: str, delay: float) -> list[dict]:
    url = f"{BASE}?Query={quote(query)}&Language=ENGLISH&Context=FomerScriptedSearch&languageUIChanged=true"
    out: dict[str, dict] = {}
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=90.0) as c:
        html = c.get(url).text
        total = int(TOTAL_RE.search(html).group(1)) if TOTAL_RE.search(html) else 0
        pages = max(1, math.ceil(total / 10))
        print(f"total results: {total}  (~{pages} pages)")
        page = 0
        while True:
            for r in parse_page(html):
                key = r["symbol"] or r["text"][:40]
                out.setdefault(key, r)
            cur = CURPAGE_RE.search(html)
            cur = int(cur.group(1)) if cur else page
            print(f"  page {cur + 1}/{pages}: collected {len(out)}")
            if cur + 1 >= pages:
                break
            data = {"__EVENTTARGET": "ctl00$MainPlaceHolder$lnkNext", "__EVENTARGUMENT": "",
                    "__VIEWSTATE": _hidden(html, "__VIEWSTATE"),
                    "__VIEWSTATEGENERATOR": _hidden(html, "__VIEWSTATEGENERATOR"),
                    "__EVENTVALIDATION": _hidden(html, "__EVENTVALIDATION")}
            time.sleep(delay)
            html = c.post(url, data=data).text
            page = cur + 1
            if page > pages + 2:  # safety
                break
    return list(out.values())


def main() -> int:
    ap = argparse.ArgumentParser(description="Enumerate a docs.wto.org series (listing only)")
    ap.add_argument("--query", default="(@Symbol= TN/RL/*)", help="DOL symbol query")
    ap.add_argument("--out", default="./docs_manifest/tn_rl_listing.jsonl")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--fisheries-only", action="store_true",
                    help="write only records whose title flags fisheries")
    args = ap.parse_args()

    recs = enumerate_series(args.query, args.delay)
    if args.fisheries_only:
        recs = [r for r in recs if r["fisheries"]]
    fish = sum(1 for r in recs if r["fisheries"])
    from pathlib import Path
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nrecords: {len(recs)} | fisheries-flagged: {fish}")
    print(f"listing: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
