"""test_spider.py - 热门文章爬虫解析函数测试"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from tgb_spider import (
    fetch_article_text,
    get_article_infos,
    read_hot_articles_from_db,
    save_hot_articles_to_db,
)


# ---------------------------------------------------------------------------
# get_article_infos HTML 解析测试
# ---------------------------------------------------------------------------

class TestGetArticleInfos:
    """测试 get_article_infos 的 HTML 解析逻辑（mock fetch）"""

    def _make_html(self, divs_html: str) -> str:
        return f"<html><body>{divs_html}</body></html>"

    @patch("tgb_spider.fetch")
    def test_parses_single_article(self, mock_fetch):
        html = self._make_html(
            '<div class="Nbbs-tiezi-lists">'
            '<div class="left middle-list-post">04-25 10:00</div>'
            '<a href="/a/abc123" title="测试文章标题">测试文章标题</a>'
            '<div class="left middle-list-user cblue cursor overhide">作者甲</div>'
            "</div>"
        )
        mock_fetch.return_value = html

        infos = get_article_infos("https://www.tgb.cn/dianzan", "04-25 00:00", "04-26 00:00", 1, delay=0)
        assert len(infos) == 1
        assert infos[0]["article_id"] == "abc123"
        assert infos[0]["title"] == "《测试文章标题》"
        assert infos[0]["author_name"] == "作者甲"
        assert "abc123" in infos[0]["url"]

    @patch("tgb_spider.fetch")
    def test_parses_multiple_articles(self, mock_fetch):
        html = self._make_html(
            '<div class="Nbbs-tiezi-lists">'
            '<div class="left middle-list-post">04-25 10:00</div>'
            '<a href="/a/id1" title="文章1">文章1</a>'
            '<div class="left middle-list-user cblue cursor overhide">作者A</div>'
            "</div>"
            '<div class="Nbbs-tiezi-lists">'
            '<div class="left middle-list-post">04-25 12:00</div>'
            '<a href="/a/id2" title="文章2">文章2</a>'
            '<div class="left middle-list-user cblue cursor overhide">作者B</div>'
            "</div>"
        )
        mock_fetch.return_value = html

        infos = get_article_infos("https://www.tgb.cn/dianzan", "04-25 00:00", "04-26 00:00", 1, delay=0)
        assert len(infos) == 2
        ids = {info["article_id"] for info in infos}
        assert ids == {"id1", "id2"}

    @patch("tgb_spider.fetch")
    def test_respects_date_range(self, mock_fetch):
        html = self._make_html(
            '<div class="Nbbs-tiezi-lists">'
            '<div class="left middle-list-post">04-20 10:00</div>'
            '<a href="/a/old1" title="旧文章">旧文章</a>'
            '<div class="left middle-list-user cblue cursor overhide">作者</div>'
            "</div>"
            '<div class="Nbbs-tiezi-lists">'
            '<div class="left middle-list-post">04-25 10:00</div>'
            '<a href="/a/new1" title="新文章">新文章</a>'
            '<div class="left middle-list-user cblue cursor overhide">作者</div>'
            "</div>"
        )
        mock_fetch.return_value = html

        infos = get_article_infos("https://www.tgb.cn/dianzan", "04-25 00:00", "04-26 00:00", 1, delay=0)
        assert len(infos) == 1
        assert infos[0]["article_id"] == "new1"

    @patch("tgb_spider.fetch")
    def test_skips_malformed_divs(self, mock_fetch):
        """缺少必要字段的 div 不会导致整页解析失败"""
        html = self._make_html(
            '<div class="Nbbs-tiezi-lists">'
            '<div class="left middle-list-post">04-25 10:00</div>'
            '<a href="/a/good1" title="好文章">好文章</a>'
            '<div class="left middle-list-user cblue cursor overhide">作者</div>'
            "</div>"
            '<div class="Nbbs-tiezi-lists">'
            '<a href="/a/bad1">没有日期</a>'
            "</div>"
        )
        mock_fetch.return_value = html

        infos = get_article_infos("https://www.tgb.cn/dianzan", "04-25 00:00", "04-26 00:00", 1, delay=0)
        assert len(infos) == 1
        assert infos[0]["article_id"] == "good1"

    @patch("tgb_spider.fetch")
    def test_handles_fetch_failure_gracefully(self, mock_fetch):
        """fetch 抛异常时该页被跳过，不影响其他页"""
        def side_effect(url, **kwargs):
            if "/2-1" in str(url):
                raise RuntimeError("network error")
            return self._make_html(
                '<div class="Nbbs-tiezi-lists">'
                '<div class="left middle-list-post">04-25 10:00</div>'
                '<a href="/a/ok1" title="OK">OK</a>'
                '<div class="left middle-list-user cblue cursor overhide">作者</div>'
                "</div>"
            )

        mock_fetch.side_effect = side_effect

        infos = get_article_infos("https://www.tgb.cn/dianzan", "04-25 00:00", "04-26 00:00", 2, delay=0)
        # 第一页成功，第二页失败
        assert len(infos) == 1
        assert infos[0]["article_id"] == "ok1"


# ---------------------------------------------------------------------------
# fetch_article_text 测试（mock fetch）
# ---------------------------------------------------------------------------

class TestFetchArticleText:
    @patch("tgb_spider.fetch")
    def test_extracts_body_text(self, mock_fetch):
        mock_fetch.return_value = """
        <html><body>
        <div class="article-text p_coten">
            <p>这是正文第一段</p>
            <p>这是正文第二段</p>
            <script>var x = 1;</script>
        </div>
        </body></html>
        """
        infos = [{"url": "https://www.tgb.cn/a/abc123", "title": "测试"}]
        result = fetch_article_text(infos, delay=0)

        assert "正文" in result[0]["body"]

    @patch("tgb_spider.fetch")
    def test_handles_missing_content_div(self, mock_fetch):
        mock_fetch.return_value = "<html><body><p>No content div here</p></body></html>"
        infos = [{"url": "https://www.tgb.cn/a/abc", "title": "Test"}]
        result = fetch_article_text(infos, delay=0)
        assert result[0]["body"] == ""


# ---------------------------------------------------------------------------
# SQLite 写入/读取测试
# ---------------------------------------------------------------------------

class TestSQLite:
    @pytest.fixture
    def temp_db(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        import os
        os.close(fd)
        # 初始化数据库schema
        import sqlite3
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # 创建表（简化版，足够测试）
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS crawl_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crawl_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            last_crawl TEXT NOT NULL,
            records INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success'
        );
        CREATE TABLE IF NOT EXISTS hot_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id TEXT UNIQUE,
            title TEXT,
            author_name TEXT,
            url TEXT,
            publish_dt TEXT,
            s_dt TEXT,
            e_dt TEXT,
            body TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        conn.commit()
        conn.close()
        yield path
        import os
        os.unlink(path)

    def test_save_and_read(self, temp_db):
        articles = [
            {
                "article_id": "art001",
                "title": "《测试文章A》",
                "author_name": "作者A",
                "url": "https://www.tgb.cn/a/art001",
                "publish_dt": "04-25 10:00",
                "body": "这是正文内容A",
            },
            {
                "article_id": "art002",
                "title": "《测试文章B》",
                "author_name": "作者B",
                "url": "https://www.tgb.cn/a/art002",
                "publish_dt": "04-25 11:00",
                "body": "这是正文内容B",
            },
        ]
        save_hot_articles_to_db(articles, "04-25 00:00", "04-26 00:00", incremental=False, db_path=temp_db)

        rows = read_hot_articles_from_db(limit=10, db_path=temp_db)
        assert len(rows) == 2
        ids = {r["article_id"] for r in rows}
        assert ids == {"art001", "art002"}

    def test_incremental_skips_existing(self, temp_db):
        """增量模式下，已存在的 article_id 被跳过，不会更新"""
        articles1 = [
            {
                "article_id": "art001",
                "title": "《文章1》",
                "author_name": "作者",
                "url": "https://www.tgb.cn/a/art001",
                "publish_dt": "04-25 10:00",
                "body": "Body 1",
            }
        ]
        # 第一次写入（非增量，ON CONFLICT DO UPDATE）
        save_hot_articles_to_db(articles1, "04-25 00:00", "04-26 00:00", incremental=False, db_path=temp_db)

        # 第二次以增量模式写入同样的文章 → 跳过
        articles2 = [
            {
                "article_id": "art001",
                "title": "《文章1 更新》",
                "author_name": "作者",
                "url": "https://www.tgb.cn/a/art001",
                "publish_dt": "04-25 10:00",
                "body": "Body 1 Updated",
            }
        ]
        save_hot_articles_to_db(articles2, "04-25 00:00", "04-26 00:00", incremental=True, db_path=temp_db)

        rows = read_hot_articles_from_db(limit=10, db_path=temp_db)
        # 增量模式跳过已存在的 article_id，body 保持第一次的值
        assert len(rows) == 1
        assert rows[0]["body"] == "Body 1"

    def test_non_incremental_updates_existing(self, temp_db):
        """非增量模式下，ON CONFLICT DO UPDATE 会更新已存在记录"""
        articles1 = [
            {
                "article_id": "art001",
                "title": "《文章1》",
                "author_name": "作者",
                "url": "https://www.tgb.cn/a/art001",
                "publish_dt": "04-25 10:00",
                "body": "Body 1",
            }
        ]
        save_hot_articles_to_db(articles1, "04-25 00:00", "04-26 00:00", incremental=False, db_path=temp_db)

        # 非增量模式再次插入相同 article_id → ON CONFLICT DO UPDATE
        articles2 = [
            {
                "article_id": "art001",
                "title": "《文章1 已更新》",
                "author_name": "作者",
                "url": "https://www.tgb.cn/a/art001",
                "publish_dt": "04-25 10:00",
                "body": "Body 1 Updated",
            }
        ]
        save_hot_articles_to_db(articles2, "04-25 00:00", "04-26 00:00", incremental=False, db_path=temp_db)

        rows = read_hot_articles_from_db(limit=10, db_path=temp_db)
        assert len(rows) == 1
        # ON CONFLICT DO UPDATE 更新了 title 和 body
        assert rows[0]["title"] == "《文章1 已更新》"
        assert rows[0]["body"] == "Body 1 Updated"
