#!/usr/bin/env python3
"""
tgb_eastmoney_comments.py
抓取东方财富股吧指定股票的评论列表
用于分析个股的散户情绪和舆情

页面示例：https://guba.eastmoney.com/list,300750,1,f.html（宁德时代）

技术方案：东方财富股吧是传统多页HTML，使用 BeautifulSoup4 解析
<table class="default_list"> 结构，提取帖子数据。

支持 SQLite 持久化（--save-db）和增量爬取（--incremental）。
"""

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from common import (
    DB_PATH,
    fetch,
    get_db,
    get_headers,
    init_db,
    logger,
    setup_logging,
    update_crawl_log,
)


# ------------------------------------------------------------------
# 核心：解析东方财富股吧列表页 HTML
# ------------------------------------------------------------------
def parse_list_page(html_content: str) -> list[dict]:
    """
    解析东方财富股吧列表页的 HTML 内容。
    HTML 结构：
        <table class="default_list">
          <thead class="listhead">...</thead>
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">160</div></td>
              <td><div class="reply">0</div></td>
              <td>
                <div class="title">
                  <a data-postid="1699428687" href="/news,300750,1699428687.html">标题</a>
                </div>
              </td>
              <td><div class="author"><a href="/list,300750.html">作者名</a></div></td>
              <td><div class="update">04-27 12:23</div></td>
            </tr>
          </tbody>
        </table>
    返回字段：views, replies, title, author, publish_dt, post_id, url
    """
    soup = BeautifulSoup(html_content, "lxml")
    items = []

    # 找到 tbody.listbody
    tbody = soup.find("tbody", class_="listbody")
    if not tbody:
        logger.warning("未找到 tbody.listbody，页面结构可能已变更")
        return []

    for row in tbody.find_all("tr", class_="listitem"):
        # 阅读数
        read_div = row.find("div", class_="read")
        views = int(read_div.get_text(strip=True)) if read_div else 0

        # 评论数
        reply_div = row.find("div", class_="reply")
        replies = int(reply_div.get_text(strip=True)) if reply_div else 0

        # 标题和链接（title div 内的 a 标签）
        title_div = row.find("div", class_="title")
        if not title_div:
            continue
        link_tag = title_div.find("a")
        if not link_tag:
            continue

        # post_id 来自 data-postid 属性
        post_id = link_tag.get("data-postid", "")

        # title 来自 a 标签的 title 属性（tooltip）
        title = link_tag.get("title", "") or link_tag.get_text(strip=True)

        # href 部分构建完整 URL
        href = link_tag.get("href", "")
        if href.startswith("/"):
            url = f"https://guba.eastmoney.com{href}"
        else:
            url = href

        # 作者
        author_div = row.find("div", class_="author")
        if author_div:
            author_link = author_div.find("a")
            author = author_link.get_text(strip=True) if author_link else author_div.get_text(strip=True)
        else:
            author = ""

        # 发布时间（格式 MM-DD HH:MM）
        update_div = row.find("div", class_="update")
        publish_dt = update_div.get_text(strip=True) if update_div else ""

        if post_id:
            items.append(
                {
                    "post_id": post_id,
                    "title": title,
                    "author": author,
                    "publish_dt": publish_dt,
                    "views": views,
                    "replies": replies,
                    "url": url,
                }
            )

    return items


# ------------------------------------------------------------------
# 分页 URL 构建
# ------------------------------------------------------------------
def build_list_url(stock_code: str, page: int) -> str:
    """构建东方财富股吧列表页 URL"""
    return f"https://guba.eastmoney.com/list,{stock_code},{page},f.html"


# ------------------------------------------------------------------
# 批量获取股票多页数据
# ------------------------------------------------------------------
def fetch_stock_page(stock_code: str, page: int = 1, delay: float = 0.5) -> list[dict]:
    """
    抓取指定股票的一页数据。
    stock_code: 如 300750（东方财富用纯数字代码，如 300750）
    page: 页码
    """
    time.sleep(delay)
    url = build_list_url(stock_code, page)

    try:
        headers = get_headers({"Referer": "https://guba.eastmoney.com/"})
        html_content = fetch(url, headers=headers, timeout=15)
    except Exception as e:
        logger.error(f"Request failed [{url}]: {e}")
        return []

    items = parse_list_page(html_content)
    logger.info(f"Page {page} [{stock_code}] → {len(items)} posts")
    return items


def crawl_stock_comments(stock_code: str, pages: int, delay: float, incremental: bool = False) -> list[dict]:
    """抓取指定股票的多页评论数据"""
    all_posts = []

    for page in range(1, pages + 1):
        items = fetch_stock_page(stock_code, page, delay)

        # 增量模式：基于 post_id 去重（post_id 在整个表中全局唯一）
        if incremental and items:
            conn = get_db()
            existing_ids = set()
            try:
                # post_id 是全局唯一的，无需按 stock_code 过滤
                rows = conn.execute("SELECT post_id FROM eastmoney_comments").fetchall()
                existing_ids = {row["post_id"] for row in rows}
            finally:
                conn.close()

            before = len(items)
            items = [item for item in items if item["post_id"] not in existing_ids]
            if items:
                logger.info(f"  增量: {before}条中{before - len(items)}条已存在，保留{len(items)}条新帖")

        all_posts.extend(items)

    return all_posts


# ------------------------------------------------------------------
# 格式化输出
# ------------------------------------------------------------------
def format_post(post: dict, include_body: bool = False) -> str:
    """将单条帖子格式化为可读字符串"""
    lines = [
        f"[标题] {post['title']}",
        f"[作者] {post['author']}",
        f"[时间] {post['publish_dt']}",
        f"[URL]  {post['url']}",
        f"[阅读 {post['views']}  评论 {post['replies']}]",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------
# 保存结果到文件
# ------------------------------------------------------------------
def save_results(
    posts: list[dict],
    stock_code: str,
    out_dir: str,
    save_db: bool = False,
    incremental: bool = False,
):
    """将抓取结果保存到文件，可选 SQLite"""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    new_posts = 0
    if save_db:
        init_db()
        conn = get_db()
        try:
            for post in posts:
                conn.execute(
                    """
                    INSERT INTO eastmoney_comments
                        (stock_code, post_id, title, author, publish_dt, views, replies, url)
                    VALUES (:stock_code, :post_id, :title, :author, :publish_dt, :views, :replies, :url)
                    ON CONFLICT(post_id) DO UPDATE SET
                        title = excluded.title,
                        author = COALESCE(excluded.author, eastmoney_comments.author),
                        publish_dt = COALESCE(excluded.publish_dt, eastmoney_comments.publish_dt),
                        views = excluded.views,
                        replies = excluded.replies,
                        url = excluded.url
                    """,
                    {
                        "stock_code": stock_code,
                        "post_id": post["post_id"],
                        "title": post["title"],
                        "author": post["author"],
                        "publish_dt": post["publish_dt"],
                        "views": post["views"],
                        "replies": post["replies"],
                        "url": post["url"],
                    },
                )
                new_posts += 1

            update_crawl_log(conn, "eastmoney_comments", stock_code, new_posts)
            conn.commit()
            logger.info(f"Saved {new_posts} new comments to SQLite (skipped {len(posts) - new_posts} duplicates): {DB_PATH}")
        finally:
            conn.close()

    # ---------- 文件1：帖子列表 ----------
    list_file = out_path / f"{stock_code}-eastmoney-list-{date_str}.txt"

    with open(list_file, "w", encoding="utf-8") as f:
        f.write(f"# {stock_code} 东方财富股吧帖子列表\n")
        f.write(f"# 抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"# 总计: {len(posts)} 条\n")
        f.write("=" * 60 + "\n\n")

        for i, post in enumerate(posts, 1):
            f.write(f"【{i}】{post['title']}\n")
            f.write(f"    作者: {post['author']} | 时间: {post['publish_dt']}\n")
            f.write(f"    阅读:{post['views']}  评论:{post['replies']}\n")
            f.write(f"    {post['url']}\n\n")

    logger.info("List saved: %s", list_file)

    # ---------- 文件2：帖子详情 ----------
    full_file = out_path / f"{stock_code}-eastmoney-full-{date_str}.txt"
    with open(full_file, "w", encoding="utf-8") as f:
        f.write(f"# {stock_code} 东方财富股吧帖子详情\n")
        f.write(f"# 抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"# 总计: {len(posts)} 条\n")
        f.write("=" * 60 + "\n\n")

        for i, post in enumerate(posts, 1):
            formatted = format_post(post, include_body=False)
            f.write(f"【第 {i} 条】\n{formatted}\n")
            f.write("\n" + "=" * 60 + "\n\n")

    logger.info(f"Detail saved: {full_file}")
    return list_file, full_file


# ------------------------------------------------------------------
# CLI 入口
# ------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="抓取东方财富股吧指定股票的评论列表（用于分析散户情绪）")
    parser.add_argument("--stock-code", "-s", required=True, help="股票代码，如 300750（东方财富用纯数字）")
    parser.add_argument("--pages", "-p", type=int, default=3, help="抓取页数（默认3页，每页约40条）")
    parser.add_argument("--delay", "-d", type=float, default=0.5, help="请求间隔秒数（默认0.5秒，请勿设太小）")
    parser.add_argument("--out-dir", "-o", default="./data", help="输出目录（默认 ./data）")
    parser.add_argument("--save-db", action="store_true", help="Save results to SQLite database")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only crawl posts newer than last crawl (requires --save-db, uses post_id dedup)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging()
    stock_code = args.stock_code.strip().lower()

    if not stock_code:
        logger.error("stock-code 不能为空")
        sys.exit(1)

    # 东方财富使用纯数字股票代码（如 300750），不含 sz/sh 前缀
    # 如果用户输入了 sz300750 或 sh600519，提取纯数字部分
    numeric_code = re.sub(r"^(sz|sh)", "", stock_code, flags=re.IGNORECASE)

    test_url = build_list_url(numeric_code, 1)
    logger.info(f"开始抓取股票 [{stock_code}] 的东方财富股吧评论")
    logger.info(f"目标页面: {test_url}")
    logger.info(f"抓取页数: {args.pages}, 请求间隔: {args.delay}s")

    # 抓取数据
    all_items = crawl_stock_comments(numeric_code, args.pages, args.delay, incremental=args.incremental)
    if not all_items:
        logger.error("未能获取到任何帖子，请检查股票代码是否正确（如 300750）")
        sys.exit(1)

    logger.info(f"共获取 {len(all_items)} 条帖子")

    save_results(
        all_items,
        stock_code,  # 使用原始输入作为 stock_code 保存
        args.out_dir,
        save_db=args.save_db,
        incremental=args.incremental,
    )
    logger.info("完成！")


if __name__ == "__main__":
    main()
