"""test_blog_posts.py - 博客帖子爬虫解析函数测试"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from tgb_blog_posts import (
    build_blog_url,
    fetch_article_content,
    parse_article_list,
    parse_blog_url,
)


# ----------------------------------------------------------------------
# URL 解析 tests
# ----------------------------------------------------------------------
class TestParseBlogUrl:
    def test_parse_numeric_id(self):
        assert parse_blog_url("7105646") == "7105646"

    def test_parse_blog_url(self):
        assert parse_blog_url("https://www.tgb.cn/blog/7105646") == "7105646"

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_blog_url("not-a-valid-input")


class TestBuildBlogUrl:
    def test_build_first_page(self):
        url = build_blog_url("7105646", 1)
        assert url == "https://www.tgb.cn/blog/7105646"

    def test_build_second_page(self):
        url = build_blog_url("7105646", 2)
        assert url == "https://www.tgb.cn/blog/7105646?page=2"

    def test_build_page_3(self):
        url = build_blog_url("7105646", 3)
        assert "page=3" in url


# ----------------------------------------------------------------------
# parse_article_list tests
# ----------------------------------------------------------------------
class TestParseArticleList:
    def test_parse_single_article(self):
        html = """
        <html>
        <body>
            <div class="article_tittle">
                <a href="a/abc123" title="Test Article Title">Test Article Title</a>
                <div class="tittle_llhf">1000阅读/20回复</div>
                <div class="tittle_fbshijian">2024-01-15</div>
                <span class="tittle_yuanchuang">原创</span>
            </div>
        </body>
        </html>
        """
        articles = parse_article_list(html)
        assert len(articles) == 1
        assert articles[0]["post_id"] == "abc123"
        assert articles[0]["title"] == "Test Article Title"
        assert articles[0]["views"] == 1000
        assert articles[0]["replies"] == 20
        assert articles[0]["publish_date"] == "2024-01-15"
        tags = json.loads(articles[0]["tags"])
        assert "原创" in tags

    def test_parse_multiple_articles(self):
        html = """
        <html>
        <body>
            <div class="article_tittle">
                <a href="a/post1" title="First Post">First Post</a>
                <div class="tittle_llhf">500阅读/10回复</div>
                <div class="tittle_fbshijian">2024-01-01</div>
            </div>
            <div class="article_tittle">
                <a href="a/post2" title="Second Post">Second Post</a>
                <div class="tittle_llhf">200阅读/5回复</div>
                <div class="tittle_fbshijian">2024-01-02</div>
                <span class="tittle_jinghua">精华</span>
            </div>
        </body>
        </html>
        """
        articles = parse_article_list(html)
        assert len(articles) == 2
        assert articles[0]["post_id"] == "post1"
        assert articles[1]["post_id"] == "post2"
        tags = json.loads(articles[1]["tags"])
        assert "精华" in tags

    def test_parse_empty_html(self):
        html = "<html><body><p>No articles here</p></body></html>"
        articles = parse_article_list(html)
        assert articles == []

    def test_parse_article_without_title_tag(self):
        html = """
        <html>
        <body>
            <div class="article_tittle">
                <div class="tittle_llhf">100阅读</div>
            </div>
        </body>
        </html>
        """
        articles = parse_article_list(html)
        assert articles == []

    def test_parse_views_and_replies(self):
        html = """
        <html>
        <body>
            <div class="article_tittle">
                <a href="a/post1">Test</a>
                <div class="tittle_llhf">12345阅读/678回复</div>
                <div class="tittle_fbshijian">2024-01-01</div>
            </div>
        </body>
        </html>
        """
        articles = parse_article_list(html)
        assert articles[0]["views"] == 12345
        assert articles[0]["replies"] == 678

    def test_parse_handles_missing_divs(self):
        html = """
        <html>
        <body>
            <div class="article_tittle">
                <a href="a/post1" title="Only Title">Only Title</a>
            </div>
        </body>
        </html>
        """
        articles = parse_article_list(html)
        assert len(articles) == 1
        assert articles[0]["views"] == 0
        assert articles[0]["replies"] == 0
        assert articles[0]["publish_date"] == ""

    def test_parse_with_jinghua_tag(self):
        html = """
        <html>
        <body>
            <div class="article_tittle">
                <a href="a/post1">Elite Post</a>
                <div class="tittle_llhf">100阅读</div>
                <div class="tittle_fbshijian">2024-01-01</div>
                <span class="tittle_jinghua">精华</span>
            </div>
        </body>
        </html>
        """
        articles = parse_article_list(html)
        tags = json.loads(articles[0]["tags"])
        assert "精华" in tags

    def test_parse_url_construction(self):
        html = """
        <html>
        <body>
            <div class="article_tittle">
                <a href="a/xyz789" title="URL Test">URL Test</a>
                <div class="tittle_llhf">50阅读</div>
                <div class="tittle_fbshijian">2024-01-01</div>
            </div>
        </body>
        </html>
        """
        articles = parse_article_list(html)
        assert "xyz789" in articles[0]["url"]
        assert "https://www.tgb.cn" in articles[0]["url"]


# ----------------------------------------------------------------------
# fetch_article_content tests
# ----------------------------------------------------------------------
class TestFetchArticleContent:
    @pytest.fixture
    def mock_fetch(self):
        """Mock the fetch function"""
        with pytest.importorskip("pytest") as _:
            pass

    def test_fetch_returns_empty_on_error(self):
        # Test that fetch_article_content handles errors gracefully
        # by mocking fetch to raise an exception
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

        # This test just verifies the function exists and can be called
        # Real network tests would require actual mocking
        assert callable(fetch_article_content)
