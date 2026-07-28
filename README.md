# taoguba-skill

> 淘股吧(tgb.cn) 爬虫工具集 — A股散户情绪分析数据采集

[![Rust](https://img.shields.io/badge/Rust-1.85%2B-orange.svg)](https://www.rust-lang.org/)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

## Rust CLI

独立 Rust 工程位于 [`tgb-cli/`](tgb-cli/README.md)。`tgb` 是文章采集的主入口，覆盖热门榜、单篇文章、大V博客、大V精选、运行审计和结构化导出。原有 Python 脚本继续保留，用于股票评论和兼容旧流程。

### 安装

需要 Rust 1.85 或更高版本：

```bash
cargo install --path tgb-cli
tgb --help
```

不安装也可以直接使用：

```bash
cargo run --manifest-path tgb-cli/Cargo.toml -- --help
```

### 常用命令

```bash
# 抓取指定时间段的热门文章及正文
tgb hot \
  --from "2026-07-25 00:00" \
  --to "2026-07-27 23:59" \
  --pages 5 \
  --fetch-body

# 抓取单篇文章；参数可以是文章 ID 或完整 URL
tgb article 2rjdXpk0pCK

# 抓取指定大V的博客文章
tgb author 134434 --pages 3 --fetch-body --resume

# 批量抓取配置文件中带“精华/置顶”标记的文章
tgb vip --pages 2 --fetch-body --resume

# 如果页面没有精选标记，可显式允许每位作者取前 3 篇作为候选
tgb vip --fallback-top 3 --fetch-body

# 查看运行记录和失败明细
tgb run list
tgb run show 1

# 导出某次运行中正文解析成功的文章
tgb export --run 1 --only-success --format jsonl --output data/run-1.jsonl
```

全局参数必须放在子命令之前，例如：

```bash
tgb \
  --database data/research.db \
  --delay-ms 1500 \
  --max-attempts 4 \
  hot --from "2026-07-25 00:00" --to "2026-07-27 23:59"
```

### 数据与可靠性

- 默认数据库为 `data/tgb.db`，Rust 表统一使用 `tgb_` 前缀，不覆盖旧 Python 表。
- 每次采集都会创建一条 `tgb_crawl_runs` 记录，保存请求页数、发现数、正文成功数和错误数。
- 正文只接受已知内容容器，不使用“最大 div”之类容易混入导航、评论和推荐区的兜底规则。
- 时间统一保存为带时区的 RFC 3339；`MM-DD HH:MM` 会根据查询区间解析年份，支持跨年区间。
- `--raw-dir data/raw` 可保存原始 HTML，便于页面结构变化后离线复查。
- HTTP 请求有全局限速、超时和瞬时错误重试；请保持克制的抓取频率。
- 导出支持 `jsonl`、`csv`、`markdown` 和 `text`。JSONL 每行是一篇完整文章，适合后续情绪分析和 LLM 处理。

主要数据表：

| 表 | 用途 |
|---|---|
| `tgb_articles` | 去重后的统一文章及正文 |
| `tgb_article_sources` | 文章与采集运行、来源、排名的关系 |
| `tgb_crawl_runs` | 每次命令的参数、状态和统计 |
| `tgb_crawl_errors` | 分阶段错误和 HTTP 状态 |

## Python 兼容脚本

## 📈 功能一览

| 脚本 | 功能 | 用途 |
|------|------|------|
| `tgb_spider.py` | 点赞榜热门文章抓取 | 市场情绪、热门话题追踪 |
| `tgb_blog_posts.py` | 大V博客帖子批量爬虫 | 获取特定博主全部文章 |
| `tgb_stock_comments.py` | 股票股吧评论抓取 | 个股散户情绪分析 |
| `crawl_vip_selected_posts.py` | 大V精选/精华帖爬虫 | 爬取116位大V的置顶/精华帖 |
| `analyze_vip_posts.py` | LLM方法论提炼 | 从精选帖提炼"A股持续复利方法论" |

---

### 🔥 点赞榜热门文章

抓取 **淘股吧点赞榜** (https://www.tgb.cn/dianzan) 热门文章：

- 文章标题 + 作者 + 原始链接
- 全部文章正文汇总
- 按时间范围过滤（指定开始/结束日期）

```bash
cd scripts
python tgb_spider.py \
  --s-dt "03-20 00:00" \
  --e-dt "03-21 00:00" \
  --search-page 5
```

### 📝 大V博客帖子

按博主ID批量抓取博客文章：

```bash
python scripts/tgb_blog_posts.py \
  --author-ids 123456 234567 \
  --max-pages 5 \
  --save-db
```

### 📊 股票股吧评论

抓取指定股票的淘股吧网友讨论帖：

```bash
# 抓取宁德时代(sz300750)股吧评论
python scripts/tgb_stock_comments.py -s sz300750 -p 3 -d 0.5
```

### 🌟 大V精选帖（精华/置顶）

爬取 **116位大V** 的精选/精华帖，支持断点续爬：

```bash
# 首次运行
python scripts/crawl_vip_selected_posts.py --save-db --pages 2

# 断点续爬
python scripts/crawl_vip_selected_posts.py --save-db --resume

# 限制作者数量测试
python scripts/crawl_vip_selected_posts.py --save-db --max-authors 10 --pages 1
```

### 🧠 方法论提炼（LLM分析）

从精选帖中提炼"A股持续复利方法论"（需要本地 LLM，如 Ollama）：

```bash
python scripts/analyze_vip_posts.py \
  --min-words 200 \
  --output data/analysis/methodology_summary.md
```

---

## 🚀 Python 快速开始

### 安装依赖

```bash
pip install requests beautifulsoup4 lxml
```

### 参数说明

**tgb_spider.py**

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--s-dt` | 是 | - | 开始时间，格式 `MM-DD HH:MM` |
| `--e-dt` | 是 | - | 结束时间，格式 `MM-DD HH:MM` |
| `--search-page` | 否 | `5` | 抓取分页数 |
| `--out-dir` | 否 | `./data` | 输出根目录 |

**tgb_stock_comments.py**

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `-s` | 是 | - | 股票代码，如 `sz300750`、`sh600519` |
| `-p` | 否 | `3` | 抓取页数 |
| `-d` | 否 | `1.0` | 请求间隔（秒） |

**crawl_vip_selected_posts.py**

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--save-db` | 否 | False | 保存到SQLite |
| `--pages` | 否 | `1` | 每位作者爬取页数 |
| `--resume` | 否 | False | 断点续爬 |
| `--max-authors` | 否 | 无限制 | 限制作者数量 |

### 输出文件

| 文件 | 说明 |
|------|------|
| `{out-dir}/corpus/MM-DD-tgb-corpus.txt` | 文章正文汇总 |
| `{out-dir}/corpus/MM-DD-tgb-list.txt` | 文章列表（标题+作者+URL） |
| `{out-dir}/vip_selected_posts.db` | SQLite数据库（大V精选帖） |

---

## 📚 大V列表

项目维护 **116位淘股吧大V** 博主信息，见 `references/tgb_blog_authors.json`：

- 字段：`uid`、`uname`、`blog_url`、`fans_count`、`level`（S/A/B/C/D/E）
- 来源：首页本周上升达人、达人排行榜、论坛热门帖、实盘比赛选手

---

## 🎨 特点

- 简单易用，单文件脚本为主
- 自带浏览器 headers，绕过基础反爬
- 自动去重，错误容忍
- 支持 SQLite 持久化存储
- 支持断点续爬
- 适合配合 OpenClaw / Claude Code / Cline / Cursor 使用

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

## ⚠️ 免责声明

- 本项目仅供学习研究使用
- 请勿用于商业用途
- 请控制抓取频率，避免对目标网站造成压力
- 数据来源于淘股吧，版权归原网站所有
