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
    """Fetch image URLs from the first page."""
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
            
            # Wait until at least some gallery items are available
            try:
                wait.until(lambda d: len(d.find_elements(By.CLASS_NAME, "gallery-item")) >= 5)
            except:
                print("Timeout waiting for items, proceeding with available.")
            
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            gallery_elements = soup.find_all('div', class_='gallery-item')
            
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
    
    # Apply CLAHE for contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)
    
    # Sharpen the image
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    sharpened = cv2.filter2D(enhanced, -1, kernel)
    
    # Adaptive threshold
    thresh = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    
    return Image.fromarray(thresh)

def clean_ocr_text(text):
    """Clean common OCR errors - less aggressive approach."""
    # Only fix obvious OCR errors
    text = text.replace('Il', '11').replace('|', '1')
    
    # Be very careful with letter/number replacements
    # Only replace when it's clearly wrong in context
    text = re.sub(r'([A-Za-z])0([A-Za-z])', r'\1o\2', text)  # o between letters
    text = re.sub(r'^0', 'O', text)  # O at start of line
    text = re.sub(r'([a-z])0', r'\1o', text)  # o after lowercase
    text = re.sub(r'0([a-z])', r'o\1', text)  # o before lowercase
    
    text = re.sub(r'([A-Z])1([A-Z])', r'\1l\2', text)  # l between uppercase
    text = re.sub(r'1([a-z])', r'l\1', text)  # l before lowercase
    
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)  # Remove non-ASCII
    text = re.sub(r'\s+', ' ', text)  # Normalize spaces
    return text.strip()

def extract_ebay_listings(image_url, img_id):
    """Extract eBay listings from the full image using simpler parsing."""
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        
        # Preprocess the image
        processed_img = preprocess_image(img)
        
        # Perform OCR with simpler config (removed problematic whitelist)
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(processed_img, config=custom_config)
        
        # Clean the text
        cleaned_text = clean_ocr_text(text)
        
        lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
        
        print(f"  OCR raw text: {text[:200]}...")
        print(f"  OCR cleaned text: {cleaned_text[:200]}...")
        print(f"  OCR: {len(lines)} lines")
        
        listings = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Look for sold date pattern
            sold_match = re.match(r'^Sold\s+([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})', line)
            if not sold_match:
                i += 1
                continue
            
            # Found a sold listing
            sold_date = sold_match.group(1)
            print(f"    Found sold date: {sold_date}")
            i += 1
            
            # Extract title - next non-empty line(s) until we hit a price
            title_lines = []
            while i < len(lines) and not re.match(r'^\$', lines[i]):
                current_line = lines[i].strip()
                # Skip condition lines and other metadata
                if not re.match(r'^(Brand New|Pre-Owned|New|Used|For parts|or Best Offer|Buy It Now|Located in|View similar|Sell one|Extra)', current_line, re.I):
                    if current_line and len(current_line) > 3:  # Minimum title length
                        title_lines.append(current_line)
                i += 1
            
            title = ' '.join(title_lines).strip()
            print(f"    Title: {title}")
            
            # Extract price - look for $ pattern
            price = None
            seller_id = None
            
            while i < len(lines) and (not price or not seller_id):
                current_line = lines[i]
                
                # Look for price
                if not price:
                    price_match = re.search(r'\$(\d+\.?\d{0,2})', current_line)
                    if price_match:
                        price = price_match.group(1)
                        print(f"    Price: ${price}")
                
                # Look for seller ID - alphanumeric with possible .-_ before percentage
                if not seller_id:
                    # Look for pattern: seller_id followed by percentage
                    seller_match = re.search(r'([a-zA-Z0-9._-]+)\s+\d+\.?\d*\s*%', current_line)
                    if seller_match:
                        seller_id = seller_match.group(1)
                        print(f"    Seller: {seller_id}")
                
                i += 1
                if i >= len(lines):
                    break
            
            # Only add if we have the essential fields
            if title and price:
                listing = {
                    'sold_date': sold_date,
                    'title': title,
                    'sold_price': price,
                    'seller_id': seller_id,
                    'url': image_url,
                    'timestamp': datetime.now().isoformat() + 'Z',
                    'publicId': img_id
                }
                listings.append(listing)
                print(f"    ✓ Saved listing")
            else:
                missing = []
                if not title: missing.append('title')
                if not price: missing.append('price')
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
                combo = f"{item.get('title', '')}|{item.get('sold_price', '')}|{item.get('seller_id', '')}"
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
                combo = f"{listing['title']}|{listing['sold_price']}|{listing.get('seller_id', '')}"
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
        print(f"\n✓ Added {len(new_listings)} new listings. Total: {len(all_listings)}")
        if duplicates > 0:
            print(f"  Skipped {duplicates} duplicates")
    else:
        print("\n✓ No new listings")
        if duplicates > 0:
            print(f"  Skipped {duplicates} duplicates")
    
    with open(output_json, 'w') as f:
        json.dump(all_listings, f, indent=2)
    
    print(f"✓ Saved to {output_json}")
    return len(new_listings) > 0

if __name__ == "__main__":
    updated = update_listings()
    if updated:
        print("\n✓ Ready for commit")
    else:
        print("\n✓ No changes")
