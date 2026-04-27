#!/usr/bin/env python3
"""
crawl_vip_selected_posts.py
爬取淘股吧116位大V的精选帖（精华帖/置顶帖）

功能：
- 读取 references/tgb_blog_authors.json 中116位大V
- 访问每位大V的博客主页，识别并爬取"精选/精华"帖
- 支持断点续爬（--resume）、分页（--pages）、限制作者数（--max-authors）
- 数据存入 SQLite（vip_selected_posts 表）

Usage:
    python scripts/crawl_vip_selected_posts.py --save-db --pages 1
    python scripts/crawl_vip_selected_posts.py --save-db --resume      # 断点续爬
    python scripts/crawl_vip_selected_posts.py --save-db --max-authors 10 --pages 2
"""

import argparse
import html
import html as html_module
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from common import (
    DB_PATH,
    DATA_DIR,
    fetch,
    get_db,
    get_headers,
    init_db,
    load_authors_json,
    logger,
    setup_logging,
)

BASE_URL = "https://www.tgb.cn"
DEFAULT_DELAY = 1.0


# ---------------------------------------------------------------------------
# 数据库 Schema
# ---------------------------------------------------------------------------
VIP_SELECTED_SCHEMA = """
CREATE TABLE IF NOT EXISTS vip_selected_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id       TEXT NOT NULL,
    author_name     TEXT,
    author_tier     TEXT,
    article_url     TEXT UNIQUE,
    title           TEXT,
    body            TEXT,
    publish_date    TEXT,
    view_num        INTEGER DEFAULT 0,
    reply_num       INTEGER DEFAULT 0,
    is_elite        INTEGER DEFAULT 0,     -- 1=精华帖, 0=普通置顶
    body_word_count INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vsp_author    ON vip_selected_posts(author_id);
CREATE INDEX IF NOT EXISTS idx_vsp_elite    ON vip_selected_posts(is_elite);
CREATE INDEX IF NOT EXISTS idx_vsp_pubdate   ON vip_selected_posts(publish_date);
"""


def init_vip_db():
    """初始化 vip_selected_posts 表"""
    conn = get_db()
    conn.executescript(VIP_SELECTED_SCHEMA)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# HTML 解析：从博客列表页提取精选帖
# ---------------------------------------------------------------------------
def parse_blog_articles(html_content: str) -> list[dict]:
    """
    解析淘股吧博客文章列表页，提取所有文章条目。
    识别"精选/精华"帖（有精华标签或置顶样式）。

    Returns:
        list of dict with keys: post_id, title, url, publish_date,
                                view_num, reply_num, is_elite, tags
    """
    soup = BeautifulSoup(html_content, "html.parser")
    articles = []

    # 查找所有文章条目（article_tittle 是淘股吧博客的文章标题div）
    for article_div in soup.find_all("div", class_="article_tittle"):
        try:
            # 标题和链接
            title_tag = article_div.find("a", href=True)
            if not title_tag:
                continue

            href = title_tag.get("href", "")
            title = title_tag.get("title", title_tag.get_text(strip=True))

            # 构建完整URL
            if href.startswith("a/"):
                article_url = f"{BASE_URL}/{href}"
            elif href.startswith("/"):
                article_url = f"{BASE_URL}{href}"
            else:
                article_url = f"{BASE_URL}/{href}"

            # 提取文章ID
            article_id_match = re.search(r"/a/([a-zA-Z0-9]+)", article_url)
            article_id = article_id_match.group(1) if article_id_match else ""

            # 浏览/回复数 (class="tittle_llhf")
            llhf = article_div.find("div", class_="tittle_llhf")
            views_replies_text = llhf.get_text(strip=True) if llhf else ""
            vr = re.findall(r"(\d+)", views_replies_text)
            views = int(vr[0]) if len(vr) > 0 else 0
            replies = int(vr[1]) if len(vr) > 1 else 0

            # 发表时间
            fbdate = article_div.find("div", class_="tittle_fbshijian")
            pub_date = fbdate.get_text(strip=True) if fbdate else ""

            # 标签判断：精华帖/置顶
            tags = []
            is_elite = 0

            # 精华标签：class="tittle_jinghua" 或 文本包含"精"
            if article_div.find("span", class_="tittle_jinghua"):
                tags.append("精华")
                is_elite = 1

            # 置顶标签
            if article_div.find("span", class_="tittle_zhiding"):
                tags.append("置顶")

            # 原创标签
            if article_div.find("span", class_="tittle_yuanchuang"):
                tags.append("原创")

            # 也检查标题前的特殊标记（有些精华帖用字体颜色区分）
            # 不依赖CSS颜色，统一用HTML结构判断

            articles.append({
                "post_id": article_id,
                "title": title,
                "url": article_url,
                "publish_date": pub_date,
                "views": views,
                "replies": replies,
                "is_elite": is_elite,
                "tags": tags,
            })
        except Exception as e:
            logger.debug(f"Failed to parse article div: {e}")
            continue

    return articles


def fetch_article_body(article_url: str, delay: float = 0.5) -> str:
    """抓取单篇文章的正文内容"""
    time.sleep(delay + random.uniform(0, 0.3))
    try:
        html = fetch(article_url, headers=get_headers({"Referer": BASE_URL}), timeout=15)
        soup = BeautifulSoup(html, "html.parser")

        body = ""
        # 尝试多个可能的内容容器
        for cls in ["stockDetailContent", "article-content", "content"]:
            elem = soup.find(class_=cls)
            if elem:
                body = elem.get_text(separator="\n", strip=True)
                break

        if not body:
            # 备选：查找大段文字区域
            for tag in soup.find_all(["div", "article"]):
                text = tag.get_text(separator="\n", strip=True)
                if len(text) > 200:
                    body = text
                    break

        if not body:
            # 最后备选：找id包含content或body的元素
            for tag_id in ["content", "body", "main"]:
                elem = soup.find(id=re.compile(tag_id, re.I))
                if elem:
                    body = elem.get_text(separator="\n", strip=True)
                    break

        # 清理body
        body = html_module.unescape(body)
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
        return body.strip()

    except Exception as e:
        logger.warning(f"Failed to fetch body from {article_url}: {e}")
        return ""


def count_words(text: str) -> int:
    """统计中英文混合文本的字数（中文1字，英文单词按空格切分）"""
    if not text:
        return 0
    # 移除多余空白
    text = re.sub(r"\s+", " ", text).strip()
    # 中文字符
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    # 英文单词（按空格和标点切分）
    english_words = len(re.findall(r"[a-zA-Z]+", text))
    return chinese + english_words


# ---------------------------------------------------------------------------
# 核心爬取逻辑
# ---------------------------------------------------------------------------
def crawl_vip_blog(
    author_id: str,
    author_name: str,
    author_tier: str,
    pages: int = 1,
    delay: float = DEFAULT_DELAY,
    save_db: bool = False,
    conn=None,
    fetch_body: bool = False,
) -> list[dict]:
    """
    爬取单个大V的精选帖

    Returns:
        list of post dicts
    """
    all_posts = []

    for page in range(1, pages + 1):
        if page == 1:
            url = f"{BASE_URL}/blog/{author_id}"
        else:
            url = f"{BASE_URL}/blog/{author_id}?page={page}"

        logger.info(f"  Page {page}: {url}")
        time.sleep(delay + random.uniform(0, 0.5))

        try:
            html_content = fetch(url, headers=get_headers({"Referer": BASE_URL}), timeout=15)
        except Exception as e:
            logger.warning(f"  Failed to fetch page {page}: {e}")
            break

        articles = parse_blog_articles(html_content)

        if not articles:
            if page == 1:
                logger.warning(f"  No articles found on first page for author {author_id}")
            break

        logger.info(f"  → Found {len(articles)} articles, {sum(1 for a in articles if a['is_elite'])} elite")

        # 筛选精选帖（is_elite=1）或置顶帖（有标签的也算）
        # 任务要求抓"精选/精华"帖：优先抓精华帖，如果页面有置顶标记也抓
        elite_posts = [a for a in articles if a["is_elite"] or "置顶" in a.get("tags", [])]
        if not elite_posts:
            # 如果一页都没有精华帖，把第一页的所有帖子都算（因为精华帖通常在首页）
            if page == 1:
                elite_posts = articles[:5]  # 最多取前5条作为"疑似精选"
                logger.info(f"  No elite posts found, using top 5 as selected")

        for art in elite_posts:
            all_posts.append({
                "author_id": author_id,
                "author_name": author_name,
                "author_tier": author_tier,
                "article_url": art["url"],
                "title": art["title"],
                "body": "",
                "publish_date": art["publish_date"],
                "view_num": art["views"],
                "reply_num": art["replies"],
                "is_elite": art["is_elite"],
                "body_word_count": 0,
            })

        if page < pages:
            time.sleep(delay + random.uniform(0, 0.3))

    # 如果需要抓取正文
    if fetch_body and all_posts:
        logger.info(f"  → 开始抓取 {len(all_posts)} 篇文章正文...")
        for i, post in enumerate(all_posts, start=1):
            logger.info(f"  → [{i}/{len(all_posts)}] 抓取正文: {post['title'][:30]}...")
            body = fetch_article_body(post["article_url"], delay=delay)
            post["body"] = body
            post["body_word_count"] = count_words(body)
            time.sleep(delay + random.uniform(0, 0.2))

    return all_posts


def save_posts_to_db(posts: list[dict], conn):
    """将帖子批量存入 SQLite（upsert）"""
    for post in posts:
        try:
            conn.execute(
                """
                INSERT INTO vip_selected_posts
                    (author_id, author_name, author_tier, article_url, title, body,
                     publish_date, view_num, reply_num, is_elite, body_word_count)
                VALUES (:author_id, :author_name, :author_tier, :article_url, :title, :body,
                        :publish_date, :view_num, :reply_num, :is_elite, :body_word_count)
                ON CONFLICT(article_url) DO UPDATE SET
                    title=excluded.title,
                    view_num=excluded.view_num,
                    reply_num=excluded.reply_num,
                    is_elite=excluded.is_elite,
                    body=excluded.body,
                    body_word_count=excluded.body_word_count
                """,
                post,
            )
        except Exception as e:
            logger.debug(f"DB upsert error: {e}")
            continue


def get_resume_author_id(conn) -> str | None:
    """从 crawl_log 获取断点续爬位置（返回 author_id）"""
    row = conn.execute(
        """
        SELECT target_id FROM crawl_log
        WHERE crawl_type = 'vip_selected_posts'
        ORDER BY id DESC LIMIT 1
        """,
    ).fetchone()
    return row["target_id"] if row else None


def mark_crawl_done(conn, author_id: str, records: int):
    """记录爬取完成点"""
    conn.execute(
        """
        INSERT INTO crawl_log (crawl_type, target_id, last_crawl, records, status)
        VALUES ('vip_selected_posts', ?, datetime('now'), ?, 'success')
        """,
        (author_id, records),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def crawl_all_vip_selected_posts(
    pages: int = 1,
    delay: float = DEFAULT_DELAY,
    save_db: bool = False,
    resume: bool = False,
    max_authors: int = 116,
    fetch_body: bool = False,
) -> dict:
    """爬取所有（或限定数量）大V的精选帖"""
    authors_map = load_authors_json()
    if not authors_map:
        logger.error("No authors found in references/tgb_blog_authors.json")
        return {"success": 0, "failed": 0, "total_posts": 0, "errors": []}

    if save_db:
        init_vip_db()

    conn = get_db() if save_db else None

    # 断点续爬：找出起始位置
    start_author_idx = 0
    if resume and conn:
        last_author_id = get_resume_author_id(conn)
        if last_author_id:
            author_ids = list(authors_map.keys())
            try:
                start_author_idx = author_ids.index(last_author_id) + 1
                logger.info(f"Resume from author index {start_author_idx} (last: {last_author_id})")
            except ValueError:
                start_author_idx = 0

    authors_list = list(authors_map.items())[start_author_idx:start_author_idx + max_authors]
    total = len(authors_list)

    results = []
    errors = []
    success_count = 0
    failed_count = 0

    logger.info(f"开始爬取 {total} 位大V 的精选帖（pages={pages}, resume={resume}, max_authors={max_authors}）")

    for i, (bid, info) in enumerate(authors_list, start_author_idx + 1):
        name = info.get("name", "unknown")
        tier = info.get("tier", "")
        fans = info.get("fans", 0)

        logger.info(f"[{i}/{start_author_idx + max_authors}] === 爬取 {name} (ID:{bid}, {tier}, {fans:,}粉) ===")

        try:
            posts = crawl_vip_blog(
                author_id=bid,
                author_name=name,
                author_tier=tier,
                pages=pages,
                delay=delay,
                save_db=save_db,
                conn=conn,
                fetch_body=fetch_body,
            )

            if save_db and conn and posts:
                save_posts_to_db(posts, conn)
                mark_crawl_done(conn, bid, len(posts))

            success_count += 1
            results.append({"bid": bid, "name": name, "count": len(posts)})
            logger.info(f"  → 爬取 {len(posts)} 条精选帖")

        except Exception as e:
            logger.error(f"  Failed to crawl author {bid} ({name}): {e}")
            errors.append({"bid": bid, "name": name, "error": str(e)})
            failed_count += 1

        # 随机延迟（1-2秒 + 随机抖动）
        sleep_time = delay + random.uniform(0.5, 1.5)
        if i < start_author_idx + max_authors - 1:
            time.sleep(sleep_time)

    # 汇总
    logger.info(f"\n{'=' * 60}")
    logger.info(f"大V精选帖爬取完成: 成功 {success_count}/{total}, 失败 {failed_count}")
    logger.info(f"共收集 {sum(r['count'] for r in results)} 条精选帖")

    if conn:
        conn.close()

    return {
        "success": success_count,
        "failed": failed_count,
        "total_posts": sum(r["count"] for r in results),
        "results": results,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="爬取淘股吧116位大V的精选帖（精华帖/置顶帖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 爬取所有大V精选帖（只第1页，因为精华帖通常在首页）
  python scripts/crawl_vip_selected_posts.py --save-db

  # 多页爬取（某些大V精华帖在后面几页）
  python scripts/crawl_vip_selected_posts.py --save-db --pages 3

  # 断点续爬（从上次中断处继续）
  python scripts/crawl_vip_selected_posts.py --save-db --resume

  # 只爬前20位大V（测试用）
  python scripts/crawl_vip_selected_posts.py --save-db --max-authors 20 --pages 2
        """,
    )
    parser.add_argument(
        "--pages", "-p", type=int, default=1,
        help="每博客爬取页数（默认1，精华帖通常在首页）"
    )
    parser.add_argument(
        "--delay", "-d", type=float, default=DEFAULT_DELAY,
        help=f"请求间隔秒数（默认{DEFAULT_DELAY}）"
    )
    parser.add_argument(
        "--save-db", action="store_true",
        help="保存到 SQLite 数据库（data/tgb.db）"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="断点续爬：从上次中断处继续（按 author_id）"
    )
    parser.add_argument(
        "--max-authors", "-n", type=int, default=116,
        help="最多爬取的大V数量（默认116，即全部）"
    )
    parser.add_argument(
        "--fetch-body", action="store_true",
        help="同时抓取每篇文章的正文（速度较慢）"
    )
    parser.add_argument(
        "--update-body", action="store_true",
        help="仅更新数据库中已有帖子的正文（不重复爬列表页）"
    )
    parser.add_argument(
        "--log-file", help="日志文件路径"
    )
    return parser.parse_args()


def update_bodies_only(delay: float = DEFAULT_DELAY) -> dict:
    """只更新数据库中已有帖子的正文（不爬列表页）"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, author_id, author_name, article_url, title FROM vip_selected_posts WHERE body = '' OR body IS NULL"
    ).fetchall()
    total = len(rows)
    logger.info(f"需要更新正文的帖子数: {total}")

    updated = 0
    for i, row in enumerate(rows, start=1):
        url = row["article_url"]
        logger.info(f"[{i}/{total}] 更新正文: {row['title'][:30]}... ({url})")
        body = fetch_article_body(url, delay=delay)
        word_count = count_words(body)
        conn.execute(
            "UPDATE vip_selected_posts SET body=?, body_word_count=? WHERE id=?",
            (body, word_count, row["id"]),
        )
        updated += 1
        if i % 10 == 0:
            conn.commit()
            logger.info(f"  → 已提交 {i} 条")
        time.sleep(delay + random.uniform(0, 0.2))

    conn.commit()
    conn.close()
    return {"updated": updated, "total": total}


def main():
    args = parse_args()
    setup_logging(log_file=args.log_file)

    # 单独更新body模式
    if args.update_body:
        result = update_bodies_only(delay=args.delay)
        print(f"\n{'=' * 60}")
        print(f"正文更新完成: 共 {result['total']} 条需更新, 成功更新 {result['updated']} 条")
        print(f"{'=' * 60}")
        return

    if not args.save_db:
        logger.warning("未指定 --save-db，数据将不会持久化到数据库")

    result = crawl_all_vip_selected_posts(
        pages=args.pages,
        delay=args.delay,
        save_db=args.save_db,
        resume=args.resume,
        max_authors=args.max_authors,
        fetch_body=args.fetch_body,
    )

    print(f"\n{'=' * 60}")
    print(f"执行完成:")
    print(f"  成功爬取: {result['success']} 位大V")
    print(f"  失败: {result['failed']} 位大V")
    print(f"  精选帖总数: {result['total_posts']} 条")
    if result['errors']:
        print(f"  失败列表: {[e['name'] for e in result['errors']]}")

    if args.save_db:
        print(f"\n数据库: {DB_PATH}")
        conn = get_db()
        total = conn.execute("SELECT COUNT(*) as cnt FROM vip_selected_posts").fetchone()["cnt"]
        elite = conn.execute("SELECT COUNT(*) as cnt FROM vip_selected_posts WHERE is_elite=1").fetchone()["cnt"]
        conn.close()
        print(f"  vip_selected_posts 表: 共 {total} 条（精华帖 {elite} 条）")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()