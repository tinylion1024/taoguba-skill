---
name: taoguba-hot
description: 抓取淘股吧点赞榜热门文章，获取A股市场散户情绪和热门话题。支持按时间范围抓取，自动提取文章正文汇总。支持 SQLite 持久化和增量爬取。
metadata:
  openclaw:
    emoji: "🔥"
    requires:
      python_modules: ["requests", "beautifulsoup4", "lxml"]
---

# 淘股吧热门文章抓取 Skill

## 功能总览

本 skill 包含四个爬虫脚本：

| 脚本 | 功能 | 数据来源 |
|------|------|----------|
| `tgb_spider.py` | 热门文章（点赞榜）抓取 | https://www.tgb.cn/dianzan |
| `tgb_stock_comments.py` | 淘股吧股票股吧评论抓取 | https://www.tgb.cn/quotes/{code} |
| `tgb_blog_posts.py` | 大V博客帖子抓取 | https://www.tgb.cn/blog/{bid} |
| `tgb_eastmoney_comments.py` | 东方财富股吧股票评论抓取 | https://guba.eastmoney.com/list,{code},1,f.html |

---

## 1. 热门文章抓取 (`tgb_spider.py`)

抓取淘股吧点赞榜的热门文章，提取标题、作者和正文，用于了解A股散户情绪和热门话题。

### 使用示例

```bash
# 基础抓取（输出到 data/corpus/）
python scripts/tgb_spider.py \
  --s-dt "04-25 00:00" \
  --e-dt "04-27 00:00" \
  --search-page 1

# 持久化到 SQLite
python scripts/tgb_spider.py \
  --s-dt "04-25 00:00" \
  --e-dt "04-27 00:00" \
  --search-page 1 \
  --save-db

# 增量爬取（仅爬不在 DB 中的文章）
python scripts/tgb_spider.py \
  --s-dt "04-25 00:00" \
  --e-dt "04-27 00:00" \
  --search-page 1 \
  --save-db \
  --incremental
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--base-url` | `https://www.tgb.cn/dianzan` | 列表页基础URL（不含分页） |
| `--s-dt` | **必填** | 开始时间，格式 `MM-DD HH:MM` |
| `--e-dt` | **必填** | 结束时间，格式 `MM-DD HH:MM` |
| `--search-page` | 5 | 抓取多少分页 |
| `--out-dir` | `./data` | 输出根目录 |
| `--delay` | 0.5 | 请求间隔秒数（防封禁） |
| `--save-db` | False | 将结果写入 SQLite 数据库 |
| `--incremental` | False | 仅爬取不在 DB 中的文章（需配合 --save-db） |

### 输出说明

- **文本文件**：`{out-dir}/corpus/{MM-DD}-tgb-corpus.txt` — 文章正文汇总
- **列表文件**：`{out-dir}/corpus/{MM-DD}-tgb-list.txt` — 文章标题/作者/链接
- **SQLite**：`data/tgb.db` → `hot_articles` 表

### SQLite 表结构

```sql
CREATE TABLE hot_articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT UNIQUE,       -- 文章唯一ID（如 2rjdXpk0pCK）
    title       TEXT,              -- 标题
    author_name TEXT,              -- 作者名
    url         TEXT,              -- 文章URL
    publish_dt  TEXT,              -- 发布时间（格式 MM-DD HH:MM）
    s_dt        TEXT,              -- 爬取范围开始
    e_dt        TEXT,              -- 爬取范围结束
    body        TEXT,              -- 正文内容
    created_at  TEXT DEFAULT (datetime('now'))
);
```

增量爬取基于 `article_id` 去重，重复文章会跳过。

---

## 2. 股票股吧评论抓取 (`tgb_stock_comments.py`)

抓取指定股票的吧帖评论，用于分析个股的散户情绪和舆情。

**技术原理：** 淘股吧是 SPA 页面，帖子数据直接嵌入在 HTML 页面的 JavaScript 变量 `coolAttr` 中，通过正则解析即可，无需 AJAX 请求。

### 使用示例

```bash
# 基础抓取
python scripts/tgb_stock_comments.py \
  --stock-code sz300750 \
  --pages 3 \
  --delay 0.5

# 写入 SQLite + 增量爬取
python scripts/tgb_stock_comments.py \
  --stock-code sz300750 \
  --pages 3 \
  --save-db \
  --incremental
```

### 参数说明

| 参数 | 短名 | 默认值 | 说明 |
|------|------|--------|------|
| `--stock-code` | `-s` | **必填** | 股票代码，如 `sz300750`、`sh600519` |
| `--pages` | `-p` | 3 | 抓取页数（每页约20条） |
| `--delay` | `-d` | 0.5 | 请求间隔秒数，请勿设太小 |
| `--out-dir` | `-o` | `./data` | 输出目录 |
| `--save-db` | - | False | 将结果写入 SQLite 数据库 |
| `--incremental` | - | False | 仅爬取新帖子（基于 topic_id 去重） |

### 输出说明

- `{stock_code}-posts-list-{date}.txt` — 帖子列表（标题/作者/时间/URL/统计）
- `{stock_code}-posts-full-{date}.txt` — 帖子详情（含正文摘要）
- SQLite：`data/tgb.db` → `stock_comments` 表

### SQLite 表结构

```sql
CREATE TABLE stock_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code  TEXT NOT NULL,       -- 股票代码 (sz300750)
    topic_id    TEXT NOT NULL,        -- 帖子topic_id（去重键）
    author_name TEXT,
    author_bid  TEXT,
    content     TEXT,                 -- 评论内容
    post_url    TEXT,
    timestamp   TEXT,                -- 发布时间
    likes       INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(stock_code, topic_id)
);
```

---

## 3. 大V博客帖子抓取 (`tgb_blog_posts.py`)

抓取指定大V博客的所有帖子列表，支持 SQLite 持久化和增量爬取。

### 使用示例

```bash
# 抓取单博客（3页）
python scripts/tgb_blog_posts.py --blog-id 7105646 --pages 3

# 写入 SQLite + 增量爬取
python scripts/tgb_blog_posts.py --blog-id 7105646 --save-db --incremental

# 爬取所有已知大V（需有 references/tgb_blog_authors.json）
python scripts/tgb_blog_posts.py --all-authors --pages 3 --save-db
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--blog-url` | - | 博客 URL，如 `https://www.tgb.cn/blog/7105646` |
| `--blog-id` | - | 博客用户 ID，如 `7105646` |
| `--pages` | 3 | 每博客抓取页数 |
| `--delay` | 0.5 | 请求间隔秒数 |
| `--fetch-content` | False | 同时抓取文章正文（会显著增加时间） |
| `--save-db` | False | 将结果写入 SQLite 数据库 |
| `--incremental` | False | 仅爬取比上次更新的帖子（需 --save-db） |
| `--all-authors` | False | 爬取 `references/tgb_blog_authors.json` 中所有大V |
| `--out-dir` | `data/` | 输出目录 |
| `--log-file` | - | 日志文件路径 |

> 注意：`--incremental` 自动启用 `--save-db`。
> 必须提供 `--blog-url`、`--blog-id` 或 `--all-authors` 其一。

### 输出说明

- 控制台打印抓取摘要（前5条帖子）
- SQLite：`data/tgb.db` → `authors` + `posts` 表

### SQLite 表结构

```sql
-- 博主表
CREATE TABLE authors (
    bid         TEXT PRIMARY KEY,     -- 博主ID
    name        TEXT NOT NULL,        -- 博主名字
    blog_url    TEXT,                 -- 博客URL
    fans        TEXT,                 -- 粉丝数
    tier        TEXT,                 -- 评级 S/A/B/C/D/E/未评级
    source      TEXT,                 -- 来源
    post_count  INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- 帖子表
CREATE TABLE posts (
    post_id     TEXT PRIMARY KEY,     -- 帖子ID
    bid         TEXT NOT NULL,        -- 博主ID (FK)
    title       TEXT,
    url         TEXT,
    publish_date TEXT,                -- 发表时间 YYYY-MM-DD
    views       INTEGER DEFAULT 0,
    replies     INTEGER DEFAULT 0,
    tags        TEXT,                 -- JSON: ["原创","精华"]
    is_content_fetched INTEGER DEFAULT 0,
    body        TEXT,                 -- 正文内容
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (bid) REFERENCES authors(bid)
);
```

---

## 4. 东方财富股吧股票评论抓取 (`tgb_eastmoney_comments.py`)

抓取东方财富股吧指定股票的评论列表，用于分析个股的散户情绪和舆情。

**技术原理：** 东方财富股吧是传统多页 HTML，使用 BeautifulSoup4 解析 `<table class="default_list">` 结构。

### 使用示例

```bash
# 基础抓取
python scripts/tgb_eastmoney_comments.py \
  --stock-code 300750 \
  --pages 3 \
  --delay 0.5

# 写入 SQLite + 增量爬取
python scripts/tgb_eastmoney_comments.py \
  --stock-code 300750 \
  --pages 3 \
  --save-db \
  --incremental
```

### 参数说明

| 参数 | 短名 | 默认值 | 说明 |
|------|------|--------|------|
| `--stock-code` | `-s` | **必填** | 股票代码，如 `300750`（东方财富用纯数字） |
| `--pages` | `-p` | 3 | 抓取页数（每页约40条） |
| `--delay` | `-d` | 0.5 | 请求间隔秒数，请勿设太小 |
| `--out-dir` | `-o` | `./data` | 输出目录 |
| `--save-db` | - | False | 将结果写入 SQLite 数据库 |
| `--incremental` | - | False | 仅爬取比上次更新的帖子（基于 post_id 去重） |

### 输出说明

- `{stock_code}-eastmoney-list-{date}.txt` — 帖子列表（标题/作者/时间/URL/统计）
- `{stock_code}-eastmoney-full-{date}.txt` — 帖子详情
- SQLite：`data/tgb.db` → `eastmoney_comments` 表

### SQLite 表结构

```sql
CREATE TABLE eastmoney_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code  TEXT NOT NULL,
    post_id     TEXT UNIQUE,          -- 帖子唯一ID（去重键）
    title       TEXT,
    author      TEXT,
    publish_dt  TEXT,
    views       INTEGER DEFAULT 0,
    replies     INTEGER DEFAULT 0,
    url         TEXT,
    body        TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
```

---

## 通用说明

### 依赖安装

```bash
pip install requests beautifulsoup4 lxml
```

### SQLite 数据库

所有脚本共用同一个数据库：`data/tgb.db`（WAL 模式，支持并发读）。

### 增量爬取原理

| 脚本 | 增量去重字段 | 说明 |
|------|------------|------|
| `tgb_spider.py` | `article_id` | 基于文章唯一ID，跳过已爬文章 |
| `tgb_stock_comments.py` | `topic_id` | 基于帖子topic_id，避免重复抓取 |
| `tgb_blog_posts.py` | `publish_date` | 基于发布时间，爬取比上次更新的帖子 |
| `tgb_eastmoney_comments.py` | `post_id` | 基于帖子唯一ID，跳过已爬帖子 |

### 注意事项

- 本 skill 仅供学习研究使用
- 数据来源于淘股吧公开网页，请勿用于商业用途
- 请控制抓取频率（默认 0.5s delay），避免对目标网站造成压力
