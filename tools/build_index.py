"""Build the metadata index for the fisheries-subsidies document set.

Merges the per-body detail listings (dedup by doc code) into ONE clean, typed
table and writes it as:
  * CSV    — 渔业补贴文件索引.csv  (utf-8-sig; opens in Excel, queryable by DuckDB)
  * SQLite — 渔业补贴文件索引.sqlite (table `documents`; for text-to-SQL)

Typed columns (year/pages INTEGER, size_kb REAL, downloadable 0/1) so natural-
language -> SQL works, and `title` is a clean field to embed for index-level
vector search. PDF body text / local_path are filled later, after download.

Run:
    python tools/build_index.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path

DM = Path("docs_manifest")
# Body label -> ordered folder name (matches the planned 渔业补贴文件库/ layout).
BODY_FOLDER = {
    "G/FS 委员会": "01_G-FS_渔业补贴委员会",
    "TN 谈判馆藏": "02_TN_谈判",
    "WT/MIN 部长会": "03_WT-MIN_部长会",
    "WT/L 总理事会": "04_WT-L_法律文本",
    "WT/LET 议定书": "05_WT-LET_接受书",
    "G/SCM 补贴通报": "06_G-SCM_补贴通报",
    "WT/GC 总理事会": "07_WT-GC_总理事会",
    "RD/TN/RL 谈判室": "08_RD-TN-RL_谈判室(受限)",
    "JOB/RL 室文件": "09_JOB-RL_室文件",
}
DETAIL_FILES = ["detail_GFS", "detail_TN", "detail_WTMIN", "detail_WTL", "detail_WTLET",
                "detail_GSCM", "detail_WTGC", "detail_RDTNRL", "detail_JOBRL"]

COLUMNS = ["doc_code", "symbol", "title", "body", "series", "year", "date",
           "size_kb", "pages", "access", "downloadable", "http_status",
           "subjects", "local_path", "url"]


def _int(s: str) -> int | None:
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else None


def _size_kb(s: str) -> float | None:
    m = re.search(r"([\d.,]+)\s*(KB|MB|GB)", s or "", re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return round(n * {"KB": 1, "MB": 1024, "GB": 1024 * 1024}[m.group(2).upper()], 1)


def _iso(date: str) -> str:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", date or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def _safe(symbol: str) -> str:
    name = symbol
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip()


CORPUS_ROOT = Path("渔业补贴文件库")


def _year_folder(date_iso: str) -> str:
    return date_iso[:4] if date_iso else "未知年份"


def _local_path(body: str, symbol: str, date_iso: str) -> str:
    """Relative path of the downloaded PDF if it exists on disk, else ''."""
    folder = BODY_FOLDER.get(body, body.replace("/", "_"))
    p = CORPUS_ROOT / folder / _year_folder(date_iso) / f"{_safe(symbol)}.pdf"
    return str(p).replace("\\", "/") if p.exists() else ""


def _subject_tags() -> dict[str, list[str]]:
    p = DM / "subject_tags.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_rows() -> list[dict]:
    tags = _subject_tags()
    seen: dict[str, dict] = {}
    for f in DETAIL_FILES:
        p = DM / f"{f}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r.get("doc_code") or "").strip() or r["symbol"]
            seen.setdefault(key, r)
    rows = []
    for key, r in seen.items():
        iso = _iso(r.get("date", ""))
        rows.append({
            "doc_code": r.get("doc_code", ""),
            "symbol": r["symbol"],
            "title": r.get("title", ""),
            "body": r["body"],
            "series": r.get("series", ""),
            "year": int(iso[:4]) if iso else None,
            "date": iso,
            "size_kb": _size_kb(r.get("size", "")),
            "pages": _int(r.get("pages", "")),
            "access": "公开" if r.get("downloadable") else "受限",
            "downloadable": 1 if r.get("verified_pdf") else 0,   # empirical
            "http_status": r.get("http_status"),
            "subjects": "; ".join(tags.get(key, [])),
            "local_path": _local_path(r["body"], r["symbol"], iso),
            "url": r.get("url", ""),
        })
    rows.sort(key=lambda r: (r["body"], r["series"], r["symbol"]))
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def write_sqlite(rows: list[dict], path: Path) -> None:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute(f"""CREATE TABLE documents (
        doc_code TEXT, symbol TEXT, title TEXT, body TEXT, series TEXT,
        year INTEGER, date TEXT, size_kb REAL, pages INTEGER,
        access TEXT, downloadable INTEGER, http_status INTEGER,
        subjects TEXT, local_path TEXT, url TEXT)""")
    con.executemany(
        f"INSERT INTO documents VALUES ({','.join('?' * len(COLUMNS))})",
        [[r[c] for c in COLUMNS] for r in rows])
    con.execute("CREATE INDEX idx_body ON documents(body)")
    con.execute("CREATE INDEX idx_year ON documents(year)")
    con.commit()
    con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Build fisheries-doc metadata index (CSV + SQLite)")
    ap.add_argument("--csv", default="./渔业补贴文件索引.csv")
    ap.add_argument("--sqlite", default="./渔业补贴文件索引.sqlite")
    args = ap.parse_args()
    rows = load_rows()
    write_csv(rows, Path(args.csv))
    write_sqlite(rows, Path(args.sqlite))
    dl = sum(r["downloadable"] for r in rows)
    print(f"index: {len(rows)} 行 (实测可下 {dl} / 受限 {len(rows)-dl})")
    print(f"  CSV    -> {args.csv}")
    print(f"  SQLite -> {args.sqlite}  (table: documents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
