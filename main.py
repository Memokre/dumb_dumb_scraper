import requests
import sys
import re
import time
import random
import json
import hashlib
import os
from bs4 import BeautifulSoup
from typing import Set, Dict, Any, List, Optional
from urllib.parse import urljoin
from datetime import datetime

BASE_URL = "https://finance.yahoo.com/"
SOURCE_SHORT = "yahoo"
SOURCE_FULL = "finance.yahoo.com"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def get_md5_hash(url: str) -> str:
    return hashlib.md5(url.encode('utf-8')).hexdigest()[-8:]

def get_page_content(session: requests.Session, url: str) -> Optional[str]:
    try:
        response = session.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def scrape_article_links(base_url: str, headers: dict) -> set[str]:
    try:
        response = requests.get(base_url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error: Could not retrieve the webpage. {e}", file=sys.stderr)
        return set()

    soup = BeautifulSoup(response.text, 'html.parser')
    target_section = soup.find('section', class_='module-hero hero-3-col yf-1mjoczb')
    unique_urls = set()

    if target_section:
        links = target_section.find_all('a', href=True)
        for link in links:
            href = link['href']
            absolute_url = urljoin(base_url, href)
            if '/news/' in absolute_url:
                cleaned_url = absolute_url.split('?')[0]
                unique_urls.add(cleaned_url)

    print(f"Found {len(unique_urls)} unique article links on the front page.")
    return unique_urls

def filter_tickers(raw_text: str) -> list[str]:
    ticker_pattern = re.compile(r'\b[A-Z]{1,5}(?:\.[A-Z]{1,2})?\b')
    potential_tickers = ticker_pattern.findall(raw_text)
    return sorted(list(set(potential_tickers)))

def scrape_article_page(session: requests.Session, url: str) -> Optional[Dict[str, Any]]:
    html_content = get_page_content(session, url)
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, 'html.parser')

    try:
        title_element = soup.select_one('h1.cover-title')
        title = title_element.get_text(strip=True) if title_element else "Not Found"

        author = "Not Found"
        author_container = soup.select_one('div.byline-attr-author')
        if author_container:
            author_element = author_container.find('a')
            if author_element:
                author = author_element.get_text(strip=True)
            else:
                author_text = author_container.find(string=True, recursive=False)
                author = author_text.strip() if author_text else author_container.get_text(strip=True).split('<span')[0].strip()

        time_element = soup.select_one('div.byline-attr-time-style time.byline-attr-meta-time')
        published_date = time_element['datetime'] if time_element and time_element.has_attr('datetime') else datetime.now().isoformat()

        article_body = soup.find('div', attrs={'data-testid': 'article-body'})
        content_elements = article_body.find_all('p') if article_body else []
        full_content_paragraphs = [p.get_text(strip=True) for p in content_elements if p.get_text(strip=True)]
        full_content = "\n".join(full_content_paragraphs)

        if not full_content:
             print(f"Skipping (no content found): {url}")
             return None

        snippet = full_content[:200] + "..." if len(full_content) > 200 else full_content

        ticker_box = soup.find('div', class_="scroll-carousel yf-r5lvmz")
        tags_list = []
        if ticker_box:
            raw_text = ticker_box.get_text(separator=' ', strip=True)
            tags_list = filter_tickers(raw_text)

        return {
            "title": title,
            "url": url,
            "date": published_date,
            "author": author,
            "source": SOURCE_FULL,
            "content_snippet": snippet,
            "full_content": full_content,
            "tags": tags_list
        }

    except Exception as e:
        print(f"Error parsing article {url}: {e}")
        return None

def save_article(article_data: Dict[str, Any], root_dir: str) -> bool:
    try:
        date_obj = datetime.fromisoformat(article_data['date'].replace('Z', '+00:00'))
        year = str(date_obj.year)
        month = str(date_obj.month).zfill(2)
        day_str = date_obj.strftime("%Y%m%d")
    except ValueError:
        now = datetime.now()
        year, month = str(now.year), str(now.month).zfill(2)
        day_str = now.strftime("%Y%m%d")

    url_hash = get_md5_hash(article_data['url'])
    filename = f"{SOURCE_SHORT}-{day_str}-{url_hash}.json"

    save_dir = os.path.join(root_dir, "data", SOURCE_SHORT, year, month)
    os.makedirs(save_dir, exist_ok=True)

    file_path = os.path.join(save_dir, filename)

    if os.path.exists(file_path):
        return False

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(article_data, f, indent=4, ensure_ascii=False)
        print(f"Saved: {file_path}")
        return True
    except Exception as e:
        print(f"Error saving {filename}: {e}")
        return False

def main():
    root_dir = "."

    article_urls = scrape_article_links(BASE_URL, HEADERS)
    if not article_urls:
        print("No article links found.")
        return

    print(f"Processing {len(article_urls)} links...")
    new_count = 0

    with requests.Session() as session:
        for url in article_urls:
            article_data = scrape_article_page(session, url)
            if article_data:
                if save_article(article_data, root_dir):
                    new_count += 1
                else:
                    print(f"Duplicate skipped: {url}")
            
            time.sleep(random.uniform(0.5, 1.5))

    print(f"\nFinished. Saved {new_count} new articles.")

if __name__ == "__main__":
    main()