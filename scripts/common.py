"""
common.py - 淘股吧爬虫通用工具
"""
import os
import re
import json
import time
import random
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from functools import wraps
from typing import Optional, List, Dict, Any

# ============ 路径配置 ============
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "tgb.db"

# ============ 日志配置 ============
def setup_logging(log_file: str = None, level=logging.INFO):
    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level, format=log_format, handlers=handlers)

logger = logging.getLogger(__name__)

# ============ UA轮换 ============
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0",
]

def get_headers(extra: dict = None) -> dict:
    ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Referer": "https://www.tgb.cn/",
    }
    if extra:
        headers.update(extra)
    return headers

# ============ 重试装饰器 ============
def retry(max_attempts: int = 3, base_delay: float = 1.0, backoff: float = 2.0,
          exceptions=(Exception,)):
    """指数退避重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        logger.error(f"[{func.__name__}] 最终失败: {e}")
                        raise
                    delay = base_delay * (backoff ** attempt)
                    logger.warning(f"[{func.__name__}] 第{attempt+1}次失败: {e}, "
                                   f"{delay:.1f}s后重试...")
                    time.sleep(delay)
        return wrapper
    return decorator

# ============ HTTP请求 ============
import requests

@retry(max_attempts=3, base_delay=1.0)
def fetch(url: str, headers: dict = None, timeout: int = 30,
          encoding: str = "utf-8") -> str:
    """带重试的HTTP GET"""
    h = get_headers() if headers is None else headers
    resp = requests.get(url, headers=h, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = encoding
    return resp.text

@retry(max_attempts=3, base_delay=1.0)
def fetch_raw(url: str, headers: dict = None, timeout: int = 30) -> bytes:
    """带重试的HTTP GET（返回原始字节）"""
    h = get_headers() if headers is None else headers
    resp = requests.get(url, headers=h, timeout=timeout)
    resp.raise_for_status()
    return resp.content

# ============ SQLite 数据库 ============
SCHEMA_SQL = """
-- authors: 大V博主表
CREATE TABLE IF NOT EXISTS authors (
    bid         TEXT PRIMARY KEY,     -- 博主ID
    name        TEXT NOT NULL,        -- 博主名字
    blog_url    TEXT,                 -- 博客URL
    fans        INTEGER DEFAULT 0,    -- 粉丝数
    tier        TEXT,                 -- 评级 S/A/B/C/D/E/未评级
    source      TEXT,                 -- 来源
    post_count  INTEGER DEFAULT 0,    -- 发帖总数
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- posts: 帖子表
CREATE TABLE IF NOT EXISTS posts (
    post_id     TEXT PRIMARY KEY,     -- 帖子ID (如 2rjdXpk0pCK)
    bid         TEXT NOT NULL,        -- 博主ID (FK)
    title       TEXT,                 -- 标题
    url         TEXT,                 -- 帖子URL
    publish_date TEXT,                -- 发表时间 YYYY-MM-DD
    views       INTEGER DEFAULT 0,   -- 浏览数
    replies     INTEGER DEFAULT 0,    -- 回复数
    tags        TEXT,                 -- 标签 JSON: ["原创","精华","红包"]
    is_content_fetched INTEGER DEFAULT 0,  -- 是否已抓正文
    body        TEXT,                 -- 正文内容
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (bid) REFERENCES authors(bid)
);

-- stock_comments: 股票讨论评论表
CREATE TABLE IF NOT EXISTS stock_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code  TEXT NOT NULL,       -- 股票代码 (sz300750)
    author_name TEXT,
    author_bid  TEXT,
    content     TEXT,                 -- 评论内容
    post_url    TEXT,
    timestamp   TEXT,                -- 发布时间
    likes       INTEGER DEFAULT 0,   -- 点赞数
    created_at  TEXT DEFAULT (datetime('now'))
);

-- crawl_log: 爬取记录（增量爬取用）
CREATE TABLE IF NOT EXISTS crawl_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_type  TEXT NOT NULL,       -- 'blog_posts', 'stock_comments'
    target_id   TEXT NOT NULL,       -- bid 或 stock_code
    last_crawl  TEXT NOT NULL,       -- 最后爬取时间
    records     INTEGER DEFAULT 0,    -- 本次抓取记录数
    status      TEXT DEFAULT 'success'
);

-- indexes
CREATE INDEX IF NOT EXISTS idx_posts_bid        ON posts(bid);
CREATE INDEX IF NOT EXISTS idx_posts_pubdate    ON posts(publish_date);
CREATE INDEX IF NOT EXISTS idx_posts_fetched    ON posts(is_content_fetched);
CREATE INDEX IF NOT EXISTS idx_crawl_target      ON crawl_log(crawl_type, target_id);
CREATE INDEX IF NOT EXISTS idx_comments_stock    ON stock_comments(stock_code);
"""

def get_db(db_path: str = None) -> sqlite3.Connection:
    """获取数据库连接（WAL模式，外键约束）"""
    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str = None):
    """初始化数据库"""
    conn = get_db(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()

def dict_from_row(row: sqlite3.Row) -> dict:
    return dict(row) if row else {}

# ============ upsert helpers ============
def upsert_author(conn: sqlite3.Connection, author: Dict[str, Any]):
    conn.execute("""
        INSERT INTO authors (bid, name, blog_url, fans, tier, source, updated_at)
        VALUES (:bid, :name, :blog_url, :fans, :tier, :source, datetime('now'))
        ON CONFLICT(bid) DO UPDATE SET
            name = excluded.name,
            blog_url = excluded.blog_url,
            fans = COALESCE(excluded.fans, authors.fans),
            tier = COALESCE(excluded.tier, authors.tier),
            source = COALESCE(excluded.source, authors.source),
            updated_at = datetime('now')
    """, author)

def upsert_post(conn: sqlite3.Connection, post: Dict[str, Any]):
    conn.execute("""
        INSERT INTO posts (post_id, bid, title, url, publish_date, views, replies, tags, updated_at)
        VALUES (:post_id, :bid, :title, :url, :publish_date, :views, :replies, :tags, datetime('now'))
        ON CONFLICT(post_id) DO UPDATE SET
            title = excluded.title,
            url = excluded.url,
            publish_date = COALESCE(excluded.publish_date, posts.publish_date),
            views = excluded.views,
            replies = excluded.replies,
            tags = excluded.tags,
            updated_at = datetime('now')
    """, post)

def update_post_body(conn: sqlite3.Connection, post_id: str, body: str):
    conn.execute("""
        UPDATE posts SET body = ?, is_content_fetched = 1, updated_at = datetime('now')
        WHERE post_id = ?
    """, (body, post_id))

def bulk_upsert_posts(conn: sqlite3.Connection, posts: List[Dict[str, Any]]):
    for p in posts:
        upsert_post(conn, p)

def update_crawl_log(conn: sqlite3.Connection, crawl_type: str, target_id: str,
                     records: int, status: str = "success"):
    conn.execute("""
        INSERT INTO crawl_log (crawl_type, target_id, last_crawl, records, status)
        VALUES (?, ?, datetime('now'), ?, ?)
    """, (crawl_type, target_id, records, status))

def get_last_crawl(crawl_type: str, target_id: str, db_path: str = None) -> Optional[str]:
    """获取某目标最后爬取时间（用于增量爬取）"""
    conn = get_db(db_path)
    row = conn.execute("""
        SELECT last_crawl FROM crawl_log
        WHERE crawl_type = ? AND target_id = ? AND status = 'success'
        ORDER BY last_crawl DESC LIMIT 1
    """, (crawl_type, target_id)).fetchone()
    conn.close()
    return row["last_crawl"] if row else None

# ============ authors.json 加载 ============
def load_authors_json(path: str = None) -> Dict[str, dict]:
    """加载 references/tgb_blog_authors.json"""
    if path is None:
        path = BASE_DIR / "references" / "tgb_blog_authors.json"
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # 支持 authors 或 authors{} 两种格式
    if "authors" in data:
        return data["authors"]
    # 去掉顶级comment字段，只保留作者数据
    return {k: v for k, v in data.items() if k not in ("_comment", "_sources", "_total_authors", "_tier_criteria")}

# ============ 导出CSV ============
def to_csv(data: List[dict], path: str):
    if not data:
        return
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
