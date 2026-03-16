"""
Platform-Agnostic Fake Review Detection Web Application
Scraping Module

Developed for Team: Akshitha, Poojitha, Zeeshan, and Manmath
"""

import random
import time
import asyncio
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

class GhostScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless

    async def _human_mimicry_scroll(self, page) -> None:
        """
        Simulate human-like gradual scrolling with random pauses
        to bypass basic anti-bot security.
        """
        body_exists = await page.evaluate("document.body !== null")
        if not body_exists:
            return
            
        scroll_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = await page.evaluate("window.innerHeight")
        current_scroll = 0

        while current_scroll < scroll_height:
            # Scroll down by a random fraction of the viewport height
            scroll_step = random.uniform(0.3, 0.8) * viewport_height
            current_scroll += scroll_step
            
            await page.evaluate(f"window.scrollTo(0, {current_scroll})")
            
            # Random delay between scrolls
            await asyncio.sleep(random.uniform(0.5, 2.0))
            
            # Update scroll_height in case of infinite scroll loaders
            body_exists = await page.evaluate("document.body !== null")
            if body_exists:
                new_scroll_height = await page.evaluate("document.body.scrollHeight")
                if new_scroll_height > scroll_height:
                    scroll_height = new_scroll_height
            else:
                break

    def extract_reviews(self, html_content: str) -> List[Dict[str, Any]]:
        """
        Use BeautifulSoup4 for DOM analysis to extract reviews.
        Note: Exact selectors will vary by platform.
        This provides a generic fallback approach with JSON-LD.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        reviews = []
        
        # 0. Platform-Agnostic JSON-LD Schema Extraction
        # Many modern e-commerce sites use Schema.org which is highly robust
        # Expanded to support Product, LocalBusiness, Hotel, Restaurant, and standalone Reviews
        valid_schema_types = {'Product', 'LocalBusiness', 'Hotel', 'Restaurant', 'Organization', 'Service', 'TravelAgency', 'TouristAttraction', 'LodgingBusiness'}
        
        def extract_from_jsonld_obj(obj):
            extracted = []
            # If the object itself is a Review
            if obj.get('@type') == 'Review':
                body = obj.get('reviewBody') or obj.get('description')
                if body:
                    rating = obj.get('reviewRating', {}).get('ratingValue')
                    extracted.append({
                        "id": len(extracted),
                        "text": body.strip(),
                        "rating_raw": str(rating) if rating else None,
                        "timestamp": obj.get('datePublished'),
                    })
            # If the object contains a list of reviews
            elif obj.get('@type') in valid_schema_types and 'review' in obj:
                reviews_data = obj['review']
                if isinstance(reviews_data, dict):
                    reviews_data = [reviews_data] # Sometimes it's a single dict instead of list
                for idx, review in enumerate(reviews_data):
                    body = review.get('reviewBody') or review.get('description')
                    if body:
                        rating = review.get('reviewRating', {}).get('ratingValue')
                        extracted.append({
                            "id": idx,
                            "text": body.strip(),
                            "rating_raw": str(rating) if rating else None,
                            "timestamp": review.get('datePublished'),
                        })
            return extracted

        for script_tag in soup.find_all('script', type='application/ld+json'):
            try:
                import json
                data = json.loads(script_tag.string)
                if isinstance(data, list):
                    for item in data:
                        reviews.extend(extract_from_jsonld_obj(item))
                elif isinstance(data, dict):
                    # Sometimes the main schema is a dict that contains a 'mainEntity' or '@graph'
                    if '@graph' in data:
                        for item in data['@graph']:
                            reviews.extend(extract_from_jsonld_obj(item))
                    else:
                        reviews.extend(extract_from_jsonld_obj(data))
            except Exception as e:
                print(f"Failed to parse JSON-LD: {e}")
                
        # If JSON-LD provided reviews, return them as they are the most reliable
        if reviews:
            # deduplicate by text
            seen = set()
            unique_reviews = []
            for r in reviews:
                if r['text'] not in seen:
                    seen.add(r['text'])
                    unique_reviews.append(r)
            return unique_reviews

        # 1. Broad approach: Generic review blocks
        # Added broad classes to cover Nykaa, Myntra, Google Maps, MakeMyTrip, RedBus, etc.
        review_class_keywords = ['review', 'comment', 'testimonial', 'feedback', 'user-review', 'customer-review']
        platform_specific_classes = [
            'col _2wzg', 'z9e2', # Flipkart Old
            'wiI7pd', 'MyEned', 'OA1nbd', # Google Maps
            'review-text', 'review-card', # Nykaa / Myntra
            'rvw-cnt', 'review-content', # General Travel
            'user-review-desc' # RedBus
        ]
        
        def is_review_block(c):
            if not c:
                return False
            c_lower = c.lower()
            return any(k in c_lower for k in review_class_keywords) or any(k.lower() in c_lower for k in platform_specific_classes)

        possible_review_blocks = soup.find_all(['div', 'article', 'section', 'li'], class_=is_review_block)
        
        # 2. Hardcoded fallbacks
        if not possible_review_blocks:
             possible_review_blocks = soup.select('div.col._2wzg32, div.ZmyqYM, div.EKFha-, div.RcXBOT, span.wiI7pd, div.MyEned')
             
        # Add exact Amazon matches
        amazon_blocks = soup.select('div[data-hook="review"]')
        for b in amazon_blocks:
            if b not in possible_review_blocks:
                possible_review_blocks.append(b)

        for idx, block in enumerate(possible_review_blocks):
            # Attempt to extract text
            text_element = block.find(attrs={"data-hook": "review-body"}) # Amazon
            if not text_element:
                 text_element = block.find(['p', 'span', 'div'], class_=lambda c: c and any(k in c.lower() for k in ['text', 'body', 'desc', 'content', 'z9e2', 'wiI7pd']))
            if not text_element:
                 text_element = block.find('div', class_='ZmyqYM') # Flipkart specific
            
            # If no specific text container is found, use the block itself if it has enough text
            review_text = text_element.get_text(strip=True) if text_element else block.get_text(separator=' ', strip=True)

            # Attempt to extract star rating (common pattern: '5 stars' or aria-label)
            rating = None
            rating_element = block.find(lambda tag: tag.has_attr('aria-label') and 'star' in tag['aria-label'].lower())
            if rating_element:
                rating = rating_element['aria-label']
                
            # Attempt to extract timestamp
            date_element = block.find(['span', 'time', 'div'], class_=lambda c: c and any(k in c.lower() for k in ['date', 'time', 'ago']))
            timestamp = date_element.get_text(strip=True) if date_element else None

            # Stricter heuristic: if we used the whole block text, make sure it's long enough and lacks excessive links
            if len(review_text) > 30:
                reviews.append({
                    "id": idx,
                    "text": review_text,
                    "rating_raw": rating,
                    "timestamp": timestamp,
                })
                
        # Deduplicate
        seen = set()
        unique_reviews = []
        for r in reviews:
            if r['text'] not in seen:
                seen.add(r['text'])
                unique_reviews.append(r)
        return unique_reviews

    async def scrape_url(self, url: str) -> List[Dict[str, Any]]:
        reviews: List[Dict[str, Any]] = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                page = await context.new_page()
                
                from playwright_stealth import stealth_async
                await stealth_async(page)
                
                try:
                    await asyncio.sleep(random.uniform(1.0, 3.0))
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    
                    if 'amazon.' in url:
                        try:
                            see_all_link = await page.locator("a[data-hook='see-all-reviews-link-foot']").get_attribute('href', timeout=5000)
                            if see_all_link:
                                await page.goto(f"https://www.amazon.in{see_all_link}", wait_until="domcontentloaded", timeout=60000)
                        except:
                            pass
                    
                    await self._human_mimicry_scroll(page)
                    await asyncio.sleep(random.uniform(7.0, 10.0)) 
        
                    try:
                          await page.wait_for_selector('div[data-hook="review"]', timeout=20000)
                    except:
                          print("Timeout waiting for reviews.")
                    
                    html_content = await page.content()
                    reviews = self.extract_reviews(html_content)
                    
                except Exception as e:
                    print(f"Error scraping {url}: {e}")
                finally:
                    await browser.close()
        except Exception as e:
            print(f"Playwright error: {e}")
            
        return reviews
              
               
          

# Optional: Run directly for testing
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
        scraper = GhostScraper(headless=False)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        extracted = loop.run_until_complete(scraper.scrape_url(test_url))
        print(f"Extracted {len(extracted)} reviews.")
        limit = min(3, len(extracted))
        for i in range(limit):
            print(extracted[i])
