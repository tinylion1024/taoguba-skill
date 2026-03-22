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
