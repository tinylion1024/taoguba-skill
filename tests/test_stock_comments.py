"""test_stock_comments.py - 股票评论爬虫解析函数测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from tgb_stock_comments import (
    extract_coolattr_from_html,
    format_post,
    parse_post_item,
)


# ----------------------------------------------------------------------
# extract_coolattr_from_html tests
# ----------------------------------------------------------------------
class TestExtractCoolAttr:
    def test_extract_basic_coolattr(self):
        html = """
        <html><head><script>
        var coolAttr = [{"newTopicID":"abc123","rtype":"T","subject":"Test Post","body":"Hello","userName":"user1","actionDate":"2024-01-01 10:00","replyNum":5,"viewNum":100,"usefulNum":10}];
        var someOther = 'foo';
        </script></head></html>
        """
        items = extract_coolattr_from_html(html)
        assert len(items) == 1
        assert items[0]["newTopicID"] == "abc123"

    def test_extract_multiple_items(self):
        html = """
        <html><script>
        var coolAttr = [
            {"newTopicID":"id1","rtype":"T","subject":"Post 1","userName":"u1"},
            {"newTopicID":"id2","rtype":"R","subject":"Post 2","userName":"u2"}
        ];
        </script></html>
        """
        items = extract_coolattr_from_html(html)
        assert len(items) == 2
        assert items[0]["newTopicID"] == "id1"
        assert items[1]["newTopicID"] == "id2"

    def test_extract_no_coolattr(self):
        html = "<html><body>No data here</body></html>"
        items = extract_coolattr_from_html(html)
        assert items == []

    def test_extract_with_html_entities(self):
        html = r"""
        <html><script>
        var coolAttr = [{"newTopicID":"abc","subject":"Post&#x80CC;&#x666F;","userName":"test"}];
        </script></html>
        """
        items = extract_coolattr_from_html(html)
        assert len(items) == 1


# ----------------------------------------------------------------------
# parse_post_item tests
# ----------------------------------------------------------------------
class TestParsePostItem:
    def test_parse_main_post(self):
        item = {
            "rtype": "T",
            "newTopicID": "topic123",
            "rID": "",
            "subject": "Test Main Post",
            "body": "This is the body",
            "userName": "author1",
            "actionDate": "2024-01-15 12:30",
            "replyNum": 5,
            "viewNum": 100,
            "usefulNum": 20,
            "userID": "uid123",
        }
        result = parse_post_item(item)

        assert result["type"] == "T"
        assert result["title"] == "Test Main Post"
        assert result["body"] == "This is the body"
        assert result["author"] == "author1"
        assert result["time"] == "2024-01-15 12:30"
        assert result["url"] == "https://www.tgb.cn/a/topic123"
        assert result["likes"] == 20
        assert result["comments"] == 5
        assert result["views"] == 100
        assert result["is_reply"] is False
        assert result["topic_id"] == "topic123"
        assert result["user_id"] == "uid123"

    def test_parse_reply_post(self):
        item = {
            "rtype": "R",
            "newTopicID": "topic456",
            "rID": "reply789",
            "subject": "Re: Test",
            "body": "This is a reply",
            "userName": "replier",
            "actionDate": "2024-01-16 08:00",
            "replyNum": 0,
            "viewNum": 0,
            "usefulNum": 3,
            "userID": "uid456",
        }
        result = parse_post_item(item)

        assert result["type"] == "R"
        assert result["is_reply"] is True
        assert result["url"] == "https://www.tgb.cn/a/topic456/reply789#reply789"
        assert result["topic_id"] == "topic456"

    def test_parse_decodes_html_entities(self):
        item = {
            "rtype": "T",
            "newTopicID": "abc",
            "rID": "",
            "subject": "Test&#x4E2D;&#x6587;",
            "body": "Body with &lt;tag&gt;",
            "userName": "user",
            "actionDate": "2024-01-01",
            "replyNum": 0,
            "viewNum": 0,
            "usefulNum": 0,
            "userID": "uid",
        }
        result = parse_post_item(item)
        # HTML entities should be decoded
        assert "&#x4E2D;" not in result["title"]

    def test_parse_handles_missing_fields(self):
        item = {
            "rtype": "T",
            "newTopicID": "abc",
        }
        result = parse_post_item(item)
        assert result["type"] == "T"
        assert result["title"] == ""
        assert result["body"] == ""
        assert result["author"] == ""
        assert result["topic_id"] == "abc"

    def test_parse_removes_font_tags(self):
        item = {
            "rtype": "T",
            "newTopicID": "abc",
            "rID": "",
            "subject": "Test <font color='red'>highlighted</font> text",
            "userName": "user",
            "actionDate": "2024-01-01",
            "replyNum": 0,
            "viewNum": 0,
            "usefulNum": 0,
            "userID": "uid",
        }
        result = parse_post_item(item)
        assert "<font" not in result["title"]
        assert "highlighted" in result["title"]


# ----------------------------------------------------------------------
# format_post tests
# ----------------------------------------------------------------------
class TestFormatPost:
    def test_format_main_post(self):
        post = {
            "is_reply": False,
            "title": "Main Post",
            "author": "user1",
            "user_id": "uid123",
            "time": "2024-01-01 12:00",
            "url": "https://www.tgb.cn/a/abc",
            "likes": 10,
            "comments": 5,
            "views": 100,
            "body": "This is the body content",
        }
        formatted = format_post(post)
        assert "📌 主帖" in formatted
        assert "Main Post" in formatted
        assert "user1" in formatted
        assert "uid123" in formatted

    def test_format_reply_post(self):
        post = {
            "is_reply": True,
            "title": "Reply Post",
            "author": "user2",
            "user_id": "uid456",
            "time": "2024-01-02 08:00",
            "url": "https://www.tgb.cn/a/abc/def#def",
            "likes": 3,
            "comments": 0,
            "views": 0,
            "body": "",
        }
        formatted = format_post(post)
        assert "🔁 跟帖回复" in formatted

    def test_format_with_body_limit(self):
        post = {
            "is_reply": False,
            "title": "Test",
            "author": "user",
            "user_id": "uid",
            "time": "2024-01-01",
            "url": "https://example.com",
            "likes": 0,
            "comments": 0,
            "views": 0,
            "body": "A" * 500,
        }
        formatted = format_post(post, body_limit=100)
        assert "..." in formatted
        assert len(formatted) < len("A" * 500)
