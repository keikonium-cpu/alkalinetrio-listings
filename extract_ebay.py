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
import requests
from io import BytesIO
from PIL import Image
import pytesseract
import cv2
import numpy as np

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
            wait = WebDriverWait(driver, 60)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gallery-item")))
            time.sleep(10)
            
            try:
                wait.until(lambda d: len(d.find_elements(By.CLASS_NAME, "gallery-item")) >= 10)
            except:
                print("Timeout waiting for 10 items, proceeding with available.")
            
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            gallery_elements = soup.find_all('div', class_='gallery-item', limit=10)
            
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

def preprocess_image(image):
    """Preprocess image for better OCR accuracy."""
    img_array = np.array(image)
    gray = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
    
    # Enhance contrast
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)
    
    # Threshold
    thresh = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    
    return Image.fromarray(thresh)

def clean_ocr_text(text):
    """Minimal cleaning to preserve original text."""
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)  # Remove non-ASCII
    text = re.sub(r'\s+', ' ', text)  # Normalize spaces
    return text.strip()

def extract_ebay_listings(image_url, img_id):
    """Extract eBay listings from the full image."""
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        # Preprocess the image
        processed_img = preprocess_image(img)
        
        # Perform OCR
        custom_config = r'--oem 3 --psm 6'  # Assume a uniform block of text
        text = pytesseract.image_to_string(processed_img, config=custom_config)
        cleaned_text = clean_ocr_text(text)
        
        print(f"  OCR raw text: {text}")
        print(f"  OCR cleaned text: {cleaned_text}")
        print(f"  OCR lines: {cleaned_text.split('\n')}")
        
        listings = []
        
        # Split into lines for parsing
        lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Match sold date
            date_match = re.match(r'^Sold\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}', line, re.I)
            if not date_match:
                i += 1
                continue
            
            listing = {
                'sold_date': line,
                'title': '',
                'sold_price': None,
                'seller_id': None,
                'url': image_url,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'publicId': img_id
            }
            
            print(f"    [Date] {line}")
            i += 1
            
            # Extract title until price line
            title_lines = []
            while i < len(lines):
                cur = lines[i]
                price_match = re.match(r'^\$\d+[\d,.]*', cur)
                if price_match:
                    break
                if cur and not re.match(r'^(Located|View|Sell|or Best|Buy It Now|\+\$|\d+\s*(bid|watcher))', cur, re.I):
                    title_lines.append(cur)
                i += 1
            listing['title'] = ' '.join(title_lines).strip()
            print(f"    [Title] {listing['title']}")
            
            # Extract price and seller from the price line
            if i < len(lines):
                cur = lines[i]
                price_match = re.search(r'^\$(\d+[\d,.]*)', cur)
                if price_match:
                    listing['sold_price'] = price_match.group(1)
                    print(f"    [Price] ${listing['sold_price']}")
                
                # Extract seller (text after price until percentage)
                seller_match = re.search(r'(\w[\w.-]*)\s+(\d+(?:\.\d+)?)\s*%', cur)
                if seller_match:
                    listing['seller_id'] = seller_match.group(1)
                    print(f"    [Seller] {listing['seller_id']}")
                i += 1
            
            if listing['title'] and listing['sold_price']:
                listings.append(listing)
                print(f"    ✓ Saved")
            else:
                missing = []
                if not listing['title']:
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
    output_dir = 'data'
    output_json = os.path.join(output_dir, 'ebaylistings.json')
    
    os.makedirs(output_dir, exist_ok=True)
    
    existing_ids = set()
    all_listings = []
    existing_combos = set()
    
    if os.path.exists(output_json):
        with open(output_json, 'r') as f:
            data = json.load(f)
            all_listings = data
            existing_ids = {item.get('publicId', '') for item in data}
            for item in data:
                combo = f"{item.get('title', '')}|{item.get('sold_price', '')}"
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
            listings = extract_ebay_listings(img_url, img_id)
            for listing in listings:
                combo = f"{listing['title']}|{listing['sold_price']}"
                if combo in existing_combos:
                    duplicates += 1
                    print(f"    ⚠ Duplicate skipped")
                    continue
                
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
    
    print(f"✓ Saved to {output_json}")
    return len(new_listings) > 0

if __name__ == "__main__":
    updated = update_listings()
    if updated:
        print("\n✓ Ready for commit")
    else:
        print("\n✓ No changes")
