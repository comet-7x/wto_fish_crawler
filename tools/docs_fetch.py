"""Tier-2 (docs.wto.org) probe + optional download for known document symbols.

Documents Online has no API and its search page is bot-gated, but the
``directdoc.aspx`` endpoint serves a PDF directly for a known symbol. This tool:
  1. maps each symbol to a directdoc URL (parentheses stripped, store prefix),
  2. probes store prefixes until one returns a real PDF,
  3. optionally downloads it, classifies it, and records everything to
     ``docs_manifest/docs_manifest.jsonl``.

These items are NOT part of the confirmed topic corpus — they are pending the
teacher's scope decision, so downstream (build_review) files them under a
"待确认" area and marks them accordingly.

Run:
    python tools/docs_fetch.py --download --out ./wto_fish_out_v6
    python tools/docs_fetch.py --symbol "TN/RL/W/100" --download --out ./wto_fish_out_v6
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote

import httpx

from wto_fish import classify

DIRECTDOC = "https://docs.wto.org/dol2fe/Pages/SS/directdoc.aspx"
STORE_PREFIXES = ("q", "e", "r", "s")  # try in order; q/e tend to be English/consolidated

# Default fisheries-subsidies symbols to probe. The TN/RL series at large needs
# the (bot-gated) search harvester to enumerate; these are the ones referenced
# from the topic pages plus the core ministerial/legal instruments.
DEFAULT_SYMBOLS = [
    "WT/MIN(22)/33",   # Ministerial Decision adopting the Agreement
    "WT/L/1144",       # Protocol of Amendment (insertion into the WTO Agreement)
    "WT/MIN(17)/64",   # MC11 fisheries-subsidies ministerial decision
    "TN/RL/31",        # Negotiating Group on Rules document referenced from topic pages
    "G/FS/1",          # Committee on Fisheries Subsidies — symbol guess (to confirm)
    "G/FS/W/1",
    "G/FS/M/1",
]


def symbol_to_filename(symbol: str, prefix: str) -> str:
    clean = symbol.replace("(", "").replace(")", "").strip().strip("/")
    return f"{prefix}:/{clean}.pdf"


def directdoc_url(symbol: str, prefix: str) -> str:
    return f"{DIRECTDOC}?filename={quote(symbol_to_filename(symbol, prefix), safe='')}&Open=True"


def series_of(symbol: str) -> str:
    s = symbol.upper()
    if s.startswith("WT/MIN"):
        return "WT/MIN"
    if s.startswith("WT/L"):
        return "WT/L"
    if s.startswith("TN/RL"):
        return "TN/RL"
    if s.startswith("G/FS"):
        return "G/FS"
    return "other"


def probe_symbol(client: httpx.Client, symbol: str, out: Path | None) -> dict:
    rec = {"symbol": symbol, "series": series_of(symbol),
           "category": classify.classify(symbol), "downloadable": False,
           "downloaded": False, "url": None, "store_prefix": None,
           "size": 0, "raw_path": None, "pending_scope": True}
    for prefix in STORE_PREFIXES:
        url = directdoc_url(symbol, prefix)
        try:
            r = client.get(url)
        except httpx.HTTPError:
            continue
        is_pdf = "pdf" in r.headers.get("content-type", "").lower() or r.content[:5] == b"%PDF-"
        if r.status_code == 200 and is_pdf and len(r.content) > 1000:
            rec.update(downloadable=True, url=url, store_prefix=prefix, size=len(r.content))
            if out is not None:
                docs = out / "raw" / "docs"
                docs.mkdir(parents=True, exist_ok=True)
                safe = symbol.replace("(", "").replace(")", "").replace("/", "_")
                path = docs / f"{safe}.pdf"
                path.write_bytes(r.content)
                rec.update(downloaded=True, raw_path=f"raw/docs/{path.name}")
            break
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe/download docs.wto.org symbols via directdoc")
    ap.add_argument("--symbol", action="append", help="extra symbol (repeatable)")
    ap.add_argument("--download", action="store_true", help="save PDFs that resolve")
    ap.add_argument("--out", default="./wto_fish_out_v6", help="crawl out dir (for raw/docs/)")
    ap.add_argument("--manifest", default="./docs_manifest/docs_manifest.jsonl")
    args = ap.parse_args()

    symbols = DEFAULT_SYMBOLS + (args.symbol or [])
    out = Path(args.out) if args.download else None
    man = Path(args.manifest)
    man.parent.mkdir(parents=True, exist_ok=True)

    recs = []
    with httpx.Client(headers={"User-Agent": "wto-fish-corpus-bot/1.0 (research)"},
                      timeout=60.0, follow_redirects=True) as client:
        for sym in symbols:
            rec = probe_symbol(client, sym, out)
            recs.append(rec)
            flag = "OK  " if rec["downloadable"] else "FAIL"
            print(f"  [{flag}] {sym:<16} {rec['category']:<22} "
                  f"{'prefix=' + rec['store_prefix'] if rec['store_prefix'] else ''} "
                  f"{rec['size'] or ''}")

    with man.open("w", encoding="utf-8") as f:
        for rec in recs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    ok = sum(1 for r in recs if r["downloadable"])
    print(f"\n{ok}/{len(recs)} symbols resolved. manifest: {man}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
