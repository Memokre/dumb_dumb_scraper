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

BASE_URL = "https://finance.yahoo.com/"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

HASH_FILE = 'scraped_article_hashes.json'
OUTPUT_FILE = 'yahoo_finance_articles.json'

def load_scraped_hashes(filename: str) -> Set[str]:
    """Loads a set of previously scraped hashes from a JSON file."""
    if not os.path.exists(filename):
        return set()
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            hashes = json.load(f)
            return set(hashes)
    except json.JSONDecodeError:
        print(f"Warning: Could not decode {filename}. Starting with empty hash set.")
        return set()

def save_scraped_hashes(filename: str, hashes: Set[str]):
    """Saves a set of hashes to a JSON file."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(list(hashes), f, indent=4)

def get_page_content(session: requests.Session, url: str) -> Optional[str]:
    """Fetches the HTML content of a given URL using our session."""
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

def scrape_article_page(session: requests.Session, url: str) -> Optional[Dict[str, str]]:

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
                if author_text:
                    author = author_text.strip()
                else:
                    full_text = author_container.get_text(strip=True)
                    if full_text:
                        author = full_text.split('<span')[0].strip()

        time_element = soup.select_one('div.byline-attr-time-style time.byline-attr-meta-time')
        updated_time = time_element['datetime'] if time_element and time_element.has_attr('datetime') else "Not Found"

        if title == "Not Found" and author == "Not Found":
             print(f"Skipping (likely not an article): {url}")
             return None

        return {
            "title": title,
            "author": author,
            "published_time_utc": updated_time,
            "article_link": url,
        }

    except Exception as e:
        print(f"Error parsing article {url}: {e}")
        return None

def main():
    """Main function to run the scraper."""
    
    scraped_hashes = load_scraped_hashes(HASH_FILE)
    print(f"Loaded {len(scraped_hashes)} previously scraped article hashes.")

    newly_scraped_data: List[Dict[str, str]] = []
    new_hashes: Set[str] = set()

    article_urls = scrape_article_links(BASE_URL, HEADERS)
    
    if not article_urls:
        print("No article links found. Exiting.")
        return

    print(f"\nProcessing {len(article_urls)} links...")

    with requests.Session() as session:
        for url in article_urls:
            link_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()
            if link_hash in scraped_hashes:
                continue

            print(f"Scraping new article: {url}")
            article_data = scrape_article_page(session, url)

            if article_data:

                article_data['article_link_hash'] = link_hash
                newly_scraped_data.append(article_data)
                new_hashes.add(link_hash)
            
            time.sleep(random.uniform(0.5, 1.5)) 
    if newly_scraped_data:
        print(f"\nScraped {len(newly_scraped_data)} new articles.")
        
        all_data = []
        if os.path.exists(OUTPUT_FILE):
            try:
                with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                    all_data = json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Could not parse {OUTPUT_FILE}, overwriting.")
        
        all_data.extend(newly_scraped_data)
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=4, ensure_ascii=False)
        print(f"Successfully saved new articles to {OUTPUT_FILE}")

        updated_hashes = scraped_hashes.union(new_hashes)
        save_scraped_hashes(HASH_FILE, updated_hashes)
        print(f"Updated hash database {HASH_FILE} with {len(new_hashes)} new hashes.")
    else:
        print("\nNo new articles were scraped in this run.")

if __name__ == "__main__":
    main()