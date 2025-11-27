import re
import json
import hashlib
import os
import sys
import time
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from datetime import datetime

try:
    from playwright.sync_api import Page
except ImportError:
    pass

BASE_URL = "https://finance.yahoo.com/"
SOURCE_SHORT = "yahoo"
SOURCE_FULL = "finance.yahoo.com"

def get_md5_hash(url: str) -> str:
    return hashlib.md5(url.encode('utf-8')).hexdigest()[-8:]

def filter_tickers(raw_text: str) -> list[str]:
    ticker_pattern = re.compile(r'\b[A-Z]{1,5}(?:\.[A-Z]{1,2})?\b')
    potential_tickers = ticker_pattern.findall(raw_text)
    return sorted(list(set(potential_tickers)))

def extract_financial_metrics(content: str) -> dict[str, list[str]]:
    percent_pattern = re.compile(r'([+-]?\s*\d{1,3}(?:\.\d+)?)\s*%')
    dollar_pattern = re.compile(r'\$[,\d]{1,16}\.\d{2}\b')
    acronym_pattern = re.compile(r'\b(GDP|CPI|Fed|IPO|M&A|CEO|CFO|EPS|EBITDA|S&P|Q\d)\b')
    
    percentages = [match.group(1).strip() for match in percent_pattern.finditer(content)]
    dollars = dollar_pattern.findall(content)
    acronyms = acronym_pattern.findall(content)

    return {
        "percentages": percentages,
        "dollar_values": dollars,
        "acronyms": acronyms
    }

def get_page_content(page: 'Page', url: str) -> Optional[str]:
    try:
        page.goto(url, timeout=60000)
        page.wait_for_load_state('domcontentloaded') 
        return page.content()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def scrape_article_links(page: 'Page', base_url: str) -> set[str]:
    try:
        if page.url != base_url:
            page.goto(base_url, timeout=60000)
            page.wait_for_load_state('domcontentloaded')
        
        print("Scrolling to trigger News Stream lazy loading...")
        try:
            for i in range(5):
                page.keyboard.press("PageDown")
                time.sleep(1.5)
            
            page.keyboard.press("End")
            time.sleep(2)

            page.wait_for_selector('li.stream-item', state="attached", timeout=20000)
        except Exception as e:
            print(f"Warning: Scrolling/Waiting for news stream failed: {e}")

        html_content = page.content()
    except Exception as e:
        print(f"Error: Could not retrieve the webpage. {e}", file=sys.stderr)
        return set()

    soup = BeautifulSoup(html_content, 'html.parser')
    unique_urls = set()

    target_section = soup.find('section', class_='module-hero')
    
    if target_section:
        links = target_section.find_all('a', href=True)
        for link in links:
            href = link['href']
            absolute_url = urljoin(base_url, href)
            if '/news/' in absolute_url:
                cleaned_url = absolute_url.split('?')[0]
                unique_urls.add(cleaned_url)
    
    print(f"Found {len(unique_urls)} links in Hero section.")

    news_stream = soup.find('div', attrs={'data-testid': 'news-stream'})

    if news_stream:
        stream_items = news_stream.find_all('li', class_='stream-item')
        print(f"Found {len(stream_items)} items in News Stream.")

        for item in stream_items:
            link = item.find('a', href=True)
            if link:
                href = link['href']
                absolute_url = urljoin(base_url, href)
                
                # Blacklist check
                if "noisefreefinance.com" in absolute_url:
                    continue

                if '/news/' in absolute_url or '/m/' in absolute_url:
                    cleaned_url = absolute_url.split('?')[0]
                    unique_urls.add(cleaned_url)

    print(f"Total unique article links found: {len(unique_urls)}")
    return unique_urls

def scrape_article_page(page: 'Page', url: str) -> Optional[Dict[str, Any]]:
    html_content = get_page_content(page, url)
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
            tags_list.extend(filter_tickers(raw_text))

        metrics = extract_financial_metrics(full_content)
        
        tags_list.extend([f"PCT:{p}" for p in metrics["percentages"]])
        tags_list.extend([f"USD:{d}" for d in metrics["dollar_values"]])
        tags_list.extend([f"ACR:{a}" for a in metrics["acronyms"]])

        tags_list = sorted(list(set(tags_list)))

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