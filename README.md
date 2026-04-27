# taoguba-skill

> 淘股吧(tgb.cn) 爬虫工具集 — A股散户情绪分析数据采集

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

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

## 🚀 快速开始

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
