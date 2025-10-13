import json
import re
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time

def fetch_all_image_urls(base_url):
    """Fetch image URLs from the first page, limited to the first 10 images for testing."""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=chrome_options)
        
        all_image_urls = {}
        page = 1
        
        url = f"{base_url}?page={page}"
        print(f"Loading page {page}: {url}")
        driver.get(url)
        
        try:
            wait = WebDriverWait(driver, 30)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gallery-item")))
            time.sleep(2)
            
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            gallery_elements = soup.find_all('div', class_='gallery-item', limit=10)  # Limit to first 10 images
            
            if len(gallery_elements) == 0:
                print(f"No gallery items found on page {page}. Stopping.")
                return {}
            
            page_images = {}
            for gallery in gallery_elements:
                img_id = gallery.get('data-id')
                img_tag = gallery.find('img')
                src = img_tag.get('src') if img_tag else None
                if img_id and src:
                    page_images[img_id] = src
            
            print(f"Page {page}: Found {len(page_images)} images")
            all_image_urls.update(page_images)
            
        except Exception as e:
            print(f"Error on page {page}: {e}")
        
        driver.quit()
        print(f"Total images collected: {len(all_image_urls)}")
        return all_image_urls
        
    except Exception as e:
        print(f"Error fetching image URLs: {e}")
        try:
            driver.quit()
        except:
            pass
        return {}

def extract_ebay_listings(image_url):
    """Extract eBay listings from the full image."""
    try:
        import requests
        from io import BytesIO
        from PIL import Image
        import pytesseract
        
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        # Removed cropping, process full image
        text = pytesseract.image_to_string(img)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        print(f"  OCR: {len(lines)} lines")
        
        listings = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Find date
            dm = re.match(r'^(Sold|Ended)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}', line, re.I)
            if not dm:
                i += 1
                continue
            
            listing = {
                'status': dm.group(1).capitalize(),
                'date': line,
                'listing_title': '',
                'sold_price': None,
                'seller': None
            }
            
            print(f"    [{listing['status']}] {line}")
            i += 1
            
            # Extract title
            title_parts = []
            while i < len(lines) and len(title_parts) < 5:
                cur = lines[i]
                
                # Stop at condition
                if re.match(r'^(Brand New|Pre-Owned|New with tags|Open box|Used|For parts)$', cur, re.I):
                    print(f"      Condition: {cur}")
                    i += 1
                    break
                # Stop at price
                if re.match(r'^\$\d+', cur):
                    print(f"      Price line: {cur}")
                    break
                # Skip junk
                if re.match(r'^(\d+\s*(bid|watcher)|or Best|Buy It Now|Located|View|Sell|Free|Watch|\+\$)', cur, re.I):
                    i += 1
                    continue
                
                # Valid title
                if len(cur) > 2 and re.search(r'[a-zA-Z]{3,}', cur):
                    title_parts.append(cur)
                    print(f"      Title: {cur}")
                
                i += 1
            
            listing['listing_title'] = ' '.join(title_parts).strip()
            
            # Extract price
            for _ in range(8):
                if i >= len(lines):
                    break
                cur = lines[i]
                pm = re.search(r'\$(\d+[\d,]*\.?\d{0,2})', cur)
                if pm:
                    listing['sold_price'] = f"${pm.group(1)}"
                    print(f"      Price: {listing['sold_price']}")
                    i += 1
                    break
                i += 1
            
            # Extract seller
            for _ in range(8):
                if i >= len(lines):
                    break
                cur = lines[i]
                
                # Stop if next listing
                if re.match(r'^(Sold|Ended)\s+', cur, re.I):
                    break
                
                # Pattern 1: username with percentage on same line
                sm = re.search(r'([a-zA-Z0-9_-]+)\s+(\d+\.?\d*)\s*%', cur, re.I)
                if sm:
                    seller = sm.group(1)
                    # Clean common OCR errors
                    seller = re.sub(r'^(Pre|Brand|New|Ouinect|Oninect)', '', seller, flags=re.I)
                    if len(seller) > 2:
                        listing['seller'] = seller
                        print(f"      Seller: {listing['seller']}")
                        i += 1
                        break
                
                # Pattern 2: username on one line, percentage on next
                username_pattern = r'^[a-zA-Z][a-zA-Z0-9_-]{2,}$'
                if re.match(username_pattern, cur):
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        if re.search(r'^\d+\.?\d*\s*%', next_line):
                            listing['seller'] = cur
                            print(f"      Seller: {listing['seller']}")
                            i += 2
                            break
                
                i += 1
            
            # Save if valid
            if listing['listing_title'] and listing['sold_price']:
                listing['listing_title'] = re.sub(r'\s{2,}', ' ', listing['listing_title']).strip()
                listings.append(listing)
                print(f"    ✓ Saved")
            else:
                missing = []
                if not listing['listing_title']:
                    missing.append('title')
                if not listing['sold_price']:
                    missing.append('price')
                print(f"    ✗ Missing: {', '.join(missing)}")
        
        print(f"  ✓ Found {len(listings)} listings")
        return listings
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def update_listings():
    """Main function."""
    base_url = 'http://www.alkalinetrioarchive.com/sales.html'
    output_json = 'ebaylistings.json'
    
    existing_ids = set()
    all_listings = []
    existing_combos = set()
    
    if os.path.exists(output_json):
        with open(output_json, 'r') as f:
            data = json.load(f)
            all_listings = data
            existing_ids = {item.get('image_id', '') for item in data}
            for item in data:
                combo = f"{item.get('listing_title', '')}|{item.get('sold_price', '')}"
                existing_combos.add(combo)
    
    print(f"Loaded {len(all_listings)} existing listings\n")
    
    image_urls = fetch_all_image_urls(base_url)
    print(f"\nFound {len(image_urls)} images\n")
    
    new_listings = []
    processed = 0
    skipped = 0
    duplicates = 0
    
    for img_id, img_url in image_urls.items():
        if img_id not in existing_ids:
            processed += 1
            print(f"[{processed}] Processing: {img_id}")
            listings = extract_ebay_listings(img_url)
            for listing in listings:
                combo = f"{listing['listing_title']}|{listing['sold_price']}"
                if combo in existing_combos:
                    duplicates += 1
                    print(f"    ⚠ Duplicate skipped")
                    continue
                
                listing['image_id'] = img_id
                listing['processed_at'] = datetime.now().isoformat()
                new_listings.append(listing)
                existing_combos.add(combo)
            existing_ids.add(img_id)
        else:
            skipped += 1
            if skipped % 10 == 0:
                print(f"[Skipped {skipped}...]")
    
    if new_listings:
        all_listings.extend(new_listings)
        print(f"\n✓ Added {len(new_listings)} new. Total: {len(all_listings)}")
        if duplicates > 0:
            print(f"  Skipped {duplicates} duplicates")
    else:
        print("\n✓ No new listings")
        if duplicates > 0:
            print(f"  Skipped {duplicates} duplicates")
    
    with open(output_json, 'w') as f:
        json.dump(all_listings, f, indent=4)
    
    print(f"✓ Saved")
    return len(new_listings) > 0

if __name__ == "__main__":
    updated = update_listings()
    if updated:
        print("\n✓ Ready for commit")
    else:
        print("\n✓ No changes")
