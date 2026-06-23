"""Per-document detail enumerator (full search view) for docs.wto.org.

Unlike docs_enumerate.py (which uses the stripped "scripted search" view), this
reads the NORMAL results view, where each row exposes the full metadata line:

    Access | Date | Size | Pages | Doc #

So we capture, for every matching document — PUBLIC and RESTRICTED alike, with
no download — symbol, series, downloadable?, date, size, page count, doc code.

Driven by the subject facet + a collection/symbol filter (same as the UI). Walks
every page via ASP.NET postback.

Run:
    python tools/docs_detail.py --filter 'CollectionList="TN"' --label "TN" \
        --out ./docs_manifest/detail_TN.jsonl
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import math
import re
import time
from pathlib import Path

import httpx

BASE = "https://docs.wto.org/dol2fe/Pages/FE_Search/FE_S_S006.aspx"
UA = "wto-fish-corpus-bot/1.0 (research; contact: zhihao7946@gmail.com)"

# The 8 fisheries subjects, OR'd, exactly as the WTO subject facet spells them.
SUBJECTS_OR = (
    '"fishing resources" OR '
    '"fishing capacities (marine fishing capacity, fishing capacity in the high seas)" OR '
    '"fishing (fishing activity)" OR "fishery services" OR "fishery" OR '
    '"fisheries subsidies" OR "fisheries policy" OR "fish stocks"'
)

HIDDEN = {k: re.compile(r'id="%s"\s+value="([^"]*)"' % k) for k in
          ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")}
TOTAL_RE = re.compile(r'hdntotalresults"\s*value="(\d+)"')
CURPAGE_RE = re.compile(r'ctl00_MainPlaceHolder_hdnCurrentPage"\s*value="(\d+)"')

# Per-record field spans (consistent template ids across rows).
F = {"access": "lbl024", "date": "lbl023", "size": "lbl051",
     "pages": "lbl049", "doc": "lbl046"}


def _enc(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


def _span(block: str, ctl: str, lbl: str) -> str:
    m = re.search(r'id="ctl00_MainPlaceHolder_dtlDocs_%s_%s"[^>]*>(.*?)</span>' % (ctl, lbl),
                  block, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()


def _symbol(block: str) -> str:
    m = re.search(r'directdoc\.aspx\?filename=([^"&]+\.pdf)', htmlmod.unescape(block), re.I)
    if m:
        return re.sub(r"^[A-Za-z]:/", "", m.group(1)).replace(".pdf", "")
    # restricted docs may have no english link: take the leading symbol text
    m = re.search(r'class="hitContainer">\s*(?:<[^>]+>\s*)*([A-Z][A-Z0-9/().\-]+)', block)
    return m.group(1) if m else "?"


def _url(block: str, symbol: str) -> str:
    """Official per-document URL: the English directdoc download link when the
    file is public; otherwise a catalogue-record link (search by symbol) that
    still opens the record and proves the document exists."""
    m = re.search(r'href="([^"]*directdoc\.aspx\?filename=[^"]+)"', htmlmod.unescape(block), re.I)
    if m:
        u = m.group(1)
        return u if u.startswith("http") else "https://docs.wto.org" + u
    from urllib.parse import quote
    return (f"{BASE}?Query={quote('(@Symbol= ' + symbol + ')')}"
            "&Language=ENGLISH&Context=FomerScriptedSearch&languageUIChanged=true")


# Document-symbol prefix -> body, ordered LONGEST/most-specific first so e.g.
# WT/LET is matched before WT/L, and RD/TN/RL before TN/RL. Covers the WTO
# Documents Online symbol nomenclature (the fisheries-relevant ones first).
SERIES_PREFIXES = (
    # fisheries negotiation + committee + legal track
    "RD/TN/RL", "TN/RL", "TN/C", "TN/MA", "TN/", "JOB/RL", "JOBS/GC", "JOB/GC",
    "G/FS", "G/SCM",
    "WT/MIN", "WT/LET", "WT/GC", "WT/L", "WT/CTE", "WT/COMTD", "WT/TPR",
    # other bodies (for clean labelling of any stray symbol)
    "G/AG", "G/ADP", "G/SPS", "G/TBT", "G/VAL", "G/LIC", "G/SG", "G/RO",
    "G/STR", "G/PSI", "G/IT", "G/MA", "G/TMB", "G/TRIMS", "G/TFA", "G/C",
    "WT/ACC", "WT/BFA", "WT/BOP", "WT/REG", "WT/DSB", "WT/DS", "WT/AB",
    "WT/TC", "WT/INF", "WT/TF", "WT/AFT", "WT/PCTF", "WT/DAILYB",
    "IP/", "S/", "GPA/", "PC/", "INF/", "JOB/", "G/", "WT/",
)


def series_of(sym: str) -> str:
    s = sym.upper().lstrip("> ")
    for p in SERIES_PREFIXES:
        if s.startswith(p):
            return p.rstrip("/")
    return s.split("/")[0] if "/" in s else s


def parse_page(h: str) -> list[dict]:
    out = []
    for block in h.split('class="hitContainer"')[1:]:
        block = 'class="hitContainer"' + block
        ctlm = re.search(r"dtlDocs_(ctl\d+)_", block)
        if not ctlm:
            continue
        ctl = ctlm.group(1)
        sym = _symbol(block)
        access = _span(block, ctl, F["access"])
        clean = re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", block)))
        tm = re.search(r'hitContainer">(.*?)\s*Access:', clean)
        title = tm.group(1).strip() if tm else ""
        out.append({
            "symbol": sym, "series": series_of(sym), "title": title,
            "downloadable": access.lower().startswith("unrestrict"),
            "access": access or "?",
            "url": _url(block, sym),
            "date": _span(block, ctl, F["date"]),
            "size": _span(block, ctl, F["size"]),
            "pages": _span(block, ctl, F["pages"]),
            "doc_code": _span(block, ctl, F["doc"]),
        })
    return out


def enumerate_detail(filter_clause: str, delay: float) -> list[dict]:
    url = (f"{BASE}?MetaCollection=WTO&SubjectList={_enc(SUBJECTS_OR)}"
           f"&{filter_clause}&Language=ENGLISH&SearchPage=FE_S_S001&languageUIChanged=true")
    seen: dict[str, dict] = {}
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True,
                      timeout=90.0, trust_env=False) as c:
        h = c.get(url).text
        tot = int(TOTAL_RE.search(h).group(1)) if TOTAL_RE.search(h) else 0
        pages = max(1, math.ceil(tot / 10))
        print(f"  total={tot} (~{pages} pages)")
        page = 0
        while True:
            for r in parse_page(h):
                seen.setdefault(r["symbol"] or f"row{len(seen)}", r)
            cur = CURPAGE_RE.search(h)
            cur = int(cur.group(1)) if cur else page
            if cur + 1 >= pages:
                break
            data = {"__EVENTTARGET": "ctl00$MainPlaceHolder$lnkNext", "__EVENTARGUMENT": "",
                    **{k: (HIDDEN[k].search(h).group(1) if HIDDEN[k].search(h) else "")
                       for k in HIDDEN}}
            time.sleep(delay)
            h = c.post(url, data=data).text
            page = cur + 1
            if page > pages + 3:
                break
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-document detail enumeration (full view)")
    ap.add_argument("--filter", required=True, help='e.g. CollectionList="TN" or SymbolList="G/FS*"')
    ap.add_argument("--label", required=True, help="body label for the records")
    ap.add_argument("--out", required=True)
    ap.add_argument("--delay", type=float, default=0.8)
    args = ap.parse_args()

    from urllib.parse import quote
    filt = args.filter.split("=", 1)
    clause = f"{filt[0]}={quote(filt[1])}"
    recs = enumerate_detail(clause, args.delay)
    for r in recs:
        r["body"] = args.label
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    dl = sum(1 for r in recs if r["downloadable"])
    print(f"{args.label}: {len(recs)} 条 (可下载 {dl} / 受限 {len(recs)-dl}) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
