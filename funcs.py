import re
import json
import hashlib
import os
import sys
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from datetime import datetime

# Type hinting for Playwright
try:
    from playwright.sync_api import Page
except ImportError:
    pass

BASE_URL = "https://finance.yahoo.com/"
SOURCE_SHORT = "yahoo"
SOURCE_FULL = "finance.yahoo.com"

# HEADERS removed as they are set in the Playwright context in main.py

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

# Modified to use Playwright Page object
def get_page_content(page: 'Page', url: str) -> Optional[str]:
    try:
        page.goto(url, timeout=60000)
        # Wait for DOM to settle - crucial for dynamic scraping
        page.wait_for_load_state('domcontentloaded') 
        return page.content()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

# Modified to accept Page object
def scrape_article_links(page: 'Page', base_url: str) -> set[str]:
    try:
        page.goto(base_url, timeout=60000)
        page.wait_for_load_state('domcontentloaded')
        html_content = page.content()
    except Exception as e:
        print(f"Error: Could not retrieve the webpage. {e}", file=sys.stderr)
        return set()

    soup = BeautifulSoup(html_content, 'html.parser')
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

# Modified to accept Page object
def scrape_article_page(page: 'Page', url: str) -> Optional[Dict[str, Any]]:
    # Uses the shared Playwright get_page_content wrapper
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