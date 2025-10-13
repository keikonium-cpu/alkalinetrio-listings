import requests
from bs4 import BeautifulSoup
import pytesseract
from PIL import Image
import cv2
import numpy as np
import json
import os
from urllib.request import urlopen

# Configuration
TARGET_URL = "http://www.alkalinetrioarchive.com/sales.html"
MAX_ITEMS = 10
OUTPUT_FILE = "data/ebaylistings.json"

# Ensure output directory exists
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

# Function to preprocess image for better OCR
def preprocess_image(image):
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh

# Function to extract relevant data from image text
def extract_data_from_text(text):
    data = {"success": False}
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if "Sold" in line and "2025" in line:
            data["sold_date"] = line
        elif "Alkaline Trio" in line:
            data["title"] = line
        elif "$" in line and ".99" in line:
            data["sold_price"] = line.split("$")[1].split()[0]
        elif "100% positive" in line:
            data["seller"] = line.split()[0]
    
    if all(key in data for key in ["sold_date", "title", "sold_price", "seller"]):
        data["success"] = True
    return data

# Fetch HTML and extract image URLs
response = requests.get(TARGET_URL)
soup = BeautifulSoup(response.content, 'html.parser')
gallery = soup.find('div', class_='gallery')
images = gallery.find_all('img', limit=MAX_ITEMS)

# List to hold extracted data
extracted_data = []

# Process each image
for img in images:
    img_url = img['data-src']  # Use data-src for lazy-loaded images
    with urlopen(img_url) as response:
        image = Image.open(response)
        image_np = np.array(image)
        processed_image = preprocess_image(image)
        
        # Perform OCR
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(processed_image, config=custom_config)
        
        # Extract relevant data
        listing_data = extract_data_from_text(text)
        listing_data["image_url"] = img_url
        listing_data["processed_at"] = datetime.datetime.utcnow().isoformat()
        
        extracted_data.append(listing_data)
        print(f"Processed: {img_url}")

# Save to JSON
with open(OUTPUT_FILE, 'w') as f:
    json.dump(extracted_data, f, indent=2)

print(f"Extracted data saved to {OUTPUT_FILE}")
