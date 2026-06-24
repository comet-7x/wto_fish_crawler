"""Tag each document with which of the 8 fisheries subjects it carries.

The per-body listings were enumerated with all 8 subjects OR'd, so we don't yet
know which subject(s) each document has. This runs one search per (body,
subject), collects the matching doc keys, and writes a map

    doc_key -> ["fisheries subsidies", "fishery", ...]

to docs_manifest/subject_tags.json. build_index.py then fills the `subjects`
column, enabling precise per-subject SQL/vector filtering.

Run:
    python tools/tag_subjects.py --delay 0.4
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from urllib.parse import quote

import httpx

import docs_detail as dd

SUBJECTS = [
    "fish stocks", "fisheries subsidies", "fishery", "fishery services",
    "fishing (fishing activity)",
    "fishing capacities (marine fishing capacity, fishing capacity in the high seas)",
    "fisheries policy", "fishing resources",
]
# (label, filter param, value) — the 9 in-scope bodies.
BODIES = [
    ("TN", "CollectionList", '"TN"'),
    ("G/FS", "SymbolList", '"G/FS*"'),
    ("WT/MIN", "SymbolList", '"WT/MIN*"'),
    ("WT/L", "SymbolList", '"WT/L/*"'),
    ("WT/LET", "SymbolList", '"WT/LET*"'),
    ("G/SCM", "SymbolList", '"G/SCM*"'),
    ("WT/GC", "SymbolList", '"WT/GC*"'),
    ("RD/TN/RL", "SymbolList", '"RD/TN/RL*"'),
    ("JOB/RL", "SymbolList", '"JOB/RL*"'),
]


def _key(rec: dict) -> str:
    return (rec.get("doc_code") or "").strip() or rec["symbol"]


def collect(client: httpx.Client, body_filter: str, subject: str, delay: float) -> set[str]:
    url = (f"{dd.BASE}?MetaCollection=WTO&SubjectList={quote(chr(34) + subject + chr(34))}"
           f"&{body_filter}&Language=ENGLISH&SearchPage=FE_S_S001&languageUIChanged=true")
    keys: set[str] = set()
    h = client.get(url).text
    tot = int(dd.TOTAL_RE.search(h).group(1)) if dd.TOTAL_RE.search(h) else 0
    if tot == 0:
        return keys
    pages = max(1, math.ceil(tot / 10))
    page = 0
    while True:
        for rec in dd.parse_page(h):
            keys.add(_key(rec))
        cur = dd.CURPAGE_RE.search(h)
        cur = int(cur.group(1)) if cur else page
        if cur + 1 >= pages:
            break
        data = {"__EVENTTARGET": "ctl00$MainPlaceHolder$lnkNext", "__EVENTARGUMENT": "",
                **{k: (dd.HIDDEN[k].search(h).group(1) if dd.HIDDEN[k].search(h) else "")
                   for k in dd.HIDDEN}}
        time.sleep(delay)
        h = client.post(url, data=data).text
        page = cur + 1
        if page > pages + 3:
            break
    return keys


def main() -> int:
    ap = argparse.ArgumentParser(description="Tag documents by fisheries subject")
    ap.add_argument("--out", default="./docs_manifest/subject_tags.json")
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    tags: dict[str, list[str]] = {}
    with httpx.Client(headers={"User-Agent": dd.UA}, follow_redirects=True,
                      timeout=90.0, trust_env=False) as c:
        for blabel, param, val in BODIES:
            for subj in SUBJECTS:
                bf = f"{param}={quote(val)}"
                for attempt in range(3):
                    try:
                        keys = collect(c, bf, subj, args.delay)
                        break
                    except httpx.HTTPError:
                        time.sleep(2)
                else:
                    keys = set()
                for k in keys:
                    tags.setdefault(k, [])
                    if subj not in tags[k]:
                        tags[k].append(subj)
                if keys:
                    print(f"  {blabel:10} | {subj:28} -> {len(keys)}")
                time.sleep(args.delay)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(tags, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n打标签文件 {len(tags)} 份 -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
