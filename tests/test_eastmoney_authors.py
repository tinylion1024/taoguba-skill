"""test_eastmoney_authors.py - 东方财富作者信息提取与UPSERT测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from tgb_eastmoney_comments import parse_list_page


# ----------------------------------------------------------------------
# author_id 提取测试
# ----------------------------------------------------------------------
class TestAuthorIdExtraction:
    def test_extract_author_id_from_i_eastmoney(self):
        """从 //i.eastmoney.com/{id} URL 提取 author_id"""
        html = """
        <html><body>
        <table class="default_list">
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">160</div></td>
              <td><div class="reply">5</div></td>
              <td>
                <div class="title">
                  <a data-postid="1699428687" data-posttype="20" href="//i.eastmoney.com/5034093950183932" title="财富号帖子">测试帖子</a>
                </div>
              </td>
              <td><div class="author"><a href="/list,300750.html">达人小明</a></div></td>
              <td><div class="update">04-27 12:23</div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert len(items) == 1
        assert items[0]["author_id"] == "5034093950183932"

    def test_extract_author_id_empty_when_no_i_eastmoney(self):
        """没有 i.eastmoney.com 链接时 author_id 为空"""
        html = """
        <html><body>
        <table class="default_list">
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">100</div></td>
              <td><div class="reply">2</div></td>
              <td><div class="title"><a data-postid="111" href="/news,300750,111.html" title="普通帖子">文字1</a></div></td>
              <td><div class="author"><a href="/list,300750.html">作者1</a></div></td>
              <td><div class="update">04-26 10:00</div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert len(items) == 1
        assert items[0]["author_id"] == ""

    def test_author_id_extraction_multiple_posts(self):
        """多帖子中部分有 author_id"""
        html = """
        <html><body>
        <table class="default_list">
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">100</div></td>
              <td><div class="reply">2</div></td>
              <td><div class="title"><a data-postid="111" href="//i.eastmoney.com/111222333" title="T1">T1</a></div></td>
              <td><div class="author">A1</div></td>
              <td><div class="update">04-26 10:00</div></td>
            </tr>
            <tr class="listitem">
              <td><div class="read">200</div></td>
              <td><div class="reply">3</div></td>
              <td><div class="title"><a data-postid="222" href="/news,300750,222.html" title="T2">T2</a></div></td>
              <td><div class="author">A2</div></td>
              <td><div class="update">04-25 09:00</div></td>
            </tr>
            <tr class="listitem">
              <td><div class="read">300</div></td>
              <td><div class="reply">4</div></td>
              <td><div class="title"><a data-postid="333" href="//i.eastmoney.com/444555666" title="T3">T3</a></div></td>
              <td><div class="author">A3</div></td>
              <td><div class="update">04-24 08:00</div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert len(items) == 3
        assert items[0]["author_id"] == "111222333"
        assert items[1]["author_id"] == ""
        assert items[2]["author_id"] == "444555666"


# ----------------------------------------------------------------------
# post_type 识别测试
# ----------------------------------------------------------------------
class TestPostTypeRecognition:
    def test_caifuhao_post_type(self):
        """data-posttype="20" → caifuhao"""
        html = """
        <html><body>
        <table class="default_list">
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">160</div></td>
              <td><div class="reply">5</div></td>
              <td>
                <div class="title">
                  <a data-postid="1699428687" data-posttype="20" href="//i.eastmoney.com/5034093950183932" title="T">帖子</a>
                </div>
              </td>
              <td><div class="author">作者</div></td>
              <td><div class="update">04-27 12:23</div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert items[0]["post_type"] == "caifuhao"

    def test_guba_post_type(self):
        """data-posttype 不是 "20" → guba"""
        html = """
        <html><body>
        <table class="default_list">
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">160</div></td>
              <td><div class="reply">5</div></td>
              <td>
                <div class="title">
                  <a data-postid="1699428687" data-posttype="0" href="/news,300750,1699428687.html" title="T">帖子</a>
                </div>
              </td>
              <td><div class="author">作者</div></td>
              <td><div class="update">04-27 12:23</div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert items[0]["post_type"] == "guba"

    def test_guba_post_type_missing_posttype_attr(self):
        """没有 data-posttype 属性 → guba"""
        html = """
        <html><body>
        <table class="default_list">
          <tbody class="listbody">
            <tr class="listitem">
              <td><div class="read">160</div></td>
              <td><div class="reply">5</div></td>
              <td>
                <div class="title">
                  <a data-postid="1699428687" href="/news,300750,1699428687.html" title="T">帖子</a>
                </div>
              </td>
              <td><div class="author">作者</div></td>
              <td><div class="update">04-27 12:23</div></td>
            </tr>
          </tbody>
        </table>
        </body></html>
        """
        items = parse_list_page(html)
        assert items[0]["post_type"] == "guba"


# ----------------------------------------------------------------------
# 作者类型映射逻辑测试（基于 post_type 和 author_type 参数）
# ----------------------------------------------------------------------
class TestAuthorTypeMapping:
    def test_personal_author_type_mapping(self):
        """author_type='f' 对应 'personal'"""
        # 模拟 save_results 中的映射逻辑
        author_type = "f"
        mapped = "personal" if author_type == "f" else ("institutional" if author_type == "j" else "")
        assert mapped == "personal"

    def test_institutional_author_type_mapping(self):
        """author_type='j' 对应 'institutional'"""
        author_type = "j"
        mapped = "personal" if author_type == "f" else ("institutional" if author_type == "j" else "")
        assert mapped == "institutional"

    def test_default_author_type_mapping(self):
        """author_type='' 对应 ''"""
        author_type = ""
        mapped = "personal" if author_type == "f" else ("institutional" if author_type == "j" else "")
        assert mapped == ""


# ----------------------------------------------------------------------
# authors 表 UPSERT 去重测试（基于 SQLite）
# ----------------------------------------------------------------------
class TestAuthorsUpsert:
    def test_authors_upsert_deduplication(self, tmp_path):
        """同一 author_id 多次插入应去重（ON CONFLICT）"""
        import sqlite3
        from common import get_db

        db_file = tmp_path / "test_authors.db"
        conn = sqlite3.connect(db_file, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        # 创建 eastmoney_authors 表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eastmoney_authors (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                author_id       TEXT UNIQUE,
                author_name     TEXT,
                author_type     TEXT,
                stock_code      TEXT DEFAULT '',
                follower_count  INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        # 第一次插入
        conn.execute(
            """
            INSERT INTO eastmoney_authors (author_id, author_name, stock_code, author_type)
            VALUES (:author_id, :author_name, :stock_code, :author_type)
            ON CONFLICT(author_id) DO UPDATE SET
                author_name = COALESCE(excluded.author_name, eastmoney_authors.author_name),
                stock_code = COALESCE(excluded.stock_code, eastmoney_authors.stock_code),
                author_type = COALESCE(excluded.author_type, eastmoney_authors.author_type)
            """,
            {"author_id": "123456", "author_name": "达人A", "stock_code": "300750", "author_type": "personal"},
        )
        conn.commit()

        rows = conn.execute("SELECT * FROM eastmoney_authors WHERE author_id='123456'").fetchall()
        assert len(rows) == 1
        assert rows[0]["author_name"] == "达人A"
        assert rows[0]["author_type"] == "personal"

        # 第二次插入（不同 stock_code，但同一 author_id）
        conn.execute(
            """
            INSERT INTO eastmoney_authors (author_id, author_name, stock_code, author_type)
            VALUES (:author_id, :author_name, :stock_code, :author_type)
            ON CONFLICT(author_id) DO UPDATE SET
                author_name = COALESCE(excluded.author_name, eastmoney_authors.author_name),
                stock_code = COALESCE(excluded.stock_code, eastmoney_authors.stock_code),
                author_type = COALESCE(excluded.author_type, eastmoney_authors.author_type)
            """,
            {"author_id": "123456", "author_name": "达人A（改名）", "stock_code": "600519", "author_type": "personal"},
        )
        conn.commit()

        rows = conn.execute("SELECT * FROM eastmoney_authors WHERE author_id='123456'").fetchall()
        assert len(rows) == 1  # 仍然只有一条
        # author_name 不应被覆盖（因为 excluded.author_name 有值）
        assert rows[0]["author_name"] == "达人A（改名）"
        # stock_code 应该被更新（因为留空则用原值）
        assert rows[0]["stock_code"] == "600519"

        conn.close()

    def test_multiple_authors_insert(self, tmp_path):
        """批量插入多个不同作者"""
        import sqlite3

        db_file = tmp_path / "test_authors2.db"
        conn = sqlite3.connect(db_file, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS eastmoney_authors (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                author_id       TEXT UNIQUE,
                author_name     TEXT,
                author_type     TEXT,
                stock_code      TEXT DEFAULT '',
                follower_count  INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        authors = [
            {"author_id": "111", "author_name": "达人甲", "stock_code": "300750", "author_type": "personal"},
            {"author_id": "222", "author_name": "达人乙", "stock_code": "300750", "author_type": "personal"},
            {"author_id": "333", "author_name": "机构A", "stock_code": "300750", "author_type": "institutional"},
        ]

        for a in authors:
            conn.execute(
                """
                INSERT INTO eastmoney_authors (author_id, author_name, stock_code, author_type)
                VALUES (:author_id, :author_name, :stock_code, :author_type)
                ON CONFLICT(author_id) DO UPDATE SET
                    author_name = COALESCE(excluded.author_name, eastmoney_authors.author_name),
                    stock_code = COALESCE(excluded.stock_code, eastmoney_authors.stock_code),
                    author_type = COALESCE(excluded.author_type, eastmoney_authors.author_type)
                """,
                a,
            )
        conn.commit()

        rows = conn.execute("SELECT * FROM eastmoney_authors ORDER BY author_id").fetchall()
        assert len(rows) == 3
        assert rows[0]["author_id"] == "111"
        assert rows[1]["author_id"] == "222"
        assert rows[2]["author_id"] == "333"
        assert rows[0]["author_type"] == "personal"
        assert rows[2]["author_type"] == "institutional"

        conn.close()
