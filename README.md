# WTO 渔业补贴专题爬虫（wto-fish-crawler）

有界爬取 WTO《渔业补贴协定》专题，产出**去重、仅英文、按官网结构分类**的 Markdown 语料，供 RAG 使用。

设计原则：**先划界，再爬取**。门户页向三个性质不同的方向发散，无脑跟链会爬穿整个 WTO 站点 + 外部站点，所以代码核心是边界规则（`config.py`），其余都是机制。

---

## 1. 三层范围（Tier）

| Tier | 含义 | 行为 |
|---|---|---|
| **T1_SITE** | `www.wto.org` 上命中路径白名单的专题页（`tratop_e/rulesneg_e/fish_e/`、`docs_e/legal_e/fish_e`、渔业出版物、相关新闻） | 抓取 + 跟链 |
| **T2_DOCS** | `docs.wto.org` 文档库中命中文档系列白名单的文件（`WT/MIN`、`WT/L`、`TN/RL`…） | 仅在 `--include-docs` 时抓取，**不跟链**（数据库不是网状站点） |
| **T3_EXTERNAL** | FAO / OECD / World Bank / UN 等外部站 | **只记录到 `external_links.jsonl`，不抓** |
| REJECT | 其他 wto 页面 / 非英文 | 丢弃 |

> ⚠️ **关于"全量爬取子链接"**：字面执行=无界。本工具用 `T1_PATH_PREFIXES` 把站内跟链锁死在渔业目录；`/english/news_e/` 这种大目录额外用 `NEWS_RELEVANCE`（文件名含 `fish`）二次过滤。要扩范围就改 `config.py`，不要改机制代码。

---

## 2. 关键规则（都在 `config.py`）

- **只保留英文**：用 WTO 文件名后缀约定，不跑语种分类器。`_e` 英文保留、`_f`/`_s` 丢弃；路径含 `/french/`、`/spanish/` 丢弃；无语言标记（多见于 `docs.wto.org` 的 PDF）放行，`lang` 记为 `und` 待下游内容级判定。零误判。
- **两级去重**：
  1. `url_norm`（去 fragment、去 tracking 参数、排序 query、小写 host）——挡多入口同页；
  2. `content_hash`（正文空白归一化后 SHA-256）——挡同一份 PDF/文档在不同路径或不同 `filename=` 参数下的重复。WTO 交叉引用极多，第 2 级是关键。重复项写入 `dedup_report.csv` 审计，不产出 Markdown。
- **分类**：`URL_CATEGORY_RULES` 前缀规则优先，`TITLE_CATEGORY_RULES` 标题兜底，默认 `uncategorized`。类目：`overview / introduction / legal_text / mandate_decision / ratification / committee / implementation / negotiation_submission / publication / news`。分类结果写进每个 Markdown 的 YAML front matter，也写进 manifest。

---

## 3. 安装

需要 Python ≥ 3.11。

```bash
uv venv && source .venv/bin/activate
uv pip install -e .            # httpx + selectolax + trafilatura
# 可选的 PDF 兜底后端（MinerU 不可用时用）：
uv pip install -e ".[pymupdf]"
# 开发：uv pip install -e ".[dev]"
```

**MinerU**：本工具默认调用你已安装的 `mineru` CLI 解析 PDF（不重复打包）。如果你的调用方式不同，改 `wto_fish/pdf_convert.py` 顶部的 `MINERU_CMD` 即可。它会在临时目录跑 `mineru -p in.pdf -o out -m auto`，然后回收产出的 `.md`。

---

## 4. 运行

```bash
# 先自测纯逻辑（不联网）
python run.py selftest

# 冒烟测试：只跑 Tier 1，最多产出 5 篇，确认链路通
python run.py crawl --out ./wto_fish_out --max-pages 5

# 正式：Tier 1 全量
python run.py crawl --out ./wto_fish_out --max-depth 4

# 加上 Tier 2 文档库（部长决定/议定书/谈判提案）
python run.py crawl --out ./wto_fish_out --include-docs --max-depth 5

# 中断后续跑（按已有 manifest 跳过已抓 URL）
python run.py crawl --out ./wto_fish_out --resume

# MinerU 不可用时临时用 pymupdf 文本兜底
python run.py crawl --out ./wto_fish_out --pdf-backend pymupdf
```

参数：`--concurrency`（默认 4）、`--delay`（每请求间隔秒，默认 1.0，礼貌爬取）、`--seed`（可重复，覆盖默认种子）。

> 改 `config.py` 里的 `USER_AGENT`，把联系邮箱换成你自己的——对公共 IGO 站点这是基本礼貌。

---

## 5. 产物结构

```
wto_fish_out/
├── raw/html/<raw_sha256>.html      # 原始 HTML
├── raw/pdf/<raw_sha256>.pdf        # 原始 PDF
├── markdown/<content_hash[:16]>.md # 转换后，带 YAML front matter
├── manifest.jsonl                  # 每个资源一行（含重复项，标 duplicate_of）
├── external_links.jsonl            # Tier 3 外链备查
├── dedup_report.csv                # 被去掉的内容级重复
└── crawl.log
```

Markdown front matter 示例：

```yaml
---
url: "https://www.wto.org/.../fish_e.htm"
url_norm: "..."
category: "overview"
lang: "en"
tier: "T1_SITE"
title: "Agreement on Fisheries Subsidies"
content_hash: "a1b1c7dd..."
source_url: "..."
fetched_at: "2026-...Z"
---
<正文 Markdown>
```

喂 RAG 时：`category` 直接做 metadata 过滤/路由；`content_hash` 做幂等入库主键；`url` 做引用回链。

---

## 6. 接你现有管线的点

- **MinerU**：PDF→MD 直接复用你的 doc-type 分块策略——legal_text / mandate_decision / publication(slides) 版式差异大，正好按 `category` 分流到不同 chunking。
- **幂等**：`content_hash[:16]` 既是文件名又是去重键，重跑不会重复入库。
- **embedding**：建议按 `category` 分集合或加 namespace；法律文本（`legal_text`）条款粒度细，单独的 chunk 策略效果会明显更好。

---

## 7. 已知边界 / 需你确认的点

1. **Committee on Fisheries Subsidies 的文档系列符号**：协定 2025-09-15 才生效，委员会文档可能用新系列号（疑似 `G/FS/`，未在站上确认）。`config.py` 里留了注释位，确认后取消注释即可纳入 Tier 2。
2. **docs.wto.org 的英文判定**：该库 PDF 常无语言后缀，本工具放行并记 `lang=und`。若要严格只留英文正文，在 `pdf_convert` 后加一道 `langdetect`/`fasttext` 内容级过滤。
3. **谈判提案（TN/RL 系列）量大**：开 `--include-docs` 前先想清楚要不要全量；这部分更适合像你做 IOTC manifest 那样先按文档号拉清单再批量下，而不是即时跟链。
4. **robots / 频率**：默认 4 并发 + 1s 间隔已较保守；正式大规模跑前建议先看 `https://www.wto.org/robots.txt` 并相应调 `--delay`。

---

## 8. Tier 2 — WTO Documents Online（docs.wto.org）

文档库（部长决定、议定书、TN/RL 谈判提案、成员通报）不在官网静态页上，而在一个
**ASP.NET WebForms 检索系统**里（`dol2fe/Pages/FE_Search/`），没有公开 JSON API，
全库 15 万+ 文档。所以分两步：

**Stage 1 — 通路探测（`tools/docs_probe.py`，已就绪）。**
已知文档号能否直接下，先验证再放量：
```bash
python tools/docs_probe.py                 # 探测 MIN(22)/33、L/1144
python tools/docs_probe.py --save           # 顺便存 PDF
python tools/docs_probe.py --symbol "TN/RL/W/100"   # 探测额外文档号
```
直取 URL 形如 `directdoc.aspx?filename=q:/WT/MIN22/33.pdf&Open=True`
（文档号去掉括号即文件名）。脚本会逐个汇报 OK/miss/FAIL。

**Stage 2 — 检索清单（待 Stage 1 通过后构建）。**
因为是 WebForms，枚举只能用浏览器自动化（Playwright）驱动检索页：按文档号系列
（`TN/RL/*`）或全文 "fisheries subsidies" 检索，翻页抓取每条结果的
符号 / 标题 / 日期 / directdoc 链接 → 落成 manifest（**只拉清单，不下正文**）。
拿到清单、知道各系列数量后，再决定下哪些 —— 与 IOTC manifest 流程一致。
