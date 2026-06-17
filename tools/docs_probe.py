"""Stage 1 of Tier-2 (docs.wto.org): connectivity + direct-fetch probe.

WHAT THIS DOES (and does NOT do):
  - It verifies that, given a KNOWN document symbol, the Documents Online
    direct-doc URL returns the PDF. This confirms the access path before we
    invest in the (heavier) search-driven harvest.
  - It does NOT search/enumerate. Documents Online is an ASP.NET WebForms app
    with no JSON API; enumeration needs a browser-driven harvester (stage 2),
    written once this probe confirms the path works on your network.

WHY a probe first: same discipline as your IOTC manifest run — verify one known
document downloads before scaling out.

Run:
    python tools/docs_probe.py
    python tools/docs_probe.py --out ./docs_probe_out --save
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import quote

import httpx

# Documents Online direct-document endpoint.
DIRECTDOC = "https://docs.wto.org/dol2fe/Pages/SS/directdoc.aspx"

# The `filename` value uses a store prefix + the document symbol with
# parentheses removed, e.g.  WT/MIN(22)/33  ->  q:/WT/MIN22/33.pdf
# `q:` is the prefix used by the known-working public citation for MIN(22)/33.
# If `q:` does not yield the English PDF for a given symbol, try the language
# prefixes below (confirmed by inspecting a working link in your browser).
STORE_PREFIXES = ("q", "e", "r")  # q=consolidated, e/r seen on some docs

# Known fisheries-subsidies symbols to probe. Extend as you confirm more.
KNOWN_SYMBOLS = [
    "WT/MIN(22)/33",   # Ministerial Decision adopting the Agreement
    "WT/L/1144",       # Protocol of Amendment
    # add confirmed TN/RL/... negotiating-group symbols here once known
]


def symbol_to_filename(symbol: str, prefix: str = "q") -> str:
    """Map a document symbol to a Documents Online `filename` value.

    WT/MIN(22)/33 -> q:/WT/MIN22/33.pdf
    Parentheses are stripped; the symbol path is otherwise preserved.
    """
    clean = symbol.replace("(", "").replace(")", "").strip().strip("/")
    return f"{prefix}:/{clean}.pdf"


def directdoc_url(symbol: str, prefix: str = "q") -> str:
    """Full direct-fetch URL for a symbol."""
    filename = symbol_to_filename(symbol, prefix)
    return f"{DIRECTDOC}?filename={quote(filename, safe='')}&Open=True"


def probe(symbols: list[str], out: Path | None) -> int:
    headers = {"User-Agent": "wto-fish-corpus-bot/1.0 (research)"}
    ok = 0
    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        for sym in symbols:
            hit = False
            for prefix in STORE_PREFIXES:
                url = directdoc_url(sym, prefix)
                try:
                    r = client.get(url)
                except httpx.HTTPError as e:
                    print(f"  [ERR ] {sym:<16} prefix={prefix}  {type(e).__name__}: {e}")
                    continue
                ctype = r.headers.get("content-type", "")
                is_pdf = "pdf" in ctype.lower() or r.content[:5] == b"%PDF-"
                size = len(r.content)
                if r.status_code == 200 and is_pdf and size > 1000:
                    print(f"  [ OK ] {sym:<16} prefix={prefix}  {size:>8} bytes  {ctype}")
                    ok += 1
                    hit = True
                    if out:
                        out.mkdir(parents=True, exist_ok=True)
                        fn = sym.replace("(", "").replace(")", "").replace("/", "_") + ".pdf"
                        (out / fn).write_bytes(r.content)
                    break
                else:
                    print(f"  [miss] {sym:<16} prefix={prefix}  HTTP {r.status_code} "
                          f"{size} bytes {ctype[:40]}")
            if not hit:
                print(f"  [FAIL] {sym:<16} no prefix returned a PDF — inspect a working "
                      f"link in your browser and adjust STORE_PREFIXES / mapping")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe WTO Documents Online direct-fetch path")
    ap.add_argument("--save", action="store_true", help="save fetched PDFs")
    ap.add_argument("--out", default="./docs_probe_out", help="dir for saved PDFs")
    ap.add_argument("--symbol", action="append", help="extra symbol to probe (repeatable)")
    args = ap.parse_args()

    symbols = KNOWN_SYMBOLS + (args.symbol or [])
    print(f"Probing {len(symbols)} symbol(s) against {DIRECTDOC}\n")
    out = Path(args.out) if args.save else None
    ok = probe(symbols, out)
    print(f"\n{ok}/{len(symbols)} symbol(s) fetched successfully.")
    if ok == 0:
        print("Path NOT confirmed. Check: network reachability to docs.wto.org, "
              "VPN/login requirements, or the filename mapping.")
        return 1
    print("Path confirmed. Ready to build stage-2 search harvester.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
