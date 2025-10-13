import pytesseract
from PIL import Image
import cv2
import numpy as np
import requests
from io import BytesIO
import json
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Optional
import time
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('extraction.log'),
        logging.StreamHandler()
    ]
)

class TesseractEbayExtractor:
    def __init__(self, output_file: str = "data/EbayListings.json"):
        self.output_file = output_file
        self.results = []
        self.seen_hashes = set()
        self.error_count = 0
        self.duplicate_count = 0
        
        # Create output directory if it doesn't exist
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing data if available
        self._load_existing_data()
    
    def _load_existing_data(self):
        """Load existing JSON data to avoid reprocessing"""
        try:
            if Path(self.output_file).exists():
                with open(self.output_file, 'r', encoding='utf-8') as f:
                    self.results = json.load(f)
                    # Build hash set from existing data
                    for item in self.results:
                        if 'image_hash' in item:
                            self.seen_hashes.add(item['image_hash'])
                logging.info(f"Loaded {len(self.results)} existing records")
        except Exception as e:
            logging.error(f"Error loading existing data: {e}")
            self.results = []
    
    def compute_image_hash(self, image_url: str) -> str:
        """Generate hash for duplicate detection"""
        return hashlib.md5(image_url.encode()).hexdigest()
    
    def extract_ebay_listings(self, image_url: str, item_id: str) -> List[Dict]:
        """Extract eBay listings from image using improved OCR."""
        listings = []
        
        try:
            # Download image
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            
            # No cropping - these are already individual listing screenshots
            # Perform OCR directly on the full image
            text = pytesseract.image_to_string(img)
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            
            logging.info(f"  OCR extracted {len(lines)} lines")
            
            i = 0
            while i < len(lines):
                line = lines[i]
                
                # Find date pattern (Sold/Ended + Date)
                date_match = re.match(
                    r'^(Sold|Ended)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}',
                    line,
                    re.I
                )
                
                if not date_match:
                    i += 1
                    continue
                
                # Start building a listing
                listing = {
                    'item_id': item_id,
                    'status': date_match.group(1).capitalize(),
                    'sold_date': line,
                    'listing_title': '',
                    'sold_price': None,
                    'seller': None,
                    'processed_at': datetime.now().isoformat()
                }
                
                logging.info(f"    [{listing['status']}] {line}")
                i += 1
                
                # Extract title (next 1-5 lines until condition/price)
                title_parts = []
                while i < len(lines) and len(title_parts) < 5:
                    cur = lines[i]
                    
                    # Stop at condition keywords
                    if re.match(r'^(Brand New|Pre-Owned|New with tags|Open box|Used|For parts)$', cur, re.I):
                        logging.info(f"      Condition: {cur}")
                        i += 1
                        break
                    
                    # Stop at price
                    if re.match(r'^\$\d+', cur):
                        logging.info(f"      Price line: {cur}")
                        break
                    
                    # Skip common non-title lines
                    if re.match(r'^(\d+\s*(bid|watcher)|or Best|Buy It Now|Located|View|Sell|Free|Watch|\+\$)', cur, re.I):
                        i += 1
                        continue
                    
                    # Valid title line (has substantial text)
                    if len(cur) > 2 and re.search(r'[a-zA-Z]{3,}', cur):
                        title_parts.append(cur)
                        logging.info(f"      Title: {cur}")
                    
                    i += 1
                
                listing['listing_title'] = ' '.join(title_parts).strip()
                
                # Extract price (search next 8 lines)
                for _ in range(8):
                    if i >= len(lines):
                        break
                    cur = lines[i]
                    price_match = re.search(r'\$(\d+[\d,]*\.?\d{0,2})', cur)
                    if price_match:
                        listing['sold_price'] = f"${price_match.group(1)}"
                        logging.info(f"      Price: {listing['sold_price']}")
                        i += 1
                        break
                    i += 1
                
                # Extract seller (search next 8 lines)
                for _ in range(8):
                    if i >= len(lines):
                        break
                    cur = lines[i]
                    
                    # Stop if next listing starts
                    if re.match(r'^(Sold|Ended)\s+', cur, re.I):
                        break
                    
                    # Pattern 1: username with percentage on same line
                    seller_match = re.search(r'([a-zA-Z0-9_-]+)\s+(\d+\.?\d*)\s*%', cur, re.I)
                    if seller_match:
                        seller = seller_match.group(1)
                        # Clean common OCR errors
                        seller = re.sub(r'^(Pre|Brand|New|Ouinect|Oninect)', '', seller, flags=re.I)
                        if len(seller) > 2:
                            listing['seller'] = seller
                            logging.info(f"      Seller: {listing['seller']}")
                            i += 1
                            break
                    
                    # Pattern 2: username on one line, percentage on next
                    username_pattern = r'^[a-zA-Z][a-zA-Z0-9_-]{2,}$'
                    if re.match(username_pattern, cur):
                        if i + 1 < len(lines):
                            next_line = lines[i + 1]
                            if re.search(r'^\d+\.?\d*\s*%', next_line):
                                listing['seller'] = cur
                                logging.info(f"      Seller: {listing['seller']}")
                                i += 2
                                break
                    
                    i += 1
                
                # Save if valid (has title and price)
                if listing['listing_title'] and listing['sold_price']:
                    # Clean up title whitespace
                    listing['listing_title'] = re.sub(r'\s{2,}', ' ', listing['listing_title']).strip()
                    listings.append(listing)
                    logging.info(f"    ✓ Saved listing")
                else:
                    missing = []
                    if not listing['listing_title']:
                        missing.append('title')
                    if not listing['sold_price']:
                        missing.append('price')
                    logging.info(f"    ✗ Missing: {', '.join(missing)}")
            
            logging.info(f"  ✓ Found {len(listings)} listings")
            return listings
            
        except Exception as e:
            logging.error(f"  ✗ Error extracting from {item_id}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def extract_from_image_url(self, image_url: str, item_id: str) -> Optional[Dict]:
        """Process a single image and extract all listings from it"""
        image_hash = self.compute_image_hash(image_url)
        
        # Check for duplicates
        if image_hash in self.seen_hashes:
            logging.info(f"Skipping duplicate: {item_id}")
            self.duplicate_count += 1
            return None
        
        # Extract listings from this image
        listings = self.extract_ebay_listings(image_url, item_id)
        
        # Mark as seen
        self.seen_hashes.add(image_hash)
        
        # Return a summary record for this image
        result = {
            'item_id': item_id,
            'image_url': image_url,
            'image_hash': image_hash,
            'success': len(listings) > 0,
            'listings_found': len(listings),
            'listings': listings,
            'processed_at': datetime.now().isoformat()
        }
        
        if len(listings) == 0:
            result['error'] = 'No listings extracted'
            self.error_count += 1
        
        return result
    
    def load_from_json(self, json_file: str) -> List[Dict[str, str]]:
        """Load image URLs directly from eBaySales.json"""
        logging.info(f"Loading images from JSON file: {json_file}")
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            images = []
            
            # Handle paginated structure
            if 'pages' in data:
                for page in data['pages']:
                    for img_data in page.get('images', []):
                        item_id = img_data.get('publicId')
                        url = img_data.get('url')
                        
                        if item_id and url and 'cloudinary' in url:
                            images.append({
                                'item_id': item_id,
                                'image_url': url
                            })
            # Handle flat structure
            elif isinstance(data, list):
                for img_data in data:
                    item_id = img_data.get('publicId')
                    url = img_data.get('url')
                    
                    if item_id and url and 'cloudinary' in url:
                        images.append({
                            'item_id': item_id,
                            'image_url': url
                        })
            
            logging.info(f"Loaded {len(images)} images from JSON")
            return images
            
        except Exception as e:
            logging.error(f"Error loading JSON file: {e}")
            return []
    
    def process_from_json(self, json_file: str, delay: float = 1.0, retry_errors: bool = True, max_images: any = "all"):
        """Process images from eBaySales.json file"""
        images = self.load_from_json(json_file)
        
        if not images:
            logging.error("No images found in JSON file")
            self._save_results()
            return
        
        self._process_images(images, delay, retry_errors, max_images)
    
    def _process_images(self, images: List[Dict[str, str]], delay: float, retry_errors: bool, max_images: any = "all"):
        """Common processing logic for images"""
        # Determine how many images to process
        total_available = len(images)
        
        if max_images == "all":
            images_to_process = images
            logging.info(f"Processing ALL {total_available} images...")
        else:
            max_count = int(max_images)
            images_to_process = images[:max_count]
            logging.info(f"Processing {len(images_to_process)} images (limited from {total_available} total)...")
        
        # Process each image
        for i, img_data in enumerate(images_to_process):
            try:
                logging.info(f"\n[{i+1}/{len(images_to_process)}] Processing: {img_data['item_id']}")
                
                result = self.extract_from_image_url(
                    img_data['image_url'], 
                    img_data['item_id']
                )
                
                # Skip duplicates (None return)
                if result is None:
                    continue
                
                # Add to results
                self.results.append(result)
                
                # Save progress every 10 images
                if (i + 1) % 10 == 0:
                    self._save_results()
                    logging.info(f"Progress saved: {i+1} images processed")
                
                # Rate limiting
                time.sleep(delay)
                
            except Exception as e:
                logging.error(f"Unexpected error processing {img_data['item_id']}: {e}")
                self.error_count += 1
        
        # Final save (always save, even if no new results)
        self._save_results()
        
        # Retry failed items if requested
        if retry_errors:
            self._retry_failed_items(delay)
        
        self._print_summary()
    
    def _retry_failed_items(self, delay: float):
        """Retry items that failed on first attempt"""
        failed_items = [r for r in self.results if not r.get('success')]
        
        if not failed_items:
            return
        
        logging.info(f"\nRetrying {len(failed_items)} failed items...")
        
        for item in failed_items:
            try:
                logging.info(f"Retrying: {item['item_id']}")
                
                # Remove old result
                self.results = [r for r in self.results if r['item_id'] != item['item_id']]
                
                # Retry extraction
                result = self.extract_from_image_url(item['image_url'], item['item_id'])
                if result:
                    self.results.append(result)
                
                time.sleep(delay)
                
            except Exception as e:
                logging.error(f"Retry failed for {item['item_id']}: {e}")
        
        self._save_results()
    
    def _save_results(self):
        """Save results to JSON file"""
        try:
            # Ensure directory exists
            Path(self.output_file).parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(self.results, f, indent=2, ensure_ascii=False)
            logging.info(f"Results saved to: {self.output_file}")
        except Exception as e:
            logging.error(f"Error saving results: {e}")
            raise
    
    def _print_summary(self):
        """Print processing summary"""
        successful = sum(1 for r in self.results if r.get('success'))
        failed = sum(1 for r in self.results if not r.get('success'))
        total_listings = sum(r.get('listings_found', 0) for r in self.results)
        
        print("\n" + "="*60)
        print("EXTRACTION SUMMARY")
        print("="*60)
        print(f"Images processed:   {len(self.results)}")
        print(f"Successful:         {successful}")
        print(f"Failed:             {failed}")
        print(f"Duplicates skipped: {self.duplicate_count}")
        print(f"Total listings:     {total_listings}")
        print(f"Output file:        {self.output_file}")
        print("="*60)


if __name__ == "__main__":
    # ========================================
    # CONFIGURATION
    # ========================================
    MAX_IMAGES_TO_PROCESS = 20  # Set to a number (e.g., 20) for testing, or "all" for full processing
    DELAY_BETWEEN_IMAGES = 0.5  # Delay in seconds between processing images
    RETRY_FAILED_EXTRACTIONS = True  # Whether to retry failed extractions
    # ========================================
    
    # Initialize extractor
    extractor = TesseractEbayExtractor(output_file="data/EbayListings.json")
    
    # Try loading from existing eBaySales.json first (if it exists)
    if Path("data/eBaySales.json").exists():
        logging.info("Found data/eBaySales.json, loading from there...")
        extractor.process_from_json(
            json_file="data/eBaySales.json",
            delay=DELAY_BETWEEN_IMAGES,
            retry_errors=RETRY_FAILED_EXTRACTIONS,
            max_images=MAX_IMAGES_TO_PROCESS
        )
    else:
        # Fallback to scraping website
        logging.info("No eBaySales.json found, scraping website...")
        logging.error("Website scraping not implemented - please ensure eBaySales.json exists")
