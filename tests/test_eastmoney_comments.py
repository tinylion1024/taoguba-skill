"""test_eastmoney_comments.py - 东方财富股吧评论爬虫解析函数测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from tgb_eastmoney_comments import build_list_url, format_post, parse_list_page


# ----------------------------------------------------------------------
# parse_list_page tests
# ----------------------------------------------------------------------
class TestParseListPage:
    def test_parse_basic_html(self):
        html = """
        <html><body>
        <table class="default_list">
          <thead class="listhead">
            <tr>
              <td><div>阅读</div></td>
              <td><div>评论</div></td>
              <td><div>标题</div></td>
              <td><div>作者</div></td>
              <td><div>最后更新</div></td>
            </tr>
          </thead>
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">160</div></td>
              <td><div class="reply">5</div></td>
              <td>
                <div class="title">
                  <a data-postid="1699428687" href="/news,300750,1699428687.html" title="测试帖子标题">测试帖子</a>
                </div>
              </td>
              <td><div class="author"><a href="/list,300750.html">股友张三</a></div></td>
              <td><div class="update">04-27 12:23</div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert len(items) == 1
        assert items[0]["post_id"] == "1699428687"
        assert items[0]["title"] == "测试帖子标题"
        assert items[0]["author"] == "股友张三"
        assert items[0]["publish_dt"] == "04-27 12:23"
        assert items[0]["views"] == 160
        assert items[0]["replies"] == 5
        assert items[0]["url"] == "https://guba.eastmoney.com/news,300750,1699428687.html"

    def test_parse_multiple_items(self):
        html = """
        <html><body>
        <table class="default_list">
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">100</div></td>
              <td><div class="reply">2</div></td>
              <td><div class="title"><a data-postid="111" href="/news,300750,111.html" title="标题1">文字1</a></div></td>
              <td><div class="author"><a href="/list,300750.html">作者1</a></div></td>
              <td><div class="update">04-26 10:00</div></td>
            </tr>
            <tr class="listitem">
              <td><div class="read">200</div></td>
              <td><div class="reply">3</div></td>
              <td><div class="title"><a data-postid="222" href="/news,300750,222.html" title="标题2">文字2</a></div></td>
              <td><div class="author"><a href="/list,300750.html">作者2</a></div></td>
              <td><div class="update">04-25 09:00</div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert len(items) == 2
        assert items[0]["post_id"] == "111"
        assert items[1]["post_id"] == "222"
        assert items[0]["views"] == 100
        assert items[1]["replies"] == 3

    def test_parse_empty_list(self):
        html = "<html><body><table class='default_list'><tbody class='listbody'></tbody></table></body></html>"
        items = parse_list_page(html)
        assert items == []

    def test_parse_no_tbody(self):
        html = "<html><body><p>No table here</p></body></html>"
        items = parse_list_page(html)
        assert items == []

    def test_parse_missing_fields(self):
        html = """
        <html><body>
        <table class="default_list">
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">0</div></td>
              <td><div class="reply">0</div></td>
              <td><div class="title"><a data-postid="999">无title属性</a></div></td>
              <td><div class="author">无链接作者</div></td>
              <td><div class="update">04-24 08:00</div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert len(items) == 1
        assert items[0]["post_id"] == "999"
        # title fallback to text content
        assert items[0]["title"] == "无title属性"
        assert items[0]["author"] == "无链接作者"

    def test_parse_zero_reads(self):
        html = """
        <html><body>
        <table class="default_list">
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">0</div></td>
              <td><div class="reply">0</div></td>
              <td><div class="title"><a data-postid="000" href="/x.html" title="T">T</a></div></td>
              <td><div class="author">A</div></td>
              <td><div class="update"></div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert items[0]["views"] == 0
        assert items[0]["replies"] == 0
        assert items[0]["publish_dt"] == ""


# ----------------------------------------------------------------------
# build_list_url tests
# ----------------------------------------------------------------------
class TestBuildListUrl:
    def test_page_1(self):
        url = build_list_url("300750", 1)
        assert url == "https://guba.eastmoney.com/list,300750,1,f.html"

    def test_page_2(self):
        url = build_list_url("300750", 2)
        assert url == "https://guba.eastmoney.com/list,300750,2,f.html"

    def test_arbitrary_page(self):
        url = build_list_url("600519", 5)
        assert url == "https://guba.eastmoney.com/list,600519,5,f.html"


# ----------------------------------------------------------------------
# format_post tests
# ----------------------------------------------------------------------
class TestFormatPost:
    def test_format_basic(self):
        post = {
            "post_id": "123456",
            "title": "测试标题",
            "author": "测试作者",
            "publish_dt": "04-27 12:00",
            "views": 100,
            "replies": 10,
            "url": "https://guba.eastmoney.com/news,300750,123456.html",
            "body": "",
        }
        formatted = format_post(post)
        assert "测试标题" in formatted
        assert "测试作者" in formatted
        assert "04-27 12:00" in formatted
        assert "100" in formatted
        assert "10" in formatted
        assert "guba.eastmoney.com" in formatted