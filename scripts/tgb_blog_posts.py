#!/usr/bin/env python3
"""
tgb_blog_posts.py
大V博客帖子爬虫 for 淘股吧 (tgb.cn)

抓取指定大V（如 https://www.tgb.cn/blog/7105646 朱雀路作手）的所有帖子列表，
包括标题、URL、浏览/回复数、发表时间、标签（原创/精华）。

Usage:
    python scripts/tgb_blog_posts.py --blog-url https://www.tgb.cn/blog/7105646 --pages 3
    python scripts/tgb_blog_posts.py --blog-id 7105646 --pages 3 --fetch-content
"""

import argparse
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# Logging configuration
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('blog_posts.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

# ----------------------------------------------------------------------
# HTTP headers
# ----------------------------------------------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://www.tgb.cn/",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

BASE_URL = "https://www.tgb.cn"


def parse_blog_url(url_or_id):
    """从URL或ID中提取userID"""
    if url_or_id.isdigit():
        return url_or_id
    m = re.search(r'/blog/(\d+)', url_or_id)
    if m:
        return m.group(1)
    raise ValueError(f"Invalid blog URL or ID: {url_or_id}")


def build_blog_url(user_id, page=1):
    """构建博客URL"""
    if page == 1:
        return f"{BASE_URL}/blog/{user_id}"
    return f"{BASE_URL}/blog/{user_id}?page={page}"


def fetch_blog_page(url, session, timeout=15):
    """获取博客页面HTML"""
    try:
        resp = session.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        return resp.text
    except requests.RequestException as e:
        logging.error(f"Failed to fetch {url}: {e}")
        return None


def parse_article_list(html):
    """解析博客文章列表"""
    soup = BeautifulSoup(html, 'html.parser')
    articles = []

    # 找到所有文章条目 <div class="article_tittle">
    for article_div in soup.find_all('div', class_='article_tittle'):
        try:
            # 标题和URL
            title_tag = article_div.find('a', href=True)
            if not title_tag:
                continue

            href = title_tag.get('href', '')
            title = title_tag.get('title', title_tag.get_text(strip=True))
            article_url = f"{BASE_URL}/{href}" if href.startswith('a/') else f"{BASE_URL}/{href}"

            # 浏览/回复数
            llhf = article_div.find('div', class_='tittle_llhf')
            views_replies = llhf.get_text(strip=True) if llhf else ''

            # 发表时间
            fbdate = article_div.find('div', class_='tittle_fbshijian')
            pub_date = fbdate.get_text(strip=True) if fbdate else ''

            # 标签（原/精）
            tags = []
            if article_div.find('span', class_='tittle_yuanchuang'):
                tags.append('原')
            if article_div.find('span', class_='tittle_jinghua'):
                tags.append('精')
            tag_str = ''.join(tags)

            # 提取文章ID用于后续抓取正文
            article_id = re.search(r'/a/([a-zA-Z0-9]+)', article_url)
            article_id = article_id.group(1) if article_id else ''

            articles.append({
                'title': title,
                'url': article_url,
                'article_id': article_id,
                'views_replies': views_replies,
                'pub_date': pub_date,
                'tag': tag_str,
            })
        except Exception as e:
            logging.debug(f"Failed to parse article: {e}")
            continue

    return articles


def fetch_article_content(article_url, session, timeout=15):
    """抓取单篇文章的正文内容"""
    try:
        resp = session.get(article_url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 找文章正文区域 - 尝试多个选择器
        content = None

        # 方案1: 找 stockDetailContent 或 similar class
        for cls in ['stockDetailContent', 'article-content', 'content', 'stock_detail']:
            elem = soup.find(class_=cls)
            if elem:
                content = elem.get_text(separator='\n', strip=True)
                break

        # 方案2: 找微博或博客正文容器
        if not content:
            for tag in soup.find_all(['div', 'article'], {'id': re.compile(r'(content|body|main)')}):
                text = tag.get_text(separator='\n', strip=True)
                if len(text) > 100:
                    content = text
                    break

        # 方案3: 找class含info/post/content的div
        if not content:
            for tag in soup.find_all('div', class_=re.compile(r'(info|post|content)')):
                text = tag.get_text(separator='\n', strip=True)
                if len(text) > 200:
                    content = text[:3000]
                    break

        return content if content else ''

    except requests.RequestException as e:
        logging.warning(f"Failed to fetch article {article_url}: {e}")
        return ''


def crawl_blog(blog_url, pages=3, delay=0.5, out_dir='./data', fetch_content=False):
    """爬取大V博客所有帖子"""
    user_id = parse_blog_url(blog_url)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime('%Y%m%d')
    list_file = out_path / f"{user_id}-posts-list-{date_str}.txt"
    full_file = out_path / f"{user_id}-posts-full-{date_str}.txt"

    session = requests.Session()
    all_articles = []
    total_pages = 0

    for page in range(1, pages + 1):
        url = build_blog_url(user_id, page)
        logging.info(f"Crawling page {page}/{pages}: {url}")

        html = fetch_blog_page(url, session)
        if not html:
            logging.warning(f"Skipping page {page} (fetch failed)")
            continue

        articles = parse_article_list(html)

        if not articles:
            # 只有第一页有内容，说明该博客文章不多
            if page == 1:
                logging.warning("No articles found on first page")
            else:
                logging.info(f"Page {page} has no articles, stopping")
            break

        logging.info(f"  Found {len(articles)} articles")
        all_articles.extend(articles)
        total_pages = page

        if page < pages:
            time.sleep(delay)

    if not all_articles:
        logging.error("No articles crawled!")
        return

    # 保存帖子列表
    logging.info(f"Saving {len(all_articles)} articles to {list_file}")
    with open(list_file, 'w', encoding='utf-8') as f:
        f.write(f"淘股吧大V博客帖子列表\n")
        f.write(f"用户ID: {user_id}\n")
        f.write(f"博客URL: {build_blog_url(user_id, 1)}\n")
        f.write(f"抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"总页数: {total_pages} | 总帖子数: {len(all_articles)}\n")
        f.write("=" * 80 + "\n\n")

        for i, art in enumerate(all_articles, 1):
            tag_prefix = f"[{art['tag']}]" if art['tag'] else ""
            f.write(f"【{i}】{tag_prefix} {art['title']}\n")
            f.write(f"    时间: {art['pub_date']} | 浏览/回复: {art['views_replies']}\n")
            f.write(f"    URL: {art['url']}\n")
            f.write(f"    文章ID: {art['article_id']}\n")
            f.write("\n")

    # 抓取正文内容
    if fetch_content:
        logging.info(f"Fetching content for {len(all_articles)} articles...")
        with open(full_file, 'w', encoding='utf-8') as f:
            f.write(f"淘股吧大V博客帖子详情（含正文）\n")
            f.write(f"用户ID: {user_id}\n")
            f.write(f"博客URL: {build_blog_url(user_id, 1)}\n")
            f.write(f"抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")

            for i, art in enumerate(all_articles, 1):
                tag_prefix = f"[{art['tag']}]" if art['tag'] else ""
                f.write(f"{'='*80}\n")
                f.write(f"【{i}】{tag_prefix} {art['title']}\n")
                f.write(f"时间: {art['pub_date']} | 浏览/回复: {art['views_replies']}\n")
                f.write(f"URL: {art['url']}\n")
                f.write(f"文章ID: {art['article_id']}\n")
                f.write("-" * 40 + "\n")

                # 抓取正文
                content = fetch_article_content(art['url'], session)
                if content:
                    f.write(f"正文:\n{content[:5000]}\n")
                else:
                    f.write("正文: (未获取到)\n")

                f.write("\n")
                if i < len(all_articles):
                    time.sleep(delay)

    logging.info(f"Done! List: {list_file}" + (f", Full: {full_file}" if fetch_content else ""))

    # 打印摘要
    print("\n" + "=" * 60)
    print(f"大V博客用户ID: {user_id}")
    print(f"抓取页数: {total_pages}")
    print(f"帖子总数: {len(all_articles)}")
    print(f"输出文件: {list_file}" + (f", {full_file}" if fetch_content else ""))
    print("=" * 60)
    print("\n前5条帖子:")
    for i, art in enumerate(all_articles[:5], 1):
        print(f"  {i}. [{art['views_replies']}] {art['pub_date']} - {art['title'][:50]}")


def main():
    parser = argparse.ArgumentParser(
        description="Crawl blog posts from 淘股吧 (tgb.cn) big-V personal blogs."
    )
    parser.add_argument('--blog-url', help='Blog URL, e.g. https://www.tgb.cn/blog/7105646')
    parser.add_argument('--blog-id', help='Blog user ID, e.g. 7105646')
    parser.add_argument('--pages', type=int, default=3, help='Number of pages to crawl (default: 3)')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between requests (default: 0.5s)')
    parser.add_argument('--out-dir', default='./data', help='Output directory (default: ./data)')
    parser.add_argument('--fetch-content', action='store_true', help='Also fetch full article content')

    args = parser.parse_args()

    if not args.blog_url and not args.blog_id:
        parser.print_help()
        sys.exit(1)

    blog_input = args.blog_url or args.blog_id
    crawl_blog(blog_input, pages=args.pages, delay=args.delay,
               out_dir=args.out_dir, fetch_content=args.fetch_content)


if __name__ == '__main__':
    main()
