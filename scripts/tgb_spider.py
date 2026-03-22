#!/usr/bin/env python3
# tgb_spider.py
import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ------------------------------------------------------------------
# 日志配置
# ------------------------------------------------------------------
logging.basicConfig(
 level=logging.INFO,
 format='%(asctime)s - %(levelname)s - %(message)s',
 handlers=[
 logging.FileHandler('fetch_corpus.log'),
 logging.StreamHandler(sys.stdout)
 ]
)

# ------------------------------------------------------------------
# 通用函数
# ------------------------------------------------------------------
headers = {
 "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
 "Referer": "https://www.tgb.cn/",
 "Accept-Language": "zh-CN,zh;q=0.9"
}

def get_html_content(url: str) -> str | None:
 """获取网页HTML内容"""
 try:
  response = requests.get(url, headers=headers, timeout=10)
  response.raise_for_status()
  return response.text
 except requests.exceptions.Timeout:
  logging.error("请求超时: %s", url)
 except requests.exceptions.HTTPError as http_err:
  logging.error("HTTP 错误: %s - URL: %s", http_err, url)
 except requests.exceptions.RequestException as req_err:
  logging.error("请求错误: %s - URL: %s", req_err, url)
 except Exception as e:
  logging.error("未知错误: %s - URL: %s", e, url)
 return None


# ------------------------------------------------------------------
# 爬取主流程
# ------------------------------------------------------------------
def get_article_infos(base_url: str, s_dt: str, e_dt: str, search_page: int):
 """从列表页抓取文章信息"""
 rt_infos = []
 for page in range(1, search_page + 1):
  list_url = f"{base_url}/{page}-1"
  html = get_html_content(list_url)
  if not html:
   continue

  soup = BeautifulSoup(html, 'lxml')
  divs = soup.find_all('div', class_='Nbbs-tiezi-lists')

  for div in divs:
   try:
    dt = div.find('div', class_="left middle-list-post").get_text(strip=True)
    href = div.find("a")["href"]
    title = div.find("a")["title"]
    author = div.find('div', class_="left middle-list-user cblue cursor overhide").get_text(strip=True)

    if s_dt <= dt <= e_dt:
     rt_infos.append({
      "title": f"《{title}》",
      "author_name": author,
      "url": urljoin(base_url, href) # 修复域名拼接
     })
   except (AttributeError, KeyError) as e:
    logging.warning("解析单条文章信息失败: %s", e)
 return rt_infos


def fetch_article_text(urls):
 """批量抓取正文"""
 texts = []
 for idx, url in enumerate(urls, 1):
  html = get_html_content(url)
  if not html:
   continue

  soup = BeautifulSoup(html, 'html.parser')
  content_div = soup.find('div', class_='article-text p_coten')
  if not content_div:
   logging.warning("未找到正文区域: %s", url)
   continue

  for tag in content_div(["script", "style"]):
   tag.extract()

  text = re.sub(r'\([^)]*\)|\n|\t', '', content_div.get_text(strip=True))
  texts.append(text)
  logging.info("第%d篇文章处理完毕", idx)
 return '\n'.join(texts)


def write_to_txt(text: str, file_path: Path):
 """写入文本文件"""
 file_path.parent.mkdir(parents=True, exist_ok=True)
 try:
  file_path.write_text(text, encoding='utf-8')
  logging.info("文本已写入 %s", file_path)
 except IOError as e:
  logging.error("写入文件失败: %s", e)


# ------------------------------------------------------------------
# CLI 入口
# ------------------------------------------------------------------
def parse_args():
 parser = argparse.ArgumentParser(description="淘股吧文章抓取")
 parser.add_argument('--base-url', default='https://www.tgb.cn/dianzan',
  help='列表页基础URL（不含分页）')
 parser.add_argument('--s-dt', required=True,
  help='开始日期时间，格式 MM-DD HH:MM')
 parser.add_argument('--e-dt', required=True,
  help='结束日期时间，格式 MM-DD HH:MM')
 parser.add_argument('--search-page', type=int, default=5,
  help='要抓取的列表页页数')
 parser.add_argument('--out-dir', default='./data',
  help='输出根目录（会自动创建 corpus 子目录）')
 return parser.parse_args()


def main():
 args = parse_args()

 date_part = datetime.now().strftime("%m-%d")
 corpus_path = Path(args.out_dir) / "corpus"
 corpus_file = corpus_path / f"{date_part}-tgb-corpus.txt"
 list_file = corpus_path / f"{date_part}-tgb-list.txt"

 # 确保输出目录存在
 corpus_path.mkdir(parents=True, exist_ok=True)

 # 1. 抓取文章列表
 infos = get_article_infos(args.base_url, args.s_dt, args.e_dt, args.search_page)
 urls = list({info["url"] for info in infos})
 # 同时保存文章列表信息
 with open(list_file, 'w', encoding='utf-8') as f:
  for info in infos:
   f.write(f"{info['title']} - {info['author_name']}\n{info['url']}\n\n")
 logging.info("共获取 %d 条文章", len(urls))

 if len(urls) == 0:
  logging.warning("未获取到符合日期范围的文章，程序结束")
  return

 # 2. 抓取正文
 text = fetch_article_text(urls)
 if not text.strip():
  logging.warning("未抓取到任何正文内容，程序结束")
  return
 write_to_txt(text, corpus_file)


if __name__ == '__main__':
 main()
