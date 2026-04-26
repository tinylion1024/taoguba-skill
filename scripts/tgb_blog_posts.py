#!/usr/bin/env python3
"""
tgb_blog_posts.py
大V博客帖子爬虫 for 淘股吧 (tgb.cn)

抓取指定大V博客的所有帖子列表，包括标题、URL、浏览/回复数、发表时间、标签。
支持 SQLite 持久化和增量爬取。

Usage:
    python scripts/tgb_blog_posts.py --blog-id 7105646 --pages 3
    python scripts/tgb_blog_posts.py --blog-id 7105646 --pages 3 --save-db
    python scripts/tgb_blog_posts.py --blog-id 7105646 --save-db --incremental  # 仅抓新帖子
    python scripts/tgb_blog_posts.py --all-authors --pages 3 --save-db          # 爬取所有已知大V
"""

import argparse
import json
import random
import re
import sys
import time

from bs4 import BeautifulSoup
from common import (
    DATA_DIR,
    DB_PATH,
    bulk_upsert_posts,
    fetch,
    get_db,
    get_headers,
    get_last_crawl,
    init_db,
    load_authors_json,
    logger,
    setup_logging,
    update_crawl_log,
    update_post_body,
    upsert_author,
)

BASE_URL = "https://www.tgb.cn"
DEFAULT_DELAY = 0.5


# -----------------------------------------------------------------------
# URL 解析
# -----------------------------------------------------------------------
def parse_blog_url(url_or_id: str) -> str:
    if url_or_id.isdigit():
        return url_or_id
    m = re.search(r"/blog/(\d+)", url_or_id)
    if m:
        return m.group(1)
    raise ValueError(f"Invalid blog URL or ID: {url_or_id}")


def build_blog_url(user_id: str, page: int = 1) -> str:
    if page == 1:
        return f"{BASE_URL}/blog/{user_id}"
    return f"{BASE_URL}/blog/{user_id}?page={page}"


# -----------------------------------------------------------------------
# HTML 解析
# -----------------------------------------------------------------------
def parse_article_list(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    articles = []

    for article_div in soup.find_all("div", class_="article_tittle"):
        try:
            title_tag = article_div.find("a", href=True)
            if not title_tag:
                continue

            href = title_tag.get("href", "")
            title = title_tag.get("title", title_tag.get_text(strip=True))
            article_url = f"{BASE_URL}/{href}" if href.startswith("a/") else f"{BASE_URL}/{href}"

            # 浏览/回复数
            llhf = article_div.find("div", class_="tittle_llhf")
            views_replies = llhf.get_text(strip=True) if llhf else ""

            # 发表时间
            fbdate = article_div.find("div", class_="tittle_fbshijian")
            pub_date = fbdate.get_text(strip=True) if fbdate else ""

            # 标签（原/精/红包）
            tags = []
            if article_div.find("span", class_="tittle_yuanchuang"):
                tags.append("原创")
            if article_div.find("span", class_="tittle_jinghua"):
                tags.append("精华")

            # 提取文章ID
            article_id = re.search(r"/a/([a-zA-Z0-9]+)", article_url)
            article_id = article_id.group(1) if article_id else ""

            # 解析 views/replies
            vr = re.findall(r"(\d+)", views_replies)
            views = int(vr[0]) if len(vr) > 0 else 0
            replies = int(vr[1]) if len(vr) > 1 else 0

            articles.append(
                {
                    "post_id": article_id,
                    "title": title,
                    "url": article_url,
                    "publish_date": pub_date,
                    "views": views,
                    "replies": replies,
                    "tags": json.dumps(tags, ensure_ascii=False),
                }
            )
        except Exception as e:
            logger.debug(f"Failed to parse article: {e}")
            continue

    return articles


def fetch_article_content(article_url: str) -> str:
    """抓取单篇文章的正文内容"""
    try:
        html = fetch(article_url, timeout=15)
        soup = BeautifulSoup(html, "html.parser")

        content = None
        for cls in ["stockDetailContent", "article-content", "content", "stock_detail"]:
            elem = soup.find(class_=cls)
            if elem:
                content = elem.get_text(separator="\n", strip=True)
                break

        if not content:
            for tag in soup.find_all(["div", "article"], {"id": re.compile(r"(content|body|main)")}):
                text = tag.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    content = text
                    break

        if not content:
            for tag in soup.find_all("div", class_=re.compile(r"(info|post|content)")):
                text = tag.get_text(separator="\n", strip=True)
                if len(text) > 200:
                    content = text[:3000]
                    break

        return content if content else ""
    except Exception as e:
        logger.warning(f"Failed to fetch article {article_url}: {e}")
        return ""


# -----------------------------------------------------------------------
# 爬取单博客
# -----------------------------------------------------------------------
def crawl_blog(
    blog_input: str,
    pages: int = 3,
    delay: float = DEFAULT_DELAY,
    fetch_content: bool = False,
    save_db: bool = False,
    incremental: bool = False,
) -> list:
    """
    爬取单个大V博客

    Args:
        blog_input: 博客URL或ID
        pages: 爬取页数
        delay: 请求间隔(秒)
        fetch_content: 是否抓取正文
        save_db: 是否保存到SQLite
        incremental: 是否增量爬取（只爬比上次更新的帖子）
    Returns:
        帖子列表
    """
    user_id = parse_blog_url(blog_input)
    blog_url = build_blog_url(user_id, 1)

    # 从 authors.json 获取博主名字
    authors_map = load_authors_json()
    author_info = authors_map.get(user_id, {})
    author_name = author_info.get("name", "")

    # 初始化数据库
    if save_db:
        init_db()

    conn = get_db() if save_db else None

    try:
        # upsert 作者记录
        if save_db and author_name:
            upsert_author(
                conn,
                {
                    "bid": user_id,
                    "name": author_name,
                    "blog_url": blog_url,
                    "fans": author_info.get("fans", 0),
                    "tier": author_info.get("tier", ""),
                    "source": author_info.get("source", ""),
                },
            )

        # 获取增量爬取时的时间分界
        cutoff_date = None
        if incremental:
            last = get_last_crawl("blog_posts", user_id)
            if last:
                cutoff_date = last.split()[0]  # 取日期部分
                logger.info(f"增量模式: 仅爬 {cutoff_date} 之后的帖子")

        all_articles = []
        total_pages = 0

        for page in range(1, pages + 1):
            url = build_blog_url(user_id, page)
            logger.info(f"Crawling page {page}/{pages}: {url}")

            try:
                html = fetch(url, headers=get_headers({"Referer": BASE_URL}), timeout=15)
            except Exception as e:
                logger.warning(f"Failed to fetch page {page}: {e}, skip")
                break

            articles = parse_article_list(html)

            if not articles:
                if page == 1:
                    logger.warning("No articles found on first page")
                else:
                    logger.info(f"Page {page} has no articles, stopping")
                break

            # 增量过滤
            if incremental and cutoff_date:
                before = len(articles)
                articles = [a for a in articles if a["publish_date"] >= cutoff_date]
                if articles:
                    logger.info(f"  增量: {before}条中{before - len(articles)}条已爬过，保留{len(articles)}条新帖")

            if incremental and not articles:
                logger.info(f"Page {page}: no new articles, stopping")
                break

            logger.info(f"  Found {len(articles)} articles")
            all_articles.extend(articles)
            total_pages = page

            if page < pages:
                time.sleep(delay + random.uniform(0, 0.3))

        if not all_articles:
            logger.error("No articles crawled!")
            return []

        logger.info(f"Total: {len(all_articles)} articles from {total_pages} pages")

        # 存入 SQLite
        if save_db:
            for art in all_articles:
                art["bid"] = user_id
            bulk_upsert_posts(conn, all_articles)
            update_crawl_log(conn, "blog_posts", user_id, len(all_articles))
            conn.commit()
            logger.info(f"Saved {len(all_articles)} posts to SQLite: {DB_PATH}")

        # 抓取正文内容
        if fetch_content and save_db and all_articles:
            logger.info(f"Fetching full content for {len(all_articles)} articles...")
            for i, art in enumerate(all_articles, 1):
                body = fetch_article_content(art["url"])
                if body:
                    update_post_body(conn, art["post_id"], body)
                    logger.debug(f"  [{i}/{len(all_articles)}] Fetched: {art['title'][:40]}")
                if i < len(all_articles):
                    time.sleep(delay + random.uniform(0, 0.3))
            conn.commit()
            logger.info(f"Updated body for {len(all_articles)} posts")

        # 打印摘要
        print(f"\n{'=' * 60}")
        print(f"大V博客用户ID: {user_id}  ({author_name or 'unknown'})")
        print(f"抓取页数: {total_pages}")
        print(f"帖子总数: {len(all_articles)}")
        print(f"{'=' * 60}")
        print("\n前5条帖子:")
        for i, art in enumerate(all_articles[:5], 1):
            tags = json.loads(art["tags"]) if art["tags"] else []
            tag_str = "[" + "/".join(tags) + "]" if tags else ""
            print(
                f"  {i}. [{art['views']:,}阅/{art['replies']}回复] {art['publish_date']} {tag_str} {art['title'][:50]}"
            )

        return all_articles

    finally:
        if conn:
            conn.close()


# -----------------------------------------------------------------------
# 批量爬取所有已知大V
# -----------------------------------------------------------------------
def crawl_all_authors(
    pages: int = 3,
    delay: float = DEFAULT_DELAY,
    fetch_content: bool = False,
    save_db: bool = False,
    incremental: bool = False,
):
    """爬取所有已知大V的博客"""
    authors_map = load_authors_json()
    if not authors_map:
        logger.error("No authors found in references/tgb_blog_authors.json")
        return

    if save_db:
        init_db()

    total = len(authors_map)
    results = []
    errors = []

    for i, (bid, info) in enumerate(authors_map.items(), 1):
        name = info.get("name", "unknown")
        logger.info(f"[{i}/{total}] === 爬取 {name} ({bid}) ===")

        try:
            articles = crawl_blog(
                bid, pages=pages, delay=delay, fetch_content=fetch_content, save_db=save_db, incremental=incremental
            )
            results.append({"bid": bid, "name": name, "count": len(articles)})
        except Exception as e:
            logger.error(f"Failed to crawl {bid} ({name}): {e}")
            errors.append({"bid": bid, "name": name, "error": str(e)})

        if i < total:
            time.sleep(delay + random.uniform(0, 0.5))

    # 汇总
    logger.info(f"\n{'=' * 60}")
    logger.info(f"批量爬取完成: 成功 {len(results)}/{total}, 失败 {len(errors)}")
    for r in results:
        logger.info(f"  {r['name']}: {r['count']} posts")
    if errors:
        logger.warning("失败列表:")
        for e in errors:
            logger.warning(f"  {e['name']} ({e['bid']}): {e['error']}")

    return results, errors


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Crawl blog posts from 淘股吧 (tgb.cn) big-V blogs.")
    parser.add_argument("--blog-url", help="Blog URL, e.g. https://www.tgb.cn/blog/7105646")
    parser.add_argument("--blog-id", help="Blog user ID, e.g. 7105646")
    parser.add_argument("--pages", type=int, default=3, help="Pages to crawl per blog (default: 3)")
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY, help=f"Request delay in seconds (default: {DEFAULT_DELAY})"
    )
    parser.add_argument("--fetch-content", action="store_true", help="Also fetch full article body (slow)")
    parser.add_argument("--save-db", action="store_true", help="Save results to SQLite database")
    parser.add_argument(
        "--incremental", action="store_true", help="Only crawl posts newer than last crawl (requires --save-db)"
    )
    parser.add_argument(
        "--all-authors", action="store_true", help="Crawl all known authors from references/tgb_blog_authors.json"
    )
    parser.add_argument("--out-dir", default=str(DATA_DIR), help="Output directory")
    parser.add_argument("--log-file", help="Log file path")

    args = parser.parse_args()

    # 日志
    setup_logging(log_file=args.log_file)

    # 验证参数
    if args.incremental and not args.save_db:
        logger.warning("--incremental requires --save-db, enabling --save-db")
        args.save_db = True

    if not args.blog_url and not args.blog_id and not args.all_authors:
        parser.print_help()
        sys.exit(1)

    if args.all_authors:
        crawl_all_authors(
            pages=args.pages,
            delay=args.delay,
            fetch_content=args.fetch_content,
            save_db=args.save_db,
            incremental=args.incremental,
        )
    else:
        blog_input = args.blog_url or args.blog_id
        crawl_blog(
            blog_input,
            pages=args.pages,
            delay=args.delay,
            fetch_content=args.fetch_content,
            save_db=args.save_db,
            incremental=args.incremental,
        )


if __name__ == "__main__":
    main()
