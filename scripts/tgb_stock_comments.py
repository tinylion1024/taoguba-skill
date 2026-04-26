#!/usr/bin/env python3
"""
tgb_stock_comments.py
抓取淘股吧指定股票的吧帖评论（网友讨论帖）
用于分析个股的散户情绪和舆情

页面示例：https://www.tgb.cn/quotes/sz300750（宁德时代）

技术方案：淘股吧是 SPA，帖子数据直接嵌入在 HTML 页面的
JavaScript 变量 coolAttr 中，通过正则提取即可，无需 AJAX 请求。

支持 SQLite 持久化（--save-db）和增量爬取（--incremental）。
"""
import argparse
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from common import (
    setup_logging, logger, DB_PATH, DATA_DIR,
    fetch, get_headers,
    get_db, init_db,
    update_crawl_log, get_last_crawl,
)

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
    pattern = r'var\s+coolAttr\s*=\s*(\[.*?\])\s*;?\s*var\s+'
    match = re.search(pattern, html_content, re.DOTALL)
    if not match:
        # 备选：宽松匹配
        pattern2 = r'coolAttr\s*=\s*(\[.*?\])\s*;'
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
def parse_post_item(item: dict) -> dict:
    """
    解析 coolAttr 中的每条记录，提取关键字段。
    rtype: "T"=主帖, "R"=跟帖回复, "W"=未知/系统
    """
    rtype = item.get('rtype', '')
    new_topic_id = item.get('newTopicID', '')
    r_id = item.get('rID', '')

    # 构建帖子URL
    if rtype == 'R' and r_id:
        url = f"https://www.tgb.cn/a/{new_topic_id}/{r_id}#{r_id}"
    else:
        url = f"https://www.tgb.cn/a/{new_topic_id}"

    # 解码 HTML 实体（淘股吧使用 Unicode 转义）
    def decode_text(s):
        if not s:
            return ''
        # 先 unescape HTML 实体，再处理 Unicode 转义
        s = html.unescape(s)
        # 清理 <font color='...'> 标签（淘股吧高亮标签）
        s = re.sub(r"<font[^>]*>([^<]*)</font>", r"\1", s)
        return s.strip()

    subject = decode_text(item.get('subject', ''))
    body = decode_text(item.get('body', ''))
    author = item.get('userName', '')
    action_date = item.get('actionDate', '')
    reply_num = item.get('replyNum', 0)
    view_num = item.get('viewNum', 0)
    useful_num = item.get('usefulNum', 0)

    # 主帖类型
    is_reply = rtype == 'R'

    return {
        'type': rtype,
        'title': subject,
        'author': author,
        'time': action_date,
        'url': url,
        'likes': useful_num,
        'comments': reply_num,
        'views': view_num,
        'is_reply': is_reply,
        'body': body,
        'user_id': item.get('userID', ''),
        'topic_id': new_topic_id,
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
    import time as _time
    _time.sleep(delay)
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


def crawl_stock_comments(stock_code: str, pages: int, delay: float) -> list[dict]:
    """抓取指定股票的多页评论数据"""
    all_posts = []
    for page in range(1, pages + 1):
        items = fetch_stock_page(stock_code, page, delay)
        all_posts.extend(items)
    return all_posts


# ------------------------------------------------------------------
# 格式化输出
# ------------------------------------------------------------------
def format_post(post: dict, include_body: bool = True, body_limit: int = 300) -> str:
    """将单条帖子格式化为可读字符串"""
    post_type = "🔁 跟帖回复" if post['is_reply'] else "📌 主帖"
    lines = [
        f"{post_type}",
        f"[标题] {post['title']}",
        f"[作者] {post['author']} (UID:{post['user_id']})",
        f"[时间] {post['time']}",
        f"[URL]  {post['url']}",
        f"[点赞 {post['likes']}  评论 {post['comments']}  浏览 {post['views']}]",
    ]
    if include_body and post['body']:
        body = post['body'][:body_limit] + ('...' if len(post['body']) > body_limit else '')
        lines.append("---")
        lines.append(body)
    return '\n'.join(lines)


# ------------------------------------------------------------------
# 保存结果到文件
# ------------------------------------------------------------------
def save_results(posts: list[dict], stock_code: str, out_dir: str,
                 save_db: bool = False, incremental: bool = False):
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
                conn.execute("""
                    INSERT INTO stock_comments
                        (stock_code, author_name, author_bid, content, post_url, timestamp, likes)
                    VALUES (:stock_code, :author, :user_id, :body, :url, :time, :likes)
                    ON CONFLICT(id) DO UPDATE SET
                        content=excluded.content, likes=excluded.likes
                """, {
                    'stock_code': stock_code,
                    'author': post['author'],
                    'user_id': post['user_id'],
                    'body': post['body'],
                    'url': post['url'],
                    'time': post['time'],
                    'likes': post['likes'],
                })
                new_posts += 1
            update_crawl_log(conn, 'stock_comments', stock_code, len(posts))
            conn.commit()
            logger.info(f"Saved {len(posts)} comments to SQLite: {DB_PATH}")
        finally:
            conn.close()

    # ---------- 文件1：帖子列表（不含正文） ----------
    list_file = out_path / f"{stock_code}-posts-list-{date_str}.txt"
    main_posts = [p for p in posts if not p['is_reply']]
    reply_posts = [p for p in posts if p['is_reply']]

    with open(list_file, 'w', encoding='utf-8') as f:
        f.write(f"# {stock_code} 淘股吧帖子列表\n")
        f.write(f"# 抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"# 主帖: {len(main_posts)} 条，跟帖: {len(reply_posts)} 条，总计: {len(posts)} 条\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"📌 主帖（共 {len(main_posts)} 条）\n")
        f.write("-" * 60 + "\n")
        for i, post in enumerate(main_posts, 1):
            f.write(f"【{i}】{post['title']}\n")
            f.write(f"    作者: {post['author']} | 时间: {post['time']}\n")
            f.write(f"    点赞:{post['likes']}  评论:{post['comments']}  浏览:{post['views']}\n")
            f.write(f"    {post['url']}\n\n")

        if reply_posts:
            f.write(f"\n🔁 跟帖回复（共 {len(reply_posts)} 条）\n")
            f.write("-" * 60 + "\n")
            for i, post in enumerate(reply_posts, 1):
                f.write(f"【{i}】{post['title']}\n")
                f.write(f"    作者: {post['author']} | 时间: {post['time']}\n")
                f.write(f"    点赞:{post['likes']}  评论:{post['comments']}  浏览:{post['views']}\n")
                f.write(f"    {post['url']}\n\n")

    logger.info("List saved: %s", list_file)

    # ---------- 文件2：帖子详情（含正文） ----------
    full_file = out_path / f"{stock_code}-posts-full-{date_str}.txt"
    with open(full_file, 'w', encoding='utf-8') as f:
        f.write(f"# {stock_code} 淘股吧帖子详情（含正文摘要）\n")
        f.write(f"# 抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"# 总计: {len(posts)} 条\n")
        f.write("=" * 60 + "\n\n")
        for i, post in enumerate(posts, 1):
            formatted = format_post(post, include_body=True, body_limit=500)
            f.write(f"【第 {i} 条】\n{formatted}\n")
            f.write("\n" + "=" * 60 + "\n\n")

    logger.info(f"Detail saved: {full_file}")
    return list_file, full_file


# ------------------------------------------------------------------
# CLI 入口
# ------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="抓取淘股吧指定股票的网友讨论帖（用于分析散户情绪）"
    )
    parser.add_argument(
        '--stock-code', '-s',
        required=True,
        help='股票代码，如 sz300750、sh600519'
    )
    parser.add_argument(
        '--pages', '-p',
        type=int,
        default=3,
        help='抓取页数（默认3页，每页约20条）'
    )
    parser.add_argument(
        '--delay', '-d',
        type=float,
        default=0.5,
        help='请求间隔秒数（默认0.5秒，请勿设太小）'
    )
    parser.add_argument(
        '--out-dir', '-o',
        default='./data',
        help='输出目录（默认 ./data）'
    )
    parser.add_argument('--save-db', action='store_true',
                        help='Save results to SQLite database')
    parser.add_argument('--incremental', action='store_true',
                        help='Only crawl posts newer than last crawl (requires --save-db)')
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

    # 抓取数据
    all_items = crawl_stock_comments(stock_code, args.pages, args.delay)
    if not all_items:
        logger.error("未能获取到任何帖子，请检查股票代码是否正确（如 sz300750）")
        sys.exit(1)

    posts = [parse_post_item(item) for item in all_items]
    main_count = sum(1 for p in posts if not p['is_reply'])
    reply_count = sum(1 for p in posts if p['is_reply'])
    logger.info(f"共获取 {len(posts)} 条帖子（主帖 {main_count}，跟帖 {reply_count}）")

    save_results(posts, stock_code, args.out_dir, save_db=args.save_db, incremental=args.incremental)
    logger.info("完成！")


if __name__ == '__main__':
    main()
