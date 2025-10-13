import pytesseract
from PIL import Image
import cv2
import numpy as np
import requests
from bs4 import BeautifulSoup
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
    
    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for better OCR accuracy"""
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply adaptive thresholding
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 11, 2
        )
        
        # Denoise
        denoised = cv2.fastNlMeansDenoising(thresh)
        
        # Increase contrast
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced = clahe.apply(denoised)
        
        return enhanced
    
    def compute_image_hash(self, image_url: str) -> str:
        """Generate hash for duplicate detection"""
        return hashlib.md5(image_url.encode()).hexdigest()
    
    def extract_date(self, text: str) -> Optional[str]:
        """Extract sold date from OCR text"""
        # Pattern: "Sold Oct 11, 2025" or variations
        patterns = [
            r'Sold\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None
    
    def extract_price(self, text: str) -> Optional[str]:
        """Extract price from OCR text"""
        # Pattern: $XX.XX or $XXX.XX
        patterns = [
            r'\$(\d+\.\d{2})',
            r'\$(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None
    
    def extract_title(self, text: str) -> Optional[str]:
        """Extract item title from OCR text"""
        # Look for the main product line (usually contains brand/item info)
        lines = text.split('\n')
        
        # Filter out common non-title lines
        exclude_terms = ['sold', 'brand new', 'positive', 'delivery', 'located', 'offer']
        
        for line in lines:
            line = line.strip()
            # Look for lines that are substantial and don't match exclusions
            if len(line) > 20 and not any(term in line.lower() for term in exclude_terms):
                # Check if it contains typical product info indicators
                if any(char in line for char in ['-', '(', ')', ',']):
                    return line
        
        return None
    
    def extract_seller(self, text: str) -> Optional[str]:
        """Extract seller username from OCR text"""
        # Pattern: username followed by "100% positive"
        pattern = r'([a-zA-Z0-9_\-]+)\s*100%\s*positive'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None
    
    def extract_from_image_url(self, image_url: str, item_id: str) -> Dict:
        """Download image and extract data using Tesseract OCR"""
        result = {
            'item_id': item_id,
            'image_url': image_url,
            'image_hash': self.compute_image_hash(image_url),
            'success': False,
            'processed_at': datetime.now().isoformat()
        }
        
        try:
            # Check for duplicates
            if result['image_hash'] in self.seen_hashes:
                logging.info(f"Skipping duplicate: {item_id}")
                self.duplicate_count += 1
                return None
            
            # Download image
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            
            # Convert to numpy array
            image_array = np.asarray(bytearray(response.content), dtype=np.uint8)
            image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            
            if image is None:
                raise ValueError("Failed to decode image")
            
            # Preprocess image
            processed = self.preprocess_image(image)
            
            # Perform OCR with multiple configurations
            custom_config = r'--oem 3 --psm 6'
            text = pytesseract.image_to_string(processed, config=custom_config)
            
            # Also try with original image for comparison
            text_original = pytesseract.image_to_string(image, config=custom_config)
            
            # Use the text with more content
            full_text = text if len(text) > len(text_original) else text_original
            
            # Extract structured data
            result['sold_date'] = self.extract_date(full_text)
            result['title'] = self.extract_title(full_text)
            result['sold_price'] = self.extract_price(full_text)
            result['seller'] = self.extract_seller(full_text)
            result['raw_text'] = full_text
            result['success'] = True
            
            # Mark as seen
            self.seen_hashes.add(result['image_hash'])
            
            logging.info(f"✓ Extracted: {item_id} - {result.get('title', 'N/A')[:50]}")
            
        except Exception as e:
            result['error'] = str(e)
            self.error_count += 1
            logging.error(f"✗ Error processing {item_id}: {e}")
        
        return result
    
    def scrape_cloudinary_images(self, url: str) -> List[Dict[str, str]]:
        """Scrape Cloudinary image URLs from the website"""
        logging.info(f"Scraping images from: {url}")
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Debug: Print the HTML structure
            logging.info(f"Page title: {soup.title.string if soup.title else 'No title'}")
            
            images = []
            
            # Try multiple selector patterns
            selectors = [
                {'class': 'gallery-item'},  # div with class="gallery-item"
                {'data-id': re.compile(r'item')},  # Any element with data-id containing "item"
            ]
            
            items = []
            for selector in selectors:
                found = soup.find_all('div', selector)
                if found:
                    logging.info(f"Found {len(found)} items with selector: {selector}")
                    items.extend(found)
                    break
            
            # If still no items found, try finding all divs with data-id
            if not items:
                items = soup.find_all('div', attrs={'data-id': True})
                logging.info(f"Found {len(items)} divs with data-id attribute")
            
            # If still nothing, try finding all img tags with cloudinary URLs
            if not items:
                logging.info("No divs found, searching for all img tags with Cloudinary URLs")
                all_imgs = soup.find_all('img')
                logging.info(f"Found {len(all_imgs)} total img tags")
                
                for img in all_imgs:
                    src = img.get('src') or img.get('data-src')
                    if src and 'cloudinary' in src and 'item' in src:
                        # Extract item ID from URL
                        match = re.search(r'item([a-zA-Z0-9]+)', src)
                        if match:
                            item_id = f"item{match.group(1)}"
                            images.append({
                                'item_id': item_id,
                                'image_url': src
                            })
                            logging.info(f"Found image: {item_id}")
            else:
                # Process items with data-id
                logging.info(f"Processing {len(items)} items")
                
                for item in items:
                    item_id = item.get('data-id')
                    if not item_id:
                        continue
                    
                    # Look for img tags within the div
                    img_tags = item.find_all('img')
                    
                    for img in img_tags:
                        src = img.get('src') or img.get('data-src')
                        if src and 'cloudinary' in src:
                            images.append({
                                'item_id': item_id,
                                'image_url': src
                            })
                            logging.info(f"Found image: {item_id}")
                            break  # Only take first image per item
            
            logging.info(f"Total Cloudinary images found: {len(images)}")
            
            # If still no images, log a sample of the HTML
            if not images:
                logging.error("No images found. HTML sample:")
                body = soup.find('body')
                if body:
                    sample = str(body)[:1000]
                    logging.error(sample)
            
            return images
            
        except Exception as e:
            logging.error(f"Error scraping website: {e}", exc_info=True)
            return []
    
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
    
    def process_from_json(self, json_file: str, delay: float = 1.0, retry_errors: bool = True):
        """Process images from eBaySales.json file"""
        images = self.load_from_json(json_file)
        
        if not images:
            logging.error("No images found in JSON file")
            self._save_results()
            return
        
        self._process_images(images, delay, retry_errors)
    
    def process_website(self, url: str, delay: float = 1.0, retry_errors: bool = True):
        """Process all images from the website"""
        images = self.scrape_cloudinary_images(url)
        
        if not images:
            logging.error("No images found to process")
            self._save_results()
            return
        
        self._process_images(images, delay, retry_errors)
    
    def _process_images(self, images: List[Dict[str, str]], delay: float, retry_errors: bool):
        """Common processing logic for images"""
        logging.info(f"Processing {len(images)} images...")
        
        # Process each image
        for i, img_data in enumerate(images):
            try:
                logging.info(f"Processing {i+1}/{len(images)}: {img_data['item_id']}")
                
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
        
        print("\n" + "="*60)
        print("EXTRACTION SUMMARY")
        print("="*60)
        print(f"Total processed:    {len(self.results)}")
        print(f"Successful:         {successful}")
        print(f"Failed:             {failed}")
        print(f"Duplicates skipped: {self.duplicate_count}")
        print(f"Output file:        {self.output_file}")
        print("="*60)


if __name__ == "__main__":
    # Initialize extractor
    extractor = TesseractEbayExtractor(output_file="data/EbayListings.json")
    
    # Try loading from existing eBaySales.json first (if it exists)
    if Path("data/eBaySales.json").exists():
        logging.info("Found data/eBaySales.json, loading from there...")
        extractor.process_from_json(
            json_file="data/eBaySales.json",
            delay=0.5,
            retry_errors=True
        )
    else:
        # Fallback to scraping website
        logging.info("No eBaySales.json found, scraping website...")
        extractor.process_website(
            url="http://www.alkalinetrioarchive.com/sales.html",
            delay=0.5,
            retry_errors=True
        )
