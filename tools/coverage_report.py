"""Coverage & evidence report for the WTO fisheries-subsidies corpus.

Produces an *auditable* account of what was collected and why, so the work can
be defended to a reviewer without taking anyone's word for it:

  * For every document series we swept, it RE-QUERIES the live docs.wto.org
    search and prints the site's own total next to our enumerated count — a
    reviewer can reproduce that number by searching the same symbol.
  * It tallies, per series: enumerated / fisheries-flagged / downloaded /
    restricted (enumerated but not publicly retrievable).
  * It writes a Markdown report + a flat CSV evidence table (one row per
    enumerated document) that is the full audit trail.

Run:
    python tools/coverage_report.py --out ./wto_fish_out_v6
    python tools/coverage_report.py --no-verify   # skip the live re-count
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

import httpx

FE_S = "https://docs.wto.org/dol2fe/Pages/FE_Search/FE_S_S006.aspx"
TOTAL_RE = re.compile(r'hdntotalresults"\s*value="(\d+)"')
DM = Path("docs_manifest")

# Series we swept: (label, live-search query, listing file, public-download?)
SERIES = [
    ("TN/RL  规则谈判组（含渔业谈判）", "(@Symbol= TN/RL/*)", DM / "tn_rl_listing.jsonl", True),
    ("RD/TN/RL  谈判室文件（非正式）", "(@Symbol= RD/TN/RL/*)", DM / "rd_tn_rl_listing.jsonl", False),
    ("JOB/RL  规则组室文件", "(@Symbol= JOB/RL/*)", DM / "job_rl_listing.jsonl", False),
    ("G/FS  渔业补贴委员会", "(@Symbol= G/FS/*)", DM / "gfs_listing.jsonl", True),
]


def live_total(query: str) -> int | None:
    url = f"{FE_S}?Query={quote(query)}&Language=ENGLISH&Context=FomerScriptedSearch&languageUIChanged=true"
    try:
        h = httpx.get(url, headers={"User-Agent": "wto-fish-corpus-bot/1.0 (research)"},
                      follow_redirects=True, timeout=40).text
        m = TOTAL_RE.search(h)
        return int(m.group(1)) if m else None
    except httpx.HTTPError:
        return None


def load(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()] if p.exists() else []


def site_counts(out: Path) -> dict:
    rows = [r for r in load(out / "manifest.jsonl") if not r.get("duplicate_of")]
    return {
        "md": sum(1 for r in rows if r.get("out_md_path")),
        "pdf": sum(1 for r in rows if r.get("content_type") == "pdf" and not r.get("error")),
        "blocked": sum(1 for r in rows if r.get("error") and "access-gated" in (r.get("error") or "")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Coverage & evidence report")
    ap.add_argument("--out", default="./wto_fish_out_v6")
    ap.add_argument("--report", default="./docs_manifest/coverage_report.md")
    ap.add_argument("--evidence", default="./docs_manifest/coverage_evidence.csv")
    ap.add_argument("--no-verify", action="store_true", help="skip live re-count")
    args = ap.parse_args()

    out = Path(args.out)
    site = site_counts(out)
    manual = load(DM / "manual_additions.jsonl")
    docs = load(DM / "docs_manifest.jsonl")  # the WT/MIN / WT/L / sample probes

    ev_rows: list[dict] = []          # flat evidence table
    series_rows: list[dict] = []      # per-series summary
    for label, query, listing, public in SERIES:
        recs = load(listing)
        fish = [r for r in recs if r.get("fisheries")]
        dl = sum(1 for r in fish if r.get("downloaded"))
        live = None if args.no_verify else live_total(query)
        series_rows.append({
            "label": label, "query": query, "live": live, "enum": len(recs),
            "fish": len(fish), "dl": dl, "public": public,
        })
        for r in recs:
            ev_rows.append({
                "series": label.split()[0], "symbol": r.get("symbol", ""),
                "title": (r.get("text", "") or "")[:160],
                "fisheries": r.get("fisheries", False),
                "downloaded": r.get("downloaded", False),
                "public_download": public,
                "english_url": r.get("english_url", ""),
            })

    # ---- evidence CSV (full audit trail) ----
    Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
    with open(args.evidence, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["series", "symbol", "title", "fisheries",
                                          "downloaded", "public_download", "english_url"])
        w.writeheader()
        w.writerows(ev_rows)

    # ---- Markdown report ----
    L = []
    L.append("# WTO 渔业补贴语料 — 覆盖与证据报告")
    L.append(f"\n生成日期：{date.today().isoformat()}　|　核验方式："
             + ("已对 docs.wto.org 实时重新计数" if not args.no_verify else "未联网核验"))
    L.append("\n## 1. 范围定义（请老师/领导先确认）")
    L.append("本语料 = ①渔业补贴**专题站点**（www.wto.org 渔业目录，有界爬取）"
             "＋②docs.wto.org 上与渔业补贴相关的**文档系列**（下表）。")
    L.append("\n## 2. 站点部分（有界爬取，manifest 为完整记录）")
    L.append(f"- HTML→Markdown：**{site['md']}** 篇　PDF（已下载待解析）：**{site['pdf']}** 个　"
             f"受限视频（不可下）：**{site['blocked']}** 个　手动补充：**{len(manual)}** 个")
    L.append("- 完整记录：`wto_fish_out_v6/manifest.jsonl`（每个URL含成功/失败/重复/受限状态）")

    L.append("\n## 3. 文档库部分（每个系列全量枚举，官网总数可独立核对）")
    L.append("\n| 文档系列 | 官网总数 | 我方枚举 | 其中渔业 | 已下载 | 可公开下载 | 独立核验：去官网搜 |")
    L.append("|---|---:|---:|---:|---:|:--:|---|")
    for s in series_rows:
        match = "✅一致" if (s["live"] is not None and s["live"] == s["enum"]) else \
                (f"官网{s['live']}" if s["live"] is not None else "—")
        pub = "是" if s["public"] else "否·受限"
        L.append(f"| {s['label']} | {s['live'] if s['live'] is not None else '—'} | {s['enum']} "
                 f"| {s['fish']} | {s['dl']} | {pub} | `{s['query']}` → {match} |")

    # ministerial / legal known decisions
    dl_docs = [d for d in docs if d.get("downloaded")]
    L.append("\n## 4. 部长决定 / 法律文件（已知具体文件号，非系列扫描）")
    for d in docs:
        st = "✅已下载" if d.get("downloaded") else "❌直取未命中（需手动核实）"
        L.append(f"- `{d['symbol']}`（{d.get('series','')}）— {st}")

    fish_total = sum(s["fish"] for s in series_rows)
    dl_total = sum(s["dl"] for s in series_rows)
    L.append("\n## 5. 汇总")
    L.append(f"- 文档库**渔业相关**文件共 **{fish_total}** 份（枚举确认存在）；其中**可公开下载并已下载 {dl_total}** 份。")
    L.append(f"- 差额主要是 **RD/TN/RL + JOB/RL 受限室文件**（共 "
             f"{sum(s['fish'] for s in series_rows if not s['public'])} 份）——"
             "官网只公开**目录与标题**，正文需 WTO 成员权限，非公开渠道无法获取。")
    L.append(f"- 加站点 {site['md']+site['pdf']+len(manual)} 份，全部逐条登记于 "
             "`语料库数据确认清单.xlsx` 与本报告的证据表。")

    L.append("\n## 6. 如何独立验证本报告（给评审者）")
    L.append("1. 打开 https://docs.wto.org → 高级检索，按上表“文档系列”的符号（如 `TN/RL/*`）搜索，"
             "核对**官网总数**与本表“我方枚举”一致 → 证明没有漏抓一批。")
    L.append("2. 逐条核对：`docs_manifest/coverage_evidence.csv` 是全量审计表，每个文档号都有"
             "标题/是否渔业/是否已下载/是否可公开下载/官方链接。")
    L.append("3. 复现：`python tools/docs_enumerate.py --query \"(@Symbol= TN/RL/*)\" ...` 重跑得到同一份清单。")

    L.append("\n## 7. 已知局限（如实披露）")
    L.append("- “是否渔业”目前按**标题关键词**判定（保守）：能干净排除 2002–2011 年的反倾销/SCM 旧文件，"
             "但少数**不含渔业字样的程序性文件**（如个别会议纪要）可能未被计入，建议对边界项人工抽检。")
    L.append("- 受限室文件（RD/TN/RL、JOB/RL）的正文无法公开获取，仅有目录级证据。")
    L.append("- 极广的跨议题系列（如 `JOB/GC` 596、`G/SCM` 9000+）非渔业专属，未逐份扫描；"
             "如需，应改用全文检索“fisheries subsidies”补网。")

    Path(args.report).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"report  : {args.report}")
    print(f"evidence: {args.evidence}  ({len(ev_rows)} 行)")
    for s in series_rows:
        flag = "OK" if (s["live"] == s["enum"]) else f"live={s['live']}"
        print(f"  {s['label'][:22]:24} enum={s['enum']:>4} fish={s['fish']:>4} dl={s['dl']:>4}  [{flag}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
