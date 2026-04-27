#!/usr/bin/env python3
"""
analyze_vip_posts.py
分析大V精选帖，提炼"A股持续复利方法论"

从 vip_selected_posts 表读取 body_word_count > 100 的帖子，
调用本地 LLM API（ Ollama 或 OpenAI-compatible ）分析并提炼方法论。

Usage:
    python scripts/analyze_vip_posts.py --min-words 200 --output data/analysis/methodology_summary.md
"""

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

import requests

from common import DB_PATH, DATA_DIR, logger, setup_logging

# ---------------------------------------------------------------------------
# LLM API 调用
# ---------------------------------------------------------------------------
LLM_ENDPOINTS = [
    {"url": "http://localhost:11434/api/generate", "model_key": "model", "prompt_key": "prompt", "legacy": True},
    {"url": "http://localhost:8000/v1/chat/completions", "model_key": "model", "prompt_key": "messages", "legacy": False},
]

SYSTEM_PROMPT = """你是一位精通A股交易、专注于复利增长的专业投资者。
你的任务是分析以下淘股吧大V的帖子内容，提炼出关于A股持续复利的方法论。

请从以下7个维度进行深度分析并提炼：
1. 选股逻辑：如何选择能带来复利的股票（价值投资、趋势投机、题材炒作等）
2. 买入时机：什么情况下买入（估值低位、突破确认、技术信号等）
3. 卖出时机/止损：何时止盈止损，如何保护本金
4. 仓位管理：如何分配仓位实现复利最大化
5. 风险控制：如何控制回撤，避免大幅亏损
6. 心态管理：如何保持稳定心态，避免情绪化交易
7. 复利关键：实现持续复利的核心要素是什么

请按以下格式输出（Markdown）：
- 每个维度给出 **大V观点摘要**（引用原文中的关键语句）
- 每个维度给出 **具体可操作的方法建议**（至少3条）
- 引用时请标注作者和帖子标题
"""


def try_llm_call(prompt: str, timeout: int = 120) -> str | None:
    """尝试调用本地 LLM API，成功返回内容，失败返回 None"""
    for ep in LLM_ENDPOINTS:
        try:
            if ep["legacy"]:
                # Ollama legacy API: POST /api/generate
                resp = requests.post(
                    ep["url"],
                    json={"model": "llama3", "prompt": prompt, "stream": False},
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    return resp.json().get("response", "")
            else:
                # OpenAI-compatible API: POST /v1/chat/completions
                resp = requests.post(
                    ep["url"],
                    json={
                        "model": "llama3",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "stream": False,
                    },
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.debug(f"LLM call failed ({ep['url']}): {e}")
            continue
    return None


def fetch_post_body(article_url: str) -> str:
    """抓取单篇文章的正文内容"""
    import html as html_module
    from bs4 import BeautifulSoup
    from common import fetch, get_headers

    try:
        html = fetch(article_url, timeout=15)
        soup = BeautifulSoup(html, "html.parser")

        body = ""
        for cls in ["stockDetailContent", "article-content", "content"]:
            elem = soup.find(class_=cls)
            if elem:
                body = elem.get_text(separator="\n", strip=True)
                break

        if not body:
            for tag in soup.find_all(["div", "article"]):
                text = tag.get_text(separator="\n", strip=True)
                if len(text) > 200:
                    body = text
                    break

        if not body:
            for tag_id in ["content", "body", "main"]:
                elem = soup.find(id=re.compile(tag_id, re.I))
                if elem:
                    body = elem.get_text(separator="\n", strip=True)
                    break

        body = html_module.unescape(body)
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
        return body.strip()

    except Exception as e:
        logger.warning(f"Failed to fetch body from {article_url}: {e}")
        return ""


def count_words(text: str) -> int:
    """统计中英文混合文本的字数"""
    if not text:
        return 0
    text = re.sub(r"\s+", " ", text).strip()
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"[a-zA-Z]+", text))
    return chinese + english_words


def build_analysis_prompt(posts: list[dict]) -> str:
    """将帖子列表构建为分析用 prompt（限制总长度）"""
    lines = []
    lines.append("以下是淘股吧大V的帖子正文，请分析并提炼复利方法论：\n")

    for i, post in enumerate(posts[:10]):  # 最多用10篇，避免token超限
        body = post.get("body", "")[:1500]  # 每篇最多1500字
        lines.append(f"【帖子{i+1}】作者：{post['author_name']}（{post['author_tier']}）")
        lines.append(f"标题：{post['title']}")
        lines.append(f"正文：{body}")
        lines.append("")

    lines.append("\n请根据以上内容，从选股逻辑、买入时机、卖出时机/止损、仓位管理、风险控制、心态管理、复利关键这7个维度进行提炼。")
    return "\n".join(lines)


def generate_methodology_md(posts: list[dict], llm_content: str | None = None) -> str:
    """生成 methodology_summary.md 内容"""

    # 按作者统计
    author_counts = {}
    tier_counts = {}
    for p in posts:
        author_counts[p["author_name"]] = author_counts.get(p["author_name"], 0) + 1
        tier = p["author_tier"] or "未评级"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    # Top作者
    top_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # 时间分布
    dates = [p["publish_date"] for p in posts if p.get("publish_date")]
    date_range = f"{min(dates)} ~ {max(dates)}" if dates else "未知"

    md_lines = []
    md_lines.append("# A股持续复利方法论\n")
    md_lines.append("> 本文档由 AI 自动分析淘股吧116位大V的精选帖（vip_selected_posts）提炼所得\n")
    md_lines.append(f"> 数据来源：淘股吧 tgb.cn\n")
    md_lines.append(f"> 分析帖子数：{len(posts)} 篇\n")
    md_lines.append(f"> 涉及作者：{len(author_counts)} 位\n")
    md_lines.append(f"> 时间范围：{date_range}\n")
    md_lines.append(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 统计概览
    md_lines.append("\n## 📊 数据概览\n")
    md_lines.append(f"| 指标 | 数值 |\n|------|------|")
    md_lines.append(f"| 精选帖总数 | {len(posts)} |\n| 涉及大V数 | {len(author_counts)} |\n| 时间范围 | {date_range} |\n")

    md_lines.append("\n### 大V级别分布\n")
    md_lines.append("| 级别 | 帖子数 |")
    md_lines.append("|------|--------|")
    for tier in ["S级", "A级", "B级", "C级", "D级", "E级", "未评级"]:
        cnt = tier_counts.get(tier, 0)
        if cnt > 0:
            md_lines.append(f"| {tier} | {cnt} |")

    md_lines.append("\n### Top 10 高产作者\n")
    md_lines.append("| 排名 | 作者 | 精选帖数 |")
    md_lines.append("|------|------|---------|")
    for i, (name, cnt) in enumerate(top_authors, 1):
        md_lines.append(f"| {i} | {name} | {cnt} |")

    # LLM 分析结果
    if llm_content:
        md_lines.append("\n## 🧠 AI 提炼：七维复利方法论\n")
        md_lines.append(llm_content)
    else:
        md_lines.append("""
## 🧠 AI 提炼：七维复利方法论

> 【提示】请配置本地 LLM API 后重新运行分析模块
>
> 当前未能连接到本地 LLM 服务（尝试了以下端点）：
> - http://localhost:11434/api/generate (Ollama)
> - http://localhost:8000/v1/chat/completions (OpenAI-compatible)
>
> 请确保本地已启动 LLM 服务（如 Ollama），或通过以下方式启动：
> ```bash
> ollama serve  # 启动 Ollama 服务
> ollama pull llama3  # 下载 llama3 模型
> ```
>
> 重新运行分析：
> ```bash
> python scripts/analyze_vip_posts.py --min-words 200 --output data/analysis/methodology_summary.md
> ```

""")

    # 各维度详细引用（直接从帖子内容）
    md_lines.append("\n## 📚 大V原文精选引用\n")

    # 按维度分类展示
    dimension_keywords = {
        "选股逻辑": ["选股", "股票", "龙头", "价值", "估值", "基本面", "行业", "板块"],
        "买入时机": ["买入", "建仓", "抄底", "突破", "买入点", "买点", "时机"],
        "卖出止损": ["卖出", "止损", "止盈", "止损点", "逃顶", "卖点", "出局"],
        "仓位管理": ["仓位", "满仓", "轻仓", "重仓", "分仓", "建仓", "加仓", "减仓"],
        "风险控制": ["风险", "回撤", "亏损", "本金", "保护", "风控", "止损"],
        "心态管理": ["心态", "情绪", "耐心", "贪婪", "恐惧", "稳定", "平和"],
        "复利关键": ["复利", "稳定", "持续", "增长", "积累", "长期", "稳健"],
    }

    for dim, keywords in dimension_keywords.items():
        md_lines.append(f"\n### {dim}\n")
        matched_posts = []
        for p in posts:
            body = p.get("body", "") or ""
            title = p.get("title", "") or ""
            combined = body + title
            if any(kw in combined for kw in keywords):
                matched_posts.append(p)
                if len(matched_posts) >= 3:
                    break

        if matched_posts:
            for p in matched_posts:
                body_preview = (p.get("body", "") or "")[:300]
                md_lines.append(f"> **《{p['title']}》— {p['author_name']}（{p['author_tier']}）**")
                md_lines.append(f"> {body_preview}...")
                md_lines.append("")
        else:
            md_lines.append("*（暂无相关帖子）*\n")

    md_lines.append("\n## 📋 使用说明\n")
    md_lines.append("""
本文件由 `scripts/analyze_vip_posts.py` 自动生成。
如需重新分析最新数据，请运行：

```bash
# 抓取大V精选帖（如尚未抓取）
python scripts/crawl_vip_selected_posts.py --save-db --pages 1

# 重新生成分析报告
python scripts/analyze_vip_posts.py --min-words 200 \\
    --output data/analysis/methodology_summary.md
```

如 LLM API 不可用，请先配置本地 Ollama：
```bash
curl -X POST http://localhost:11434/api/generate \\
  -d '{"model":"llama3","prompt":"hello","stream":false}'
```
""")

    return "\n".join(md_lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="分析大V精选帖，提炼A股复利方法论")
    parser.add_argument("--min-words", type=int, default=200, help="正文最小字数（默认200）")
    parser.add_argument("--max-posts", type=int, default=50, help="最多分析帖子数（默认50）")
    parser.add_argument("--output", "-o", default="data/analysis/methodology_summary.md", help="输出文件路径")
    parser.add_argument("--skip-fetch", action="store_true", help="跳过正文抓取，使用已有数据")
    parser.add_argument("--log-file", help="日志文件")
    return parser.parse_args()


def main():
    args = parse_args()

    # 初始化日志
    setup_logging(log_file=args.log_file)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 读取已有帖子（body_word_count > 0 表示已有正文）
    rows = conn.execute(
        """
        SELECT author_id, author_name, author_tier, article_url, title, body,
               publish_date, view_num, reply_num, is_elite, body_word_count
        FROM vip_selected_posts
        WHERE body_word_count > 0
        ORDER BY view_num DESC
        LIMIT ?
        """,
        (args.max_posts,),
    ).fetchall()

    posts = [dict(row) for row in rows]
    conn.close()

    logger.info(f"读取到 {len(posts)} 篇已有正文的精选帖（body_word_count > 0）")

    # 如果正文数量不足，提示用户先抓取
    if len(posts) < 5 and not args.skip_fetch:
        logger.warning(
            f"正文帖子数不足（{len(posts)} 篇），建议先运行抓取脚本：\n"
            f"  python scripts/crawl_vip_selected_posts.py --save-db --fetch-body"
        )

    # 构建 prompt 并调用 LLM
    llm_content = None
    if posts:
        logger.info("正在调用本地 LLM API...")
        prompt = build_analysis_prompt(posts)
        llm_content = try_llm_call(prompt, timeout=180)

    # 生成报告
    md_content = generate_methodology_md(posts, llm_content)

    # 写出文件
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md_content, encoding="utf-8")

    logger.info(f"方法论报告已生成: {output_path}")
    print(f"\n{'=' * 60}")
    print(f"分析完成！")
    print(f"  有效帖子: {len(posts)} 篇")
    print(f"  LLM API: {'成功' if llm_content else '不可用（生成占位符）'}")
    print(f"  输出文件: {output_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()