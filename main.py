import requests
import time
import random
from funcs import BASE_URL, HEADERS, scrape_article_links, scrape_article_page, save_article

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
                # Check if the article was saved successfully (i.e., not a duplicate)
                if save_article(article_data, root_dir):
                    new_count += 1
                else:
                    print(f"Duplicate skipped: {url}")
            
            # Introduce a random delay between requests
            time.sleep(random.uniform(0.5, 1.5))

    print(f"\nFinished. Saved {new_count} new articles.")

if __name__ == "__main__":
    main()