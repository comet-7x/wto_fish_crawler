# WTO 渔业补贴专题爬虫（wto-fish-crawler）

有界抓取 WTO《渔业补贴协定》专题，产出**去重、仅英文、按类别分类**的 Markdown 语料，供 RAG / 向量化使用。

设计原则：**先划界，再爬取**。门户页向三个性质不同的方向发散，无脑跟链会爬穿整个 WTO 站点 + 外部站点，所以代码核心是边界规则（`config.py`），其余都是机制。

---

## 整体架构

本项目分**两条互补的采集线路**：

| 线路 | 目标 | 入口 | 产出 |
|---|---|---|---|
| **A · 站点爬虫** | `www.wto.org` 渔业专题网页 | `run.py` | `wto_fish_out_v6/`、`渔业补贴站点库/` |
| **B · 文件库工具** | `docs.wto.org` 文件库 PDF（G/FS、TN、WT/MIN、WT/L 等系列） | `tools/docs_*.py` | `渔业补贴文件库/`、`docs_manifest/` |

两条线路的产物合并后即为完整的 WTO 渔业补贴语料库。

---

## 目录结构

```
wto_fish_crawler/
│
├── run.py                        ← 线路A 主爬虫入口
├── wto_fish/                     ← 主爬虫核心包
│   ├── config.py                 ← 所有规则（种子、白名单、分类）
│   ├── urlrules.py               ← 纯URL逻辑（标准化、分层、语言过滤）
│   ├── pipeline.py               ← 爬取流水线（广度优先、并发、去重）
│   ├── fetch.py                  ← 异步HTTP下载（限速、重试）
│   ├── extract.py                ← HTML→Markdown + 链接提取
│   ├── classify.py               ← URL/标题规则分类
│   ├── dedup.py                  ← 两级去重（URL级 + 内容级）
│   ├── models.py                 ← 数据结构（PageRecord、Tier）
│   └── pdf_convert.py            ← PDF→Markdown（MinerU / PyMuPDF）
│
├── tools/                        ← 线路B 及辅助工具（各自独立运行）
│   ├── docs_detail.py            ← 按文件编号系列爬取文件库，下载PDF
│   ├── docs_enumerate.py         ← 枚举文件库文件列表
│   ├── docs_fetch.py             ← 批量下载文件库PDF
│   ├── docs_harvest.py           ← Playwright浏览器枚举文件库检索结果
│   ├── docs_probe.py             ← 验证文件库直接下载路径是否通
│   ├── crawl_countries.py        ← 爬取接受成员国家主页
│   ├── render_dynamic.py         ← Playwright渲染动态页面（DataTables等）
│   ├── build_review.py           ← 生成交付给老师的审核文件夹 + Excel
│   ├── build_site_library.py     ← 整理站点库文件夹结构
│   ├── build_index.py            ← 建立文件索引（CSV / SQLite）
│   ├── delivery_manifest.py      ← 生成交付清单 Excel
│   ├── finalize_workbook.py      ← 最终 Excel 汇总
│   ├── coverage_report.py        ← 覆盖率报告
│   ├── tag_subjects.py           ← 给文件打主题标签
│   ├── verify_links.py           ← 验证链接有效性
│   └── download_corpus.py        ← 批量下载语料
│
├── wto_fish_out_v6/              ← 线路A 当前爬取输出
│   ├── manifest.jsonl            ← 每个URL一行的完整元数据记录
│   ├── markdown/                 ← HTML转换后的Markdown（带YAML front matter）
│   ├── raw/html/                 ← 原始HTML字节（按raw_sha256命名）
│   ├── raw/pdf/                  ← 原始PDF字节
│   ├── external_links.jsonl      ← Tier-3外部链接日志（FAO、OECD等）
│   ├── dedup_report.csv          ← 内容级重复记录
│   └── crawl.log
│
├── docs_manifest/                ← 线路B 文件库元数据清单
│   ├── detail_GFS.jsonl          ← G/FS 渔业补贴委员会文件详情
│   ├── detail_TN.jsonl           ← TN/RL 谈判文件详情
│   ├── detail_WTMIN.jsonl        ← WT/MIN 部长会文件详情
│   ├── detail_WTL.jsonl          ← WT/L 法律文书详情
│   ├── detail_WTLET.jsonl        ← WT/LET 成员接受书详情
│   ├── detail_GSCM.jsonl         ← G/SCM 补贴通报详情
│   ├── detail_WTGC.jsonl         ← WT/GC 总理事会文件详情
│   ├── detail_JOBRL.jsonl        ← JOB/RL 室文件详情
│   └── delivery_main.csv         ← 交付主清单
│
├── 渔业补贴文件库/               ← 线路B 下载的PDF，按系列/年份分类
│   ├── 01_G-FS_渔业补贴委员会/
│   ├── 02_TN_谈判/
│   ├── 03_WT-MIN_部长会/
│   ├── 04_WT-L_法律文本/
│   ├── 05_WT-LET_接受书/
│   ├── 06_G-SCM_补贴通报/
│   ├── 07_WT-GC_总理事会/
│   └── 09_JOB-RL_室文件/
│
├── 渔业补贴站点库/               ← 线路A 整理后的交付文件夹
│   ├── 01_网页_HTML转Markdown/   ← 按类别存放的Markdown文件
│   ├── 02_文件_PDF/              ← 爬取到的PDF
│   └── 03_音视频_受限仅链接/     ← 访问受限的视频（仅记录链接）
│
├── 接受成员国家页/               ← 各接受成员国WTO主页（crawl_countries.py）
│   ├── _接受成员国家页索引.csv
│   └── <国家名>.md（90+个）
│
├── tests/
│   └── test_urlrules.py          ← URL逻辑单元测试
│
├── 语料库数据确认清单.xlsx       ← 交给老师确认的总清单
└── pyproject.toml
```

---

## 一、线路A：站点爬虫（`run.py`）

### 三层范围（Tier）

| Tier | 含义 | 行为 |
|---|---|---|
| **T1_SITE** | `www.wto.org` 命中路径白名单的专题页 | 抓取 + 递归跟链 |
| **T2_DOCS** | `docs.wto.org` 命中文件系列白名单的文件 | `--include-docs` 时抓取，不跟链 |
| **T3_EXTERNAL** | FAO / OECD / World Bank 等外部站 | 仅记录到 `external_links.jsonl` |
| REJECT | 其他wto页面 / 非英文 | 丢弃 |

### 路径白名单（`config.py`）

```python
T1_PATH_PREFIXES = (
    "/english/tratop_e/rulesneg_e/fish_e/",   # 渔业专题核心页（递归跟链）
    "/english/docs_e/legal_e/fish_e",          # 法律文本
    "/english/res_e/publications_e/fish",      # 渔业出版物
    "/english/res_e/booksp_e/",                # 书籍/出版物PDF
    "/english/news_e/",                        # 新闻（额外要求路径含"fish"）
    "/english/thewto_e/minist_e/",             # 部长会简报（额外要求含"fish"）
)
```

**不在这6个前缀里的URL，即使从渔业页面链出，也不会被爬取。** 要扩范围改 `config.py`，不要改机制代码。

### 关键规则

- **仅保留英文**：按WTO文件名后缀约定（`_e` 保留、`_f`/`_s` 丢弃；路径含 `/french/`、`/spanish/` 丢弃）
- **两级去重**：
  1. `url_norm`（去fragment、去tracking参数、排序query、小写host）——挡多入口同页
  2. `content_hash`（正文空白归一化后SHA-256）——挡同一份PDF在不同路径重复出现
- **分类**：URL规则优先，标题规则兜底，结果写入YAML front matter和manifest

### 文档类别

| 类别代码 | 中文含义 |
|---|---|
| `overview` | 概览 |
| `introduction` | 导论 |
| `legal_text` | 法律文本 |
| `ratification` | 接受与批准 |
| `implementation` | 履约 |
| `fish_fund` | 渔业基金 |
| `publication` | 出版物 |
| `news` | 新闻 |
| `ministerial` | 部长会简报 |
| `case_story` | 案例故事 |
| `international_instrument` | 国际文书 |
| `negotiation_submission` | 谈判 |
| `multimedia` | 音视频 |
| `committee` | 委员会 |
| `mandate_decision` | 部长决定与议定书 |

### 安装

需要 Python ≥ 3.11。

```bash
uv venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e .                    # httpx + selectolax + trafilatura
uv pip install -e ".[pymupdf]"         # 可选：PDF文本兜底后端
uv pip install -e ".[dev]"             # 开发依赖
```

**MinerU**：默认调用已安装的 `mineru` CLI 解析PDF。调用方式不同时修改 `wto_fish/pdf_convert.py` 顶部的 `MINERU_CMD`。

### 运行

```bash
# 自测纯逻辑（不联网）
python run.py selftest

# 冒烟测试：最多产出5篇
python run.py crawl --out ./wto_fish_out --max-pages 5

# 正式：Tier 1 全量（默认深度4）
python run.py crawl --out ./wto_fish_out_v6 --max-depth 4

# 加上 Tier 2 文件库
python run.py crawl --out ./wto_fish_out_v6 --include-docs --max-depth 5

# 中断后续跑（按已有manifest跳过已抓URL）
python run.py crawl --out ./wto_fish_out_v6 --resume

# PDF文本兜底（MinerU不可用时）
python run.py crawl --out ./wto_fish_out_v6 --pdf-backend pymupdf
```

参数：`--concurrency`（默认4）、`--delay`（每请求间隔秒，默认1.0）、`--seed`（可重复，覆盖默认种子）

### 产物结构

```
wto_fish_out_v6/
├── raw/html/<raw_sha256>.html      # 原始HTML
├── raw/pdf/<raw_sha256>.pdf        # 原始PDF
├── markdown/<hash16>.md            # 转换后Markdown，带YAML front matter
├── manifest.jsonl                  # 每个资源一行（含重复项，标duplicate_of）
├── external_links.jsonl            # Tier-3外链备查
├── dedup_report.csv                # 被去掉的内容级重复
└── crawl.log
```

Markdown front matter 示例：

```yaml
---
url: "https://www.wto.org/.../fish_e.htm"
category: "overview"
lang: "en"
tier: "T1_SITE"
title: "Agreement on Fisheries Subsidies"
content_hash: "a1b1c7dd..."
fetched_at: "2026-...Z"
---
<正文 Markdown>
```

---

## 二、线路B：文件库工具（`tools/docs_*.py`）

`docs.wto.org` 是 ASP.NET WebForms 检索系统（`dol2fe/Pages/FE_Search/`），无公开 JSON API，全库15万+文件。分阶段处理：

### Stage 1 — 通路探测

```bash
python tools/docs_probe.py                          # 探测 MIN(22)/33、L/1144
python tools/docs_probe.py --save                   # 顺便存PDF
python tools/docs_probe.py --symbol "TN/RL/W/100"  # 探测额外文件号
```

直取URL形如 `directdoc.aspx?filename=q:/WT/MIN22/33.pdf&Open=True`（文件号去括号即文件名）。

### Stage 2 — 枚举文件清单

```bash
# 用Playwright浏览器驱动检索页，翻页抓取清单（只列，不下载）
python tools/docs_harvest.py --fulltext "fisheries subsidies" --out ./docs_manifest
python tools/docs_harvest.py --symbol "TN/RL/" --out ./docs_manifest

# 按文件号系列精确枚举
python tools/docs_enumerate.py
```

### Stage 3 — 下载文件详情与PDF

```bash
# 按系列拉取文件元数据和PDF
python tools/docs_detail.py

# 批量下载PDF（依据清单）
python tools/docs_fetch.py
```

产物按文件系列 + 年份分类存入 `渔业补贴文件库/`。

---

## 三、辅助工具

### 接受成员国家页

```bash
python tools/crawl_countries.py
```

爬取所有已接受《渔业补贴协定》成员国的WTO国家主页，存为Markdown，输出 `接受成员国家页/`（90+个国家）。

### 交付物生成

```bash
# 生成给老师审核的文件夹 + Excel（三个WTO Sheet）
python tools/build_review.py --out ./wto_fish_out_v6 --xlsx ./语料库数据确认清单.xlsx

# 整理站点库文件夹（按类别归档）
python tools/build_site_library.py --out ./wto_fish_out_v6

# 生成交付清单Excel
python tools/delivery_manifest.py

# 最终Excel汇总
python tools/finalize_workbook.py

# 建立全局文件索引（CSV + SQLite）
python tools/build_index.py
```

### 其他工具

```bash
python tools/render_dynamic.py    # Playwright渲染动态页（如fish_fund_e DataTables）
python tools/tag_subjects.py      # 给文件打主题标签
python tools/coverage_report.py   # 覆盖率报告
python tools/verify_links.py      # 验证链接有效性
```

---

## 四、接RAG管线的建议

- **`category`** 直接做 metadata 过滤/路由；法律文本（`legal_text`）条款粒度细，建议单独chunking策略
- **`content_hash[:16]`** 既是文件名又是去重键，重跑不会重复入库
- **`url`** 做引用回链
- 文件库PDF（`渔业补贴文件库/`）建议先按系列分集合，谈判文件（TN/RL）量大，可按年份分批入库

---

## 五、已知边界

1. **G/FS 委员会文件系列**：协定2025-09-15才生效，委员会文件系列（`G/FS/`）已确认并纳入线路B。
2. **docs.wto.org 英文判定**：该库PDF常无语言后缀，`lang` 记为 `und`。如需严格只留英文正文，在PDF解析后加 `langdetect`/`fasttext` 内容级过滤。
3. **TN/RL 谈判提案量大**：20年积累数百份，建议先用清单确认范围再批量下载，而非全量。
4. **访问受限的音视频**：WTO主席更新视频（`.mp4`）直接GET会返回HTML登录页，爬虫自动识别并记录为"受限"，存入 `03_音视频_受限仅链接/`，需浏览器或授权流获取。
5. **礼貌爬取**：默认4并发 + 1s间隔；正式大规模运行前建议检查 `https://www.wto.org/robots.txt`，并在 `config.py` 中把 `USER_AGENT` 的联系邮箱换成你自己的。
