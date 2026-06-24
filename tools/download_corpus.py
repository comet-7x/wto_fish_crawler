"""Download the verified-public fisheries PDFs into 渔业补贴文件库/机构/年份/.

Reads the per-body detail listings, dedups by doc code, keeps only the
empirically-verified downloadable docs (verified_pdf), and saves each English
PDF to:

    渔业补贴文件库/<NN_机构>/<年份>/<安全文件号>.pdf

Resumable: existing files are skipped. Restricted docs are never downloaded
(they stay in the index/xlsx only). After this, re-run build_index.py to fill
local_path.

Run:
    python tools/download_corpus.py --delay 0.4
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import httpx

ROOT = Path("渔业补贴文件库")
BODY_FOLDER = {
    "G/FS 委员会": "01_G-FS_渔业补贴委员会",
    "TN 谈判馆藏": "02_TN_谈判",
    "WT/MIN 部长会": "03_WT-MIN_部长会",
    "WT/L 总理事会": "04_WT-L_法律文本",
    "WT/LET 议定书": "05_WT-LET_接受书",
    "G/SCM 补贴通报": "06_G-SCM_补贴通报",
    "WT/GC 总理事会": "07_WT-GC_总理事会",
    "JOB/RL 室文件": "09_JOB-RL_室文件",
}
DETAIL_FILES = ["detail_GFS", "detail_TN", "detail_WTMIN", "detail_WTL", "detail_WTLET",
                "detail_GSCM", "detail_WTGC", "detail_RDTNRL", "detail_JOBRL"]
DM = Path("docs_manifest")


def _safe(symbol: str) -> str:
    name = symbol
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip()


def _year(date: str) -> str:
    m = re.match(r"\d{2}/\d{2}/(\d{4})", date or "")
    return m.group(1) if m else "未知年份"


def targets() -> list[dict]:
    seen: dict[str, dict] = {}
    for f in DETAIL_FILES:
        p = DM / f"{f}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                key = (r.get("doc_code") or "").strip() or r["symbol"]
                seen.setdefault(key, r)
    return [r for r in seen.values() if r.get("verified_pdf") and r.get("url")]


def main() -> int:
    ap = argparse.ArgumentParser(description="Download verified-public fisheries PDFs")
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    rows = targets()
    print(f"待下载 {len(rows)} 份 -> {ROOT}/")
    ok = skip = fail = 0
    with httpx.Client(headers={"User-Agent": "wto-fish-corpus-bot/1.0 (research)"},
                      follow_redirects=True, timeout=90.0, trust_env=False) as c:
        for i, r in enumerate(rows, 1):
            folder = ROOT / BODY_FOLDER.get(r["body"], r["body"].replace("/", "_")) / _year(r["date"])
            path = folder / f"{_safe(r['symbol'])}.pdf"
            if path.exists() and path.stat().st_size > 1000:
                skip += 1
                continue
            try:
                resp = c.get(r["url"])
                body = resp.content
                if resp.status_code == 200 and (body[:5] == b"%PDF-" or
                                                "pdf" in resp.headers.get("content-type", "").lower()):
                    folder.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                    ok += 1
                else:
                    fail += 1
                    print(f"  [miss] {r['symbol']}: HTTP {resp.status_code}")
            except httpx.HTTPError as e:
                fail += 1
                print(f"  [ERR ] {r['symbol']}: {type(e).__name__}")
            if i % 25 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)}  下载ok={ok} 跳过={skip} 失败={fail}")
            time.sleep(args.delay)
    print(f"\n完成：新下载 {ok} | 已存在跳过 {skip} | 失败 {fail} | 目标 {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
