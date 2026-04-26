# taoguba-hot

> 淘股吧热门文章抓取工具 -  获取A股散户情绪热门讨论，用于市场情绪分析

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

## 📈 功能

### 🔥 热门文章抓取
抓取 **淘股吧点赞榜** (https://www.tgb.cn/dianzan) 热门文章，获取：

- 文章标题 + 作者 + 原始链接
- 全部文章正文汇总
- 按时间范围过滤（指定开始/结束日期）
- 适合用于获取A股散户情绪、热门话题追踪

### 📊 股票股吧评论抓取（新增）
抓取指定股票的淘股吧网友讨论帖，**用于分析个股散户情绪**：

- 输入股票代码（如 `sz300750`、`sh600519`）即可抓取该股票吧所有帖子
- 自动区分主帖和跟帖回复
- 包含：标题、作者、时间、点赞/评论/浏览数、正文摘要
- 无需 AJAX 请求，直接解析 HTML 中嵌入的 JSON 数据，稳定可靠

**示例：抓取宁德时代(sz300750)股吧评论：**
```bash
python scripts/tgb_stock_comments.py -s sz300750 -p 3 -d 0.5
```

## 🚀 快速开始

### 安装依赖

```bash
pip install requests beautifulsoup4 lxml
```

### 使用方法

```bash
cd scripts
python tgb_spider.py \
  --s-dt "03-20 00:00" \
  --e-dt "03-21 00:00" \
  --search-page 5
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--base-url` | 否 | `https://www.tgb.cn/dianzan` | 列表页基础URL |
| `--s-dt` | 是 | - | 开始时间，格式 `MM-DD HH:MM` |
| `--e-dt` | 是 | - | 结束时间，格式 `MM-DD HH:MM` |
| `--search-page` | 否 | `5` | 抓取多少分页 |
| `--out-dir` | 否 | `./data` | 输出根目录 |

### 输出文件

| 文件 | 说明 |
|------|------|
| `{out-dir}/corpus/MM-DD-tgb-corpus.txt` | 所有文章正文汇总 |
| `{out-dir}/corpus/MM-DD-tgb-list.txt` | 文章列表（标题 + 作者 + URL） |

## 📝 示例输出

获取昨日热门文章：

```bash
python scripts/tgb_spider.py \
  --s-dt "$(date -d yesterday +'%m-%d 00:00')" \
  --e-dt "$(date +'%m-%d 00:00')" \
  --search-page 5
```

## 🎨 特点

- 简单易用，单文件脚本
- 自带浏览器headers，绕过基础反爬
- 自动去重
- 错误容忍，单篇文章抓取失败不影响整体
- 适合配合OpenClaw/ Claude Code / Cline / Cursor 使用

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

## ⚠️ 免责声明

- 本项目仅供学习研究使用
- 请勿用于商业用途
- 请控制抓取频率，避免对目标网站造成压力
- 数据来源于淘股吧，版权归原网站所有
