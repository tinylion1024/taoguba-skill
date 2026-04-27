#!/usr/bin/env python3
"""
tgb_stock_comments.py
抓取淘股吧指定股票的吧帖评论（网友讨论帖）
用于分析个股的散户情绪和舆情

页面示例：https://www.tgb.cn/quotes/sz300750（宁德时代）

技术方案：淘股吧是 SPA，帖子数据直接嵌入在 HTML 页面的
JavaScript 变量 coolAttr 中，通过正则提取即可，无需 AJAX 请求。

支持 SQLite 持久化（--save-db）和增量爬取（--incremental）。

新增功能：
- 大V点评：识别认证用户或高粉丝用户的帖子
- --crawl-all-authors-posts：爬取所有大V在目标股票下的讨论帖
"""

import argparse
import html
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from common import (
    DB_PATH,
    DATA_DIR,
    fetch,
    get_db,
    get_headers,
    get_last_crawl,
    init_db,
    load_authors_json,
    logger,
    setup_logging,
    update_crawl_log,
)


# ------------------------------------------------------------------
# 全局配置：股票讨论页面的VIP识别阈值
# ------------------------------------------------------------------
# 粉丝数超过此阈值认为是"大V"（用于评论区识别）
VIP_FANS_THRESHOLD = 10000  # 1万粉丝以上


# ------------------------------------------------------------------
# 核心：从 HTML 中提取 coolAttr JSON 数据
# ------------------------------------------------------------------
def extract_coolattr_from_html(html_content: str) -> list[dict]:
    """
    淘股吧的帖子数据直接嵌入在 HTML 页面的 <script> 标签中：
        var coolAttr = [{...}, {...}, ...];
    本函数通过正则提取并解析该 JSON 数据。
    """
    # 匹配 var coolAttr = [...] 捕获JSON数组部分
    pattern = r"var\s+coolAttr\s*=\s*(\[.*?\])\s*;?\s*var\s+"
    match = re.search(pattern, html_content, re.DOTALL)
    if not match:
        # 备选：宽松匹配
        pattern2 = r"coolAttr\s*=\s*(\[.*?\])\s*;"
        match = re.search(pattern2, html_content, re.DOTALL)

    if not match:
        logger.error("未找到 coolAttr 数据，页面结构可能已变更")
        return []

    json_str = match.group(1)
    try:
        data = json.loads(json_str)
        return data
    except json.JSONDecodeError as e:
        logger.error(f"coolAttr JSON 解析失败: {e}")
        return []


# ------------------------------------------------------------------
# 数据解析：将每条帖子的字段提取为结构化 dict
# ------------------------------------------------------------------
def parse_post_item(item: dict, authors_map: dict = None) -> dict:
    """
    解析 coolAttr 中的每条记录，提取关键字段。
    rtype: "T"=主帖, "R"=跟帖回复, "W"=未知/系统
    
    authors_map: 大V信息映射表，用于识别VIP用户
    """
    rtype = item.get("rtype", "")
    new_topic_id = item.get("newTopicID", "")
    r_id = item.get("rID", "")

    # 构建帖子URL
    if rtype == "R" and r_id:
        url = f"https://www.tgb.cn/a/{new_topic_id}/{r_id}#{r_id}"
    else:
        url = f"https://www.tgb.cn/a/{new_topic_id}"

    # 解码 HTML 实体（淘股吧使用 Unicode 转义）
    def decode_text(s):
        if not s:
            return ""
        # 先 unescape HTML 实体，再处理 Unicode 转义
        s = html.unescape(s)
        # 清理 <font color='...'> 标签（淘股吧高亮标签）
        s = re.sub(r"<font[^>]*>([^<]*)</font>", r"\1", s)
        return s.strip()

    subject = decode_text(item.get("subject", ""))
    body = decode_text(item.get("body", ""))
    author = item.get("userName", "")
    action_date = item.get("actionDate", "")
    reply_num = item.get("replyNum", 0)
    view_num = item.get("viewNum", 0)
    useful_num = item.get("usefulNum", 0)
    user_id = item.get("userID", "")

    # 主帖类型
    is_reply = rtype == "R"

    # VIP 识别：检查用户是否为大V
    is_vip = False
    vip_tier = ""
    author_fans = 0
    if authors_map and user_id in authors_map:
        author_info = authors_map[user_id]
        is_vip = True
        vip_tier = author_info.get("tier", "")
        author_fans = author_info.get("fans", 0)

    return {
        "type": rtype,
        "title": subject,
        "author": author,
        "time": action_date,
        "url": url,
        "likes": useful_num,
        "comments": reply_num,
        "views": view_num,
        "is_reply": is_reply,
        "body": body,
        "user_id": user_id,
        "topic_id": new_topic_id,
        "is_vip": is_vip,
        "vip_tier": vip_tier,
        "author_fans": author_fans,
    }


# ------------------------------------------------------------------
# 批量获取股票多页数据
# ------------------------------------------------------------------
def fetch_stock_page(stock_code: str, page: int = 1, delay: float = 0.5) -> list[dict]:
    """
    抓取指定股票的一页数据。
    stock_code: 如 sz300750
    page: 页码（第1页URL没有页码后缀）
    """
    time.sleep(delay + random.uniform(0, 0.5))  # 随机延迟
    if page == 1:
        url = f"https://www.tgb.cn/quotes/{stock_code}"
    else:
        url = f"https://www.tgb.cn/quotes/{stock_code}/{page}"

    try:
        html_content = fetch(url, headers=get_headers({"Referer": "https://www.tgb.cn/"}), timeout=15)
    except Exception as e:
        logger.error(f"Request failed [{url}]: {e}")
        return []

    items = extract_coolattr_from_html(html_content)
    logger.info(f"Page {page} [{stock_code}] → {len(items)} posts")
    return items


def crawl_stock_comments(stock_code: str, pages: int, delay: float, incremental: bool = False) -> list[dict]:
    """抓取指定股票的多页评论数据"""
    all_posts = []

    # 增量模式：获取上次爬取时间
    cutoff = None
    if incremental:
        cutoff = get_last_crawl("stock_comments", stock_code)
        if cutoff:
            logger.info(f"增量模式: 仅爬取 {cutoff} 之后的帖子")

    for page in range(1, pages + 1):
        items = fetch_stock_page(stock_code, page, delay)

        # 增量过滤：按时间戳筛选
        if cutoff and items:
            before = len(items)
            items = [item for item in items if item.get("actionDate", "") >= cutoff]
            if items:
                logger.info(f"  增量: {before}条中{before - len(items)}条已爬过，保留{len(items)}条新帖")
            else:
                logger.info(f"Page {page}: 无新帖子，停止爬取")
                break

        all_posts.extend(items)
    return all_posts


# ------------------------------------------------------------------
# 大V点评筛选
# ------------------------------------------------------------------
def filter_vip_comments(posts: list[dict]) -> list[dict]:
    """从帖子列表中筛选出大V（认证或高粉丝）的帖子"""
    vip_posts = [p for p in posts if p.get("is_vip", False)]
    # 按粉丝数排序
    vip_posts.sort(key=lambda x: x.get("author_fans", 0), reverse=True)
    return vip_posts


def format_vip_comment(post: dict, include_body: bool = True, body_limit: int = 300) -> str:
    """将大V帖子格式化为可读字符串"""
    tier_emoji = {"S级": "👑", "A级": "🌟", "B级": "⭐", "C级": "✨", "D级": "🔹", "E级": "🔸"}
    emoji = tier_emoji.get(post.get("vip_tier", ""), "🔹")
    lines = [
        f"{emoji} [{post['vip_tier']}] {post['author']} (粉丝: {post['author_fans']:,})",
        f"[标题] {post['title']}",
        f"[时间] {post['time']}",
        f"[URL]  {post['url']}",
        f"[点赞 {post['likes']}  评论 {post['comments']}  浏览 {post['views']}]",
    ]
    if include_body and post["body"]:
        body = post["body"][:body_limit] + ("..." if len(post["body"]) > body_limit else "")
        lines.append("---")
        lines.append(body)
    return "\n".join(lines)


# ------------------------------------------------------------------
# 爬取所有大V在特定股票下的讨论帖
# ------------------------------------------------------------------
def crawl_all_vips_posts_about_stock(
    stock_code: str,
    pages: int = 3,
    delay: float = 1.0,
    save_db: bool = False,
    target_stocks: list[str] = None,
) -> dict:
    """
    读取 references/tgb_blog_authors.json 中所有大V，
    依次爬取他们在目标股票页面下的讨论帖。
    
    target_stocks: 重点关注股票列表，如 ["sz300750", "sh600519"]
    """
    authors_map = load_authors_json()
    if not authors_map:
        logger.error("No authors found in references/tgb_blog_authors.json")
        return {"success": 0, "failed": 0, "results": []}

    if save_db:
        init_db()

    total = len(authors_map)
    results = []
    errors = []
    success_count = 0
    failed_count = 0

    # 目标股票列表（默认为传入的stock_code）
    stocks_to_check = target_stocks or [stock_code]

    logger.info(f"开始爬取 {total} 位大V在 {len(stocks_to_check)} 只股票下的讨论帖")
    logger.info(f"目标股票: {stocks_to_check}")

    for i, (bid, info) in enumerate(authors_map.items(), 1):
        name = info.get("name", "unknown")
        fans = info.get("fans", 0)
        tier = info.get("tier", "")
        
        logger.info(f"[{i}/{total}] === 爬取 {name} (粉丝:{fans:,} {tier}) 的股票讨论 ===")

        try:
            vip_posts_found = []
            for sc in stocks_to_check:
                # 爬取该股票页面，收集此大V的帖子
                items = crawl_stock_comments(sc, pages, delay, incremental=False)
                
                # 筛选属于该大V的帖子
                for item in items:
                    if str(item.get("userID", "")) == str(bid):
                        post = parse_post_item(item, authors_map)
                        post["target_stock"] = sc
                        vip_posts_found.append(post)

            if vip_posts_found:
                logger.info(f"  → 找到 {len(vip_posts_found)} 条关于目标股票的帖子")
                for p in vip_posts_found:
                    results.append({
                        "author_id": bid,
                        "author_name": name,
                        "tier": tier,
                        "fans": fans,
                        "stock_code": p.get("target_stock", stock_code),
                        "title": p.get("title", ""),
                        "body": p.get("body", ""),
                        "url": p.get("url", ""),
                        "time": p.get("time", ""),
                        "likes": p.get("likes", 0),
                    })

                # 保存到数据库
                if save_db:
                    _save_vip_stock_posts_to_db(vip_posts_found, stock_code)

            success_count += 1
        except Exception as e:
            logger.error(f"Failed to crawl {bid} ({name}): {e}")
            errors.append({"bid": bid, "name": name, "error": str(e)})
            failed_count += 1

        if i < total:
            time.sleep(delay + random.uniform(0, 0.5))

    # 汇总
    logger.info(f"\n{'=' * 60}")
    logger.info(f"大V股票讨论爬取完成: 成功 {success_count}/{total}, 失败 {failed_count}")
    logger.info(f"共收集 {len(results)} 条大V在目标股票下的讨论帖")

    return {
        "success": success_count,
        "failed": failed_count,
        "total_vip_posts": len(results),
        "results": results,
        "errors": errors,
    }


def _save_vip_stock_posts_to_db(posts: list[dict], stock_code: str):
    """将大V在特定股票下的讨论帖保存到数据库"""
    conn = get_db()
    try:
        for post in posts:
            conn.execute(
                """
                INSERT INTO stock_comments
                    (stock_code, topic_id, author_name, author_bid, content, post_url, timestamp, likes)
                VALUES (:stock_code, :topic_id, :author, :user_id, :body, :url, :time, :likes)
                ON CONFLICT(stock_code, topic_id) DO UPDATE SET
                    content=excluded.content, likes=excluded.likes
                """,
                {
                    "stock_code": stock_code,
                    "topic_id": post.get("topic_id", ""),
                    "author": post.get("author", ""),
                    "user_id": post.get("user_id", ""),
                    "body": post.get("body", ""),
                    "url": post.get("url", ""),
                    "time": post.get("time", ""),
                    "likes": post.get("likes", 0),
                },
            )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------
# 格式化输出
# ------------------------------------------------------------------
def format_post(post: dict, include_body: bool = True, body_limit: int = 300) -> str:
    """将单条帖子格式化为可读字符串"""
    post_type = "🔁 跟帖回复" if post["is_reply"] else "📌 主帖"
    vip_marker = " [VIP]" if post.get("is_vip", False) else ""
    lines = [
        f"{post_type}{vip_marker}",
        f"[标题] {post['title']}",
        f"[作者] {post['author']} (UID:{post['user_id']})",
        f"[时间] {post['time']}",
        f"[URL]  {post['url']}",
        f"[点赞 {post['likes']}  评论 {post['comments']}  浏览 {post['views']}]",
    ]
    if include_body and post["body"]:
        body = post["body"][:body_limit] + ("..." if len(post["body"]) > body_limit else "")
        lines.append("---")
        lines.append(body)
    return "\n".join(lines)


# ------------------------------------------------------------------
# 保存结果到文件
# ------------------------------------------------------------------
def save_results(posts: list[dict], stock_code: str, out_dir: str, save_db: bool = False, incremental: bool = False):
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
                # 增量模式：基于 topic_id 去重，已存在的跳过
                existing = conn.execute(
                    "SELECT id FROM stock_comments WHERE stock_code = ? AND topic_id = ?",
                    (stock_code, post["topic_id"]),
                ).fetchone()

                if incremental and existing:
                    logger.debug(f"Skipping existing topic_id: {post['topic_id']}")
                    continue

                conn.execute(
                    """
                    INSERT INTO stock_comments
                        (stock_code, topic_id, author_name, author_bid, content, post_url, timestamp, likes)
                    VALUES (:stock_code, :topic_id, :author, :user_id, :body, :url, :time, :likes)
                    ON CONFLICT(stock_code, topic_id) DO UPDATE SET
                        content=excluded.content, likes=excluded.likes
                    """,
                    {
                        "stock_code": stock_code,
                        "topic_id": post["topic_id"],
                        "author": post["author"],
                        "user_id": post["user_id"],
                        "body": post["body"],
                        "url": post["url"],
                        "time": post["time"],
                        "likes": post["likes"],
                    },
                )
                new_posts += 1
            update_crawl_log(conn, "stock_comments", stock_code, new_posts)
            conn.commit()
            logger.info(
                f"Saved {new_posts} new comments to SQLite (skipped {len(posts) - new_posts} duplicates): {DB_PATH}"
            )
        finally:
            conn.close()

    # ---------- 文件1：帖子列表（不含正文） ----------
    list_file = out_path / f"{stock_code}-posts-list-{date_str}.txt"
    main_posts = [p for p in posts if not p["is_reply"]]
    reply_posts = [p for p in posts if p["is_reply"]]

    with open(list_file, "w", encoding="utf-8") as f:
        f.write(f"# {stock_code} 淘股吧帖子列表\n")
        f.write(f"# 抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"# 主帖: {len(main_posts)} 条，跟帖: {len(reply_posts)} 条，总计: {len(posts)} 条\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"📌 主帖（共 {len(main_posts)} 条）\n")
        f.write("-" * 60 + "\n")
        for i, post in enumerate(main_posts, 1):
            vip_flag = " [VIP]" if post.get("is_vip") else ""
            f.write(f"【{i}】{post['title']}{vip_flag}\n")
            f.write(f"    作者: {post['author']} | 时间: {post['time']}\n")
            f.write(f"    点赞:{post['likes']}  评论:{post['comments']}  浏览:{post['views']}\n")
            f.write(f"    {post['url']}\n\n")

        if reply_posts:
            f.write(f"\n🔁 跟帖回复（共 {len(reply_posts)} 条）\n")
            f.write("-" * 60 + "\n")
            for i, post in enumerate(reply_posts, 1):
                vip_flag = " [VIP]" if post.get("is_vip") else ""
                f.write(f"【{i}】{post['title']}{vip_flag}\n")
                f.write(f"    作者: {post['author']} | 时间: {post['time']}\n")
                f.write(f"    点赞:{post['likes']}  评论:{post['comments']}  浏览:{post['views']}\n")
                f.write(f"    {post['url']}\n\n")

    logger.info("List saved: %s", list_file)

    # ---------- 文件2：帖子详情（含正文） ----------
    full_file = out_path / f"{stock_code}-posts-full-{date_str}.txt"
    with open(full_file, "w", encoding="utf-8") as f:
        f.write(f"# {stock_code} 淘股吧帖子详情（含正文摘要）\n")
        f.write(f"# 抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"# 总计: {len(posts)} 条\n")
        f.write("=" * 60 + "\n\n")
        for i, post in enumerate(posts, 1):
            formatted = format_post(post, include_body=True, body_limit=500)
            f.write(f"【第 {i} 条】\n{formatted}\n")
            f.write("\n" + "=" * 60 + "\n\n")

    logger.info(f"Detail saved: {full_file}")

    # ---------- 文件3：大V点评汇总 ----------
    vip_posts = filter_vip_comments(posts)
    if vip_posts:
        vip_file = out_path / f"{stock_code}-vip-comments-{date_str}.txt"
        with open(vip_file, "w", encoding="utf-8") as f:
            f.write(f"# {stock_code} 大V点评汇总\n")
            f.write(f"# 抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# 大V帖子数: {len(vip_posts)} 条\n")
            f.write("=" * 60 + "\n\n")
            for i, post in enumerate(vip_posts, 1):
                formatted = format_vip_comment(post, include_body=True, body_limit=500)
                f.write(f"【大V点评 {i}】\n{formatted}\n")
                f.write("\n" + "=" * 60 + "\n\n")
        logger.info(f"VIP comments saved: {vip_file}")

    return list_file, full_file


# ------------------------------------------------------------------
# CLI 入口
# ------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="抓取淘股吧指定股票的网友讨论帖（用于分析散户情绪）")
    parser.add_argument("--stock-code", "-s", required=True, help="股票代码，如 sz300750、sh600519")
    parser.add_argument("--pages", "-p", type=int, default=3, help="抓取页数（默认3页，每页约20条）")
    parser.add_argument("--delay", "-d", type=float, default=0.5, help="请求间隔秒数（默认0.5秒，请勿设太小）")
    parser.add_argument("--out-dir", "-o", default="./data", help="输出目录（默认 ./data）")
    parser.add_argument("--save-db", action="store_true", help="Save results to SQLite database")
    parser.add_argument(
        "--incremental", action="store_true", help="Only crawl posts newer than last crawl (requires --save-db)"
    )
    parser.add_argument(
        "--crawl-vip",
        action="store_true",
        help="简写：等价于 --crawl-all-authors-posts，从116位大V中爬取此股票下的讨论帖"
    )
    parser.add_argument(
        "--crawl-all-authors-posts",
        action="store_true",
        help="Crawl all VIP authors' posts about this stock (reads from references/tgb_blog_authors.json)"
    )
    parser.add_argument(
        "--target-stocks",
        nargs="+",
        help="重点关注股票列表（用于 --crawl-all-authors-posts），如 sz300750 sh600519"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging()
    stock_code = args.stock_code.strip().lower()

    if not stock_code:
        logger.error("stock-code 不能为空")
        sys.exit(1)

    test_url = f"https://www.tgb.cn/quotes/{stock_code}"
    logger.info(f"开始抓取股票 [{stock_code}] 的讨论帖")
    logger.info(f"目标页面: {test_url}")
    logger.info(f"抓取页数: {args.pages}, 请求间隔: {args.delay}s")

    # 加载大V信息
    authors_map = load_authors_json()
    logger.info(f"已加载 {len(authors_map)} 位大V信息")

    if args.crawl_all_authors_posts or args.crawl_vip:
        # 爬取所有大V在目标股票下的讨论帖
        result = crawl_all_vips_posts_about_stock(
            stock_code=stock_code,
            pages=args.pages,
            delay=args.delay,
            save_db=args.save_db,
            target_stocks=args.target_stocks or [stock_code],
        )
        logger.info(f"大V股票讨论爬取完成: 成功 {result['success']}, 失败 {result['failed']}")
        logger.info(f"共收集 {result['total_vip_posts']} 条大V讨论帖")
    else:
        # 抓取普通评论数据
        all_items = crawl_stock_comments(stock_code, args.pages, args.delay, incremental=args.incremental)
        if not all_items:
            logger.error("未能获取到任何帖子，请检查股票代码是否正确（如 sz300750）")
            sys.exit(1)

        posts = [parse_post_item(item, authors_map) for item in all_items]
        main_count = sum(1 for p in posts if not p["is_reply"])
        reply_count = sum(1 for p in posts if p["is_reply"])
        vip_count = sum(1 for p in posts if p.get("is_vip", False))
        logger.info(f"共获取 {len(posts)} 条帖子（主帖 {main_count}，跟帖 {reply_count}，大V帖 {vip_count}）")

        save_results(posts, stock_code, args.out_dir, save_db=args.save_db, incremental=args.incremental)
        logger.info("完成！")


if __name__ == "__main__":
    main()
