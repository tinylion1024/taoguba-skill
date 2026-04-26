---
name: taoguba-hot
description: 抓取淘股吧点赞榜热门文章，获取A股市场散户情绪和热门话题。支持按时间范围抓取，自动提取文章正文汇总。
metadata:
  openclaw:
    emoji: "🔥"
    requires:
      python_modules: ["requests", "beautifulsoup4", "lxml"]
---

# 淘股吧热门文章抓取 Skill

## 功能

### 1. 热门文章抓取
抓取淘股吧点赞榜（`https://www.tgb.cn/dianzan`）的热门文章，提取文章标题、作者和正文内容，用于：

- 了解当前A股散户情绪
- 捕捉市场热门讨论话题
- 发现市场关注度高的个股
- 获取短线热点方向

## 使用方式

### 抓取今日/昨日热门文章

```bash
cd ~/.agents/skills/taoguba-hot
python3 scripts/tgb_spider.py \
  --s-dt "03-20 00:00" \
  --e-dt "03-21 00:00" \
  --search-page 5
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--base-url` | `https://www.tgb.cn/dianzan` | 列表页基础URL |
| `--s-dt` | 必填 | 开始时间，格式 `MM-DD HH:MM` |
| `--e-dt` | 必填 | 结束时间，格式 `MM-DD HH:MM` |
| `--search-page` | 5 | 抓取多少分页 |
| `--out-dir` | `./data` | 输出根目录（会自动创建 corpus 子目录） |

### 输出文件

- `{out-dir}/corpus/{MM-DD}-tgb-corpus.txt` - 抓取到的文章正文汇总
- `{out-dir}/corpus/{MM-DD}-tgb-list.txt` - 文章标题、作者和链接列表

### 2. 股票股吧评论抓取
抓取指定股票（如 `sz300750`、`sh600519`）的吧帖评论，用于分析该股票的 **散户情绪和舆情**。

**技术原理：** 淘股吧是 SPA 页面，帖子数据直接嵌入在 HTML 页面的 JavaScript 变量 `coolAttr` 中，无需 AJAX 请求，直接正则解析即可。

**使用示例：**
```bash
cd ~/.agents/skills/taoguba-hot
python3 scripts/tgb_stock_comments.py \
  --stock-code sz300750 \
  --pages 3 \
  --delay 0.5
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--stock-code` / `-s` | 必填 | 股票代码，如 `sz300750`、`sh600519` |
| `--pages` / `-p` | 3 | 抓取页数（每页约20条） |
| `--delay` / `-d` | 0.5 | 请求间隔（秒），请勿设太小 |
| `--out-dir` / `-o` | `./data` | 输出目录 |

**输出文件：**
- `{stock_code}-posts-list-{date}.txt` - 帖子列表（标题/作者/时间/URL/统计数据）
- `{stock_code}-posts-full-{date}.txt` - 帖子详情（含正文摘要）

**示例：**
```bash
# 抓取贵州茅台股吧评论（3页）
python3 scripts/tgb_stock_comments.py -s sh600519 -p 3 -d 0.5

# 抓取比亚迪股吧评论（1页）
python3 scripts/tgb_stock_comments.py -s sz002594 -p 1
```

## 依赖安装

```bash
pip install requests beautifulsoup4 lxml
```

## 示例

获取昨日热门文章（5页）：

```bash
python3 scripts/tgb_spider.py \
  --s-dt "$(date -d yesterday +'%m-%d 00:00')" \
  --e-dt "$(date +'%m-%d 00:00')" \
  --search-page 5
```

## 说明

- 该skill仅供学习研究使用
- 数据来源于淘股吧公开网页
- 请勿用于商业用途
- 请控制抓取频率，避免对目标网站造成压力
