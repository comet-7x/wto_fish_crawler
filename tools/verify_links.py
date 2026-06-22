"""Empirically verify each document link in a detail listing.

The catalogue's "Access: Unrestricted/Restricted" label is WTO's own metadata.
This tool checks it against reality by GET-ing every link:

  IMPORTANT: HTTP 200 alone is NOT proof of a downloadable PDF — restricted docs
  also return 200, but with an HTML access/login page instead of the file. So we
  record both the status code AND whether the body is actually a PDF
  (Content-Type pdf or a %PDF- magic header). "真正可下载" = 200 AND is-PDF.

Annotates each record with http_status / content_type / verified_pdf and rewrites
the JSONL in place.

Run:
    python tools/verify_links.py --listing ./docs_manifest/detail_TN.jsonl --delay 0.3
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx


def verify(listing: Path, delay: float) -> None:
    rows = [json.loads(l) for l in listing.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = mismatch = 0
    with httpx.Client(headers={"User-Agent": "wto-fish-corpus-bot/1.0 (research)"},
                      follow_redirects=True, timeout=60.0, trust_env=False) as c:
        for i, r in enumerate(rows, 1):
            url = r.get("url")
            if not url:
                r["http_status"] = None; r["verified_pdf"] = False; continue
            try:
                # stream so we can read only the first bytes, not the whole PDF
                with c.stream("GET", url) as resp:
                    ct = resp.headers.get("content-type", "")
                    head = next(resp.iter_bytes(8), b"")
                    is_pdf = "pdf" in ct.lower() or head.startswith(b"%PDF-")
                    r["http_status"] = resp.status_code
                    r["content_type"] = ct.split(";")[0]
                    r["verified_pdf"] = bool(resp.status_code == 200 and is_pdf)
            except httpx.HTTPError as e:
                r["http_status"] = None; r["content_type"] = f"ERR:{type(e).__name__}"
                r["verified_pdf"] = False
            if r["verified_pdf"]:
                ok += 1
            # flag where the catalogue label and the empirical result disagree
            if r.get("downloadable") != r["verified_pdf"]:
                mismatch += 1
            if i % 50 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)}  真PDF={ok}  与标注不一致={mismatch}")
            time.sleep(delay)
    with listing.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{listing.name}: 真正可下载 {ok}/{len(rows)} | 与Access标注不一致 {mismatch} -> 已写回")


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify document links (200 AND is-PDF)")
    ap.add_argument("--listing", required=True, action="append",
                    help="detail JSONL (repeatable)")
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()
    for lst in args.listing:
        print(f"=== verify {lst} ===")
        verify(Path(lst), args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
