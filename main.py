import sys
import subprocess
import time
import random
import importlib.util
from playwright.sync_api import sync_playwright, Error as PlaywrightError
from funcs import BASE_URL, scrape_article_links, scrape_article_page, save_article

def ensure_browsers_installed():
    try:
        print("Installing Chromium...")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    except Exception as e:
        print(f"Failed to install browsers: {e}")
        sys.exit(1)

def handle_cookie_popup(page, url):
    """
    Navigates to the URL and handles the Yahoo cookie consent popup.
    """
    print(f"Navigating to {url} to check for cookies...")
    try:
        page.goto(url, timeout=60000)
        # Wait a moment for the redirect to consent.yahoo.com or popup to render
        page.wait_for_load_state('domcontentloaded')
        time.sleep(2)

        # Look for the "Accept all" button (common on Yahoo consent pages)
        # We try multiple selectors to be robust
        accept_button = page.locator('button[name="agree"], button:has-text("Accept all")').first
        reject_button = page.locator('button[name="reject"], button:has-text("Reject all")').first

        if accept_button.is_visible():
            print("Cookie consent popup detected. Clicking 'Accept all'...")
            accept_button.click()
            # Removed strict networkidle wait; relying on sleep allows the redirect to process without timeout
            time.sleep(3) 
        elif reject_button.is_visible():
            print("Cookie consent popup detected. Clicking 'Reject all'...")
            reject_button.click()
            time.sleep(3)
        else:
            print("No obvious cookie popup found (or already accepted).")

    except Exception as e:
        print(f"Warning: Attempted to handle cookies but encountered an issue: {e}")

def main():
    root_dir = "."
    
    if importlib.util.find_spec("playwright") is None:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])

    with sync_playwright() as p:
        try:
            # Headless True to hide the browser window
            browser = p.chromium.launch(headless=True)
        except PlaywrightError as e:
            if "Executable doesn't exist" in str(e):
                ensure_browsers_installed()
                browser = p.chromium.launch(headless=True)
            else:
                raise e

        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
        page = context.new_page()

        # Handle cookies explicitly before trying to scrape
        handle_cookie_popup(page, BASE_URL)

        article_urls = scrape_article_links(page, BASE_URL)
        
        if not article_urls:
            print("No article links found.")
            browser.close()
            return

        print(f"Processing {len(article_urls)} links...")
        new_count = 0

        for url in article_urls:
            article_data = scrape_article_page(page, url)
            
            if article_data:
                if save_article(article_data, root_dir):
                    new_count += 1
                else:
                    print(f"Duplicate skipped: {url}")
            
            time.sleep(random.uniform(0.5, 1.5))

        browser.close()

    print(f"\nFinished. Saved {new_count} new articles.")

if __name__ == "__main__":
    main()