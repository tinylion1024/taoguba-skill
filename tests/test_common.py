"""test_common.py - 通用工具函数测试"""

import os

# 确保 scripts 目录在路径中
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from common import (
    bulk_upsert_posts,
    fetch,
    get_db,
    get_headers,
    get_last_crawl,
    init_db,
    load_authors_json,
    retry,
    to_csv,
    update_crawl_log,
    update_post_body,
    upsert_author,
    upsert_post,
)


class TestGetHeaders:
    def test_get_headers_returns_dict(self):
        headers = get_headers()
        assert isinstance(headers, dict)
        assert "User-Agent" in headers
        assert "Accept" in headers

    def test_get_headers_includes_referer(self):
        headers = get_headers()
        assert headers["Referer"] == "https://www.tgb.cn/"

    def test_get_headers_with_extra(self):
        headers = get_headers(extra={"X-Custom": "value"})
        assert headers["X-Custom"] == "value"


class TestRetry:
    def test_retry_success_first_attempt(self):
        @retry(max_attempts=3)
        def success_func():
            return "ok"

        result = success_func()
        assert result == "ok"

    def test_retry_fails_after_max_attempts(self):
        @retry(max_attempts=3, base_delay=0.01)
        def fail_func():
            raise ValueError("test error")

        with pytest.raises(ValueError):
            fail_func()

    def test_retry_succeeds_on_second_attempt(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def eventually_success():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first fail")
            return "ok"

        result = eventually_success()
        assert result == "ok"
        assert call_count == 2


class TestFetch:
    @patch("common.requests.get")
    def test_fetch_returns_html(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>test</html>"
        mock_response.encoding = "utf-8"
        mock_get.return_value = mock_response

        result = fetch("https://example.com")
        assert result == "<html>test</html>"

    @patch("common.requests.get")
    def test_fetch_with_custom_headers(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>test</html>"
        mock_response.encoding = "utf-8"
        mock_get.return_value = mock_response

        custom_headers = {"User-Agent": "TestAgent"}
        fetch("https://example.com", headers=custom_headers)
        mock_get.assert_called_once()


class TestDatabase:
    @pytest.fixture
    def temp_db(self):
        """创建临时数据库"""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(path)
        yield path
        os.unlink(path)

    def test_init_db_creates_tables(self, temp_db):
        conn = get_db(temp_db)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "authors" in tables
        assert "posts" in tables
        assert "stock_comments" in tables
        assert "crawl_log" in tables
        conn.close()

    def test_upsert_author_insert(self, temp_db):
        conn = get_db(temp_db)
        upsert_author(
            conn,
            {
                "bid": "123",
                "name": "Test Author",
                "blog_url": "https://example.com",
                "fans": "100万",
                "tier": "S",
                "source": "manual",
            },
        )
        conn.commit()

        row = conn.execute("SELECT * FROM authors WHERE bid='123'").fetchone()
        assert row is not None
        assert row["name"] == "Test Author"
        assert row["fans"] == "100万"
        conn.close()

    def test_upsert_author_update(self, temp_db):
        conn = get_db(temp_db)

        # 首次插入
        upsert_author(
            conn,
            {
                "bid": "123",
                "name": "Original Name",
                "blog_url": "https://example.com",
                "fans": "50万",
                "tier": "A",
                "source": "test",
            },
        )
        conn.commit()

        # 再次插入（更新）
        upsert_author(
            conn,
            {
                "bid": "123",
                "name": "Updated Name",
                "blog_url": "https://example.com",
                "fans": "100万",
                "tier": "S",
                "source": "test",
            },
        )
        conn.commit()

        row = conn.execute("SELECT * FROM authors WHERE bid='123'").fetchone()
        assert row["name"] == "Updated Name"
        assert row["fans"] == "100万"
        conn.close()

    def test_upsert_post(self, temp_db):
        conn = get_db(temp_db)
        # posts 表有外键约束，需要先有 author
        upsert_author(
            conn,
            {
                "bid": "456",
                "name": "Test Author",
                "blog_url": "https://example.com",
                "fans": "0",
                "tier": "B",
                "source": "test",
            },
        )
        conn.commit()

        upsert_post(
            conn,
            {
                "post_id": "abc123",
                "bid": "456",
                "title": "Test Post",
                "url": "https://example.com/a/abc123",
                "publish_date": "2024-01-01",
                "views": 100,
                "replies": 10,
                "tags": '["原创"]',
            },
        )
        conn.commit()

        row = conn.execute("SELECT * FROM posts WHERE post_id='abc123'").fetchone()
        assert row is not None
        assert row["title"] == "Test Post"
        assert row["views"] == 100
        conn.close()

    def test_update_post_body(self, temp_db):
        conn = get_db(temp_db)

        # 先插入 author
        upsert_author(
            conn,
            {
                "bid": "456",
                "name": "Test Author",
                "blog_url": "https://example.com",
                "fans": "0",
                "tier": "B",
                "source": "test",
            },
        )
        conn.commit()

        # 先插入帖子
        upsert_post(
            conn,
            {
                "post_id": "abc123",
                "bid": "456",
                "title": "Test",
                "url": "https://example.com",
                "publish_date": "2024-01-01",
                "views": 0,
                "replies": 0,
                "tags": "[]",
            },
        )
        conn.commit()

        # 更新正文
        update_post_body(conn, "abc123", "这是正文内容")
        conn.commit()

        row = conn.execute("SELECT * FROM posts WHERE post_id='abc123'").fetchone()
        assert row["body"] == "这是正文内容"
        assert row["is_content_fetched"] == 1
        conn.close()

    def test_bulk_upsert_posts(self, temp_db):
        conn = get_db(temp_db)
        # 先插入 author
        upsert_author(
            conn,
            {
                "bid": "b1",
                "name": "Author 1",
                "blog_url": "https://example.com",
                "fans": "0",
                "tier": "B",
                "source": "test",
            },
        )
        conn.commit()

        posts = [
            {
                "post_id": "p1",
                "bid": "b1",
                "title": "Post 1",
                "url": "https://example.com/1",
                "publish_date": "2024-01-01",
                "views": 10,
                "replies": 1,
                "tags": "[]",
            },
            {
                "post_id": "p2",
                "bid": "b1",
                "title": "Post 2",
                "url": "https://example.com/2",
                "publish_date": "2024-01-02",
                "views": 20,
                "replies": 2,
                "tags": "[]",
            },
        ]
        bulk_upsert_posts(conn, posts)
        conn.commit()

        rows = conn.execute("SELECT COUNT(*) FROM posts").fetchone()
        assert rows[0] == 2
        conn.close()

    def test_update_crawl_log(self, temp_db):
        conn = get_db(temp_db)
        update_crawl_log(conn, "blog_posts", "123", 10)
        conn.commit()

        row = conn.execute("SELECT * FROM crawl_log WHERE crawl_type='blog_posts' AND target_id='123'").fetchone()
        assert row is not None
        assert row["records"] == 10
        conn.close()

    def test_get_last_crawl(self, temp_db):
        conn = get_db(temp_db)
        update_crawl_log(conn, "blog_posts", "123", 5)
        conn.commit()
        conn.close()

        last = get_last_crawl("blog_posts", "123", db_path=temp_db)
        assert last is not None

    def test_get_last_crawl_none(self, temp_db):
        last = get_last_crawl("blog_posts", "nonexistent", db_path=temp_db)
        assert last is None


class TestLoadAuthorsJson:
    def test_load_authors_json_returns_dict(self):
        authors = load_authors_json()
        assert isinstance(authors, dict)


class TestToCsv:
    def test_to_csv_creates_file(self, tmp_path):
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        csv_path = tmp_path / "output.csv"
        to_csv(data, str(csv_path))

        assert csv_path.exists()
        content = csv_path.read_text(encoding="utf-8-sig")
        assert "name" in content
        assert "Alice" in content
        assert "Bob" in content

    def test_to_csv_empty_data(self, tmp_path):
        to_csv([], str(tmp_path / "empty.csv"))
        # 空数据不创建文件
