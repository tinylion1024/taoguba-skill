#!/usr/bin/env python3
"""
tgb_spider.py
淘股吧热门文章（点赞榜）爬虫

支持 SQLite 持久化和增量爬取。
接入 common.py 作为可靠爬虫基础设施。

Usage:
    python scripts/tgb_spider.py --s-dt "04-25 00:00" --e-dt "04-27 00:00" --search-page 1
    python scripts/tgb_spider.py --s-dt "04-25 00:00" --e-dt "04-27 00:00" --search-page 1 --save-db
    python scripts/tgb_spider.py --s-dt "04-25 00:00" --e-dt "04-27 00:00" --search-page 1 --save-db --incremental
"""

import argparse
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from common import (
    DATA_DIR,
    DB_PATH,
    fetch,
    get_db,
    get_headers,
    get_last_crawl,
    init_db,
    logger,
    setup_logging,
    update_crawl_log,
)

# ---------------------------------------------------------------------------
# HTML 解析
# ---------------------------------------------------------------------------

def get_article_infos(base_url: str, s_dt: str, e_dt: str, search_page: int, delay: float = 0.5):
    """
    从列表页抓取文章信息（仅列表，不含正文）。

    Args:
        base_url:  列表页基础URL（不含分页）
        s_dt:      开始时间，格式 MM-DD HH:MM
        e_dt:      结束时间，格式 MM-DD HH:MM
        search_page: 抓取页数
        delay:     请求间隔（秒）

    Returns:
        list[dict]，每项含 keys: title, author_name, url, publish_dt, article_id
    """
    rt_infos = []
    for page in range(1, search_page + 1):
        time.sleep(delay)
        list_url = f"{base_url}/{page}-1"
        try:
            html = fetch(list_url, headers=get_headers({"Referer": base_url}), timeout=15)
        except Exception as e:
            logger.warning("列表页 fetch 失败 [%s]: %s", list_url, e)
            continue

        soup = BeautifulSoup(html, "lxml")
        divs = soup.find_all("div", class_="Nbbs-tiezi-lists")

        for div in divs:
            try:
                dt = div.find("div", class_="left middle-list-post").get_text(strip=True)
                href = div.find("a")["href"]
                title = div.find("a")["title"]
                author = div.find("div", class_="left middle-list-user cblue cursor overhide").get_text(
                    strip=True
                )

                if not (s_dt <= dt <= e_dt):
                    continue

                # 提取 article_id（URL 形如 /a/xxxx）
                m = re.search(r"/a/([a-zA-Z0-9]+)", href)
                article_id = m.group(1) if m else href

                rt_infos.append(
                    {
                        "title": f"《{title}》",
                        "author_name": author,
                        "url": urljoin(base_url, href),
                        "publish_dt": dt,
                        "article_id": article_id,
                    }
                )
            except (AttributeError, KeyError) as e:
                logger.debug("解析单条文章信息失败: %s", e)

    return rt_infos


def fetch_article_text(infos: list[dict], delay: float = 0.5) -> list[dict]:
    """
    批量抓取正文内容，追加到 infos 列表每项的 body 字段。

    Returns:
        更新后的 infos 列表（每项新增 body 字段）
    """
    for idx, info in enumerate(infos, 1):
        time.sleep(delay)
        try:
            html = fetch(info["url"], headers=get_headers({"Referer": "https://www.tgb.cn/"}), timeout=15)
        except Exception as e:
            logger.warning("正文页 fetch 失败 [%s]: %s", info["url"], e)
            info["body"] = ""
            continue

        soup = BeautifulSoup(html, "html.parser")
        content_div = soup.find("div", class_="article-text p_coten")
        if not content_div:
            logger.debug("未找到正文区域: %s", info["url"])
            info["body"] = ""
            continue

        for tag in content_div(["script", "style"]):
            tag.extract()

        text = re.sub(r"\([^)]*\)|\n|\t", "", content_div.get_text(strip=True))
        info["body"] = text
        logger.info("第%d篇文章正文处理完毕: %s", idx, info["title"][:30])

    return infos


# ---------------------------------------------------------------------------
# SQLite 读写
# ---------------------------------------------------------------------------

def save_hot_articles_to_db(
    articles: list[dict],
    s_dt: str,
    e_dt: str,
    incremental: bool = False,
    db_path: str = None,
):
    """
    将热门文章写入 hot_articles 表。

    Args:
        articles:  文章列表（含 article_id/title/author_name/url/publish_dt/body）
        s_dt:      爬取范围开始
        e_dt:      爬取范围结束
        incremental: 是否增量（基于 article_id 去重）
        db_path: 可选，指定数据库路径（测试用）
    """
    init_db(db_path)
    conn = get_db(db_path)
    new_count = 0

    try:
        for art in articles:
            # 增量模式：已存在的 article_id 跳过
            if incremental:
                existing = conn.execute(
                    "SELECT id FROM hot_articles WHERE article_id = ?",
                    (art["article_id"],),
                ).fetchone()
                if existing:
                    logger.debug("Skipping existing article_id: %s", art["article_id"])
                    continue

            conn.execute(
                """
                INSERT INTO hot_articles
                    (article_id, title, author_name, url, publish_dt, s_dt, e_dt, body)
                VALUES (:article_id, :title, :author_name, :url, :publish_dt, :s_dt, :e_dt, :body)
                ON CONFLICT(article_id) DO UPDATE SET
                    title=excluded.title,
                    author_name=excluded.author_name,
                    publish_dt=excluded.publish_dt,
                    body=excluded.body
                """,
                {
                    "article_id": art["article_id"],
                    "title": art["title"],
                    "author_name": art["author_name"],
                    "url": art["url"],
                    "publish_dt": art["publish_dt"],
                    "s_dt": s_dt,
                    "e_dt": e_dt,
                    "body": art.get("body", ""),
                },
            )
            new_count += 1

        update_crawl_log(conn, "hot_articles", "hot", new_count)
        conn.commit()
        logger.info(
            "Saved %d new articles to SQLite (total %d, skipped duplicates: %d): %s",
            new_count,
            len(articles),
            len(articles) - new_count,
            DB_PATH,
        )
    finally:
        conn.close()


def read_hot_articles_from_db(s_dt: str = None, e_dt: str = None, limit: int = 100, db_path: str = None) -> list[dict]:
    """从数据库读取热门文章（可选按时间范围过滤）"""
    init_db(db_path)
    conn = get_db(db_path)
    try:
        query = "SELECT * FROM hot_articles"
        params = []
        where_parts = []
        if s_dt:
            where_parts.append("s_dt >= ?")
            params.append(s_dt)
        if e_dt:
            where_parts.append("e_dt <= ?")
            params.append(e_dt)
        if where_parts:
            query += " WHERE " + " AND ".join(where_parts)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 文件输出
# ---------------------------------------------------------------------------

def write_to_txt(text: str, file_path: Path):
    """写入文本文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file_path.write_text(text, encoding="utf-8")
        logger.info("文本已写入 %s", file_path)
    except OSError as e:
        logger.error("写入文件失败: %s", e)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="淘股吧热门文章（点赞榜）抓取")
    parser.add_argument(
        "--base-url", default="https://www.tgb.cn/dianzan", help="列表页基础URL（不含分页）"
    )
    parser.add_argument("--s-dt", required=True, help="开始日期时间，格式 MM-DD HH:MM")
    parser.add_argument("--e-dt", required=True, help="结束日期时间，格式 MM-DD HH:MM")
    parser.add_argument("--search-page", type=int, default=5, help="要抓取的列表页页数")
    parser.add_argument("--out-dir", default=str(DATA_DIR), help="输出根目录")
    parser.add_argument("--delay", type=float, default=0.5, help="请求间隔秒数（默认0.5）")
    parser.add_argument("--save-db", action="store_true", help="Save results to SQLite database")
    parser.add_argument(
        "--incremental", action="store_true", help="Only crawl articles not in DB (requires --save-db)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 日志
    setup_logging()

    date_part = datetime.now().strftime("%m-%d")
    corpus_path = Path(args.out_dir) / "corpus"
    corpus_path.mkdir(parents=True, exist_ok=True)
    corpus_file = corpus_path / f"{date_part}-tgb-corpus.txt"
    list_file = corpus_path / f"{date_part}-tgb-list.txt"

    # 1. 增量模式：检查上次爬取时间
    if args.incremental and args.save_db:
        last = get_last_crawl("hot_articles", "hot")
        if last:
            logger.info("增量模式: 检测到上次爬取时间 %s，仅爬取新文章", last)

    # 2. 抓取文章列表
    infos = get_article_infos(
        args.base_url, args.s_dt, args.e_dt, args.search_page, delay=args.delay
    )

    # 按 article_id 去重（列表页可能有重复）
    seen = set()
    unique_infos = []
    for info in infos:
        if info["article_id"] not in seen:
            seen.add(info["article_id"])
            unique_infos.append(info)
    infos = unique_infos

    logger.info("共获取 %d 条文章（去重后）", len(infos))

    # 同时保存文章列表信息
    with open(list_file, "w", encoding="utf-8") as f:
        for info in infos:
            f.write(f"{info['title']} - {info['author_name']}\n{info['url']}\n\n")
    logger.info("文章列表已写入 %s", list_file)

    if len(infos) == 0:
        logger.warning("未获取到符合日期范围的文章，程序结束")
        return

    # 3. 抓取正文
    infos = fetch_article_text(infos, delay=args.delay)
    bodies = [info.get("body", "") for info in infos if info.get("body")]
    text = "\n".join(bodies)

    if not text.strip():
        logger.warning("未抓取到任何正文内容，程序结束")
        return
    write_to_txt(text, corpus_file)

    # 4. 可选：写入 SQLite
    if args.save_db:
        # 确保正文已追加到 infos
        save_hot_articles_to_db(infos, args.s_dt, args.e_dt, incremental=args.incremental)

    logger.info("完成！")


if __name__ == "__main__":
    main()
