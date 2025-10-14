import requests
import json
import re
from datetime import datetime, UTC
import base64
import os
from ftplib import FTP
import subprocess
import time

# Retrieve secrets from GitHub Actions environment variables
CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
API_KEY = os.getenv('CLOUDINARY_API_KEY')
API_SECRET = os.getenv('CLOUDINARY_API_SECRET')
OCR_API_KEY = os.getenv('OCR_API_KEY')
FTP_SERVER = os.getenv('FTP_SERVER')
FTP_USERNAME = os.getenv('FTP_USERNAME')
FTP_PASSWORD = os.getenv('FTP_PASSWORD')
FOLDER_PREFIX = 'website-screenshots/'
MAX_RESULTS = 10
OCR_TIMEOUT = 30  # Timeout in seconds for OCR requests

# Step 1: List images from Cloudinary
def list_cloudinary_images():
    print("Listing images from Cloudinary...")
    url = f'https://api.cloudinary.com/v1_1/{CLOUD_NAME}/resources/image'
    params = {
        'type': 'upload',
        'prefix': FOLDER_PREFIX,
        'max_results': MAX_RESULTS,
        'direction': 'desc'
    }
    auth = base64.b64encode(f'{API_KEY}:{API_SECRET}'.encode()).decode()
    headers = {'Authorization': f'Basic {auth}'}
    
    response = requests.get(url, params=params, headers=headers, timeout=10)
    if response.status_code != 200:
        raise Exception(f'Error listing images: {response.text}')
    
    resources = response.json().get('resources', [])
    images = [(res['secure_url'], res['public_id']) for res in resources if res['format'] in ['jpg', 'png', 'webp']]
    print(f"Found {len(images)} images.")
    return images

# Step 2: OCR extract text from image URL
def ocr_extract_text(image_url):
    print(f"Processing OCR for {image_url}...")
    ocr_url = 'https://api.ocr.space/parse/imageurl'
    params = {
        'apikey': OCR_API_KEY,
        'url': image_url,
        'language': 'eng',
        'isOverlayRequired': 'true'
    }
    try:
        response = requests.get(ocr_url, params=params, timeout=OCR_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        raise Exception(f'OCR request failed: {e}')
    
    result = response.json()
    if result.get('OCRExitCode') != 1:
        raise Exception(f'OCR failed: {result.get("ErrorMessage")}')
    
    print(f"OCR completed for {image_url}.")
    return result

# Step 3: Parse OCR text to structured dict
def parse_ocr_to_json(ocr_result, url, public_id):
    print(f"Parsing OCR result for {public_id}...")
    try:
        lines = ocr_result['ParsedResults'][0]['Overlay']['Lines']
    except KeyError:
        print(f"No valid OCR lines for {public_id}, using defaults.")
        return {
            "sold_date": "N/A",
            "title": "N/A",
            "sold_price": "N/A",
            "seller_id": "N/A",
            "url": url,
            "timestamp": datetime.now(UTC).isoformat() + 'Z',
            "publicId": public_id.split('/')[-1]
        }
    
    sold_date = None
    title_lines = []
    sold_price = None
    seller_id = None
    
    for line in lines:
        text = line['LineText'].strip()
        if not text:
            continue
        
        if sold_date is None and text.startswith('Sold '):
            sold_date = text.replace('Sold ', '', 1)
        elif sold_date and sold_price is None and not text.startswith('$'):
            if text.lower() != 'brand new':
                title_lines.append(text)
        elif sold_price is None and text.startswith('$'):
            sold_price = re.match(r'^\$[\d\.]+', text).group(0)
        elif '% positive' in text.lower():
            seller_match = re.match(r'([a-zA-Z0-9._-]+)\s+\d{1,3}(\.\d+)?%\s+positive', text, re.IGNORECASE)
            if seller_match:
                seller_id = seller_match.group(1)
    
    title = ' '.join(title_lines).strip() if title_lines else "N/A"
    
    return {
        "sold_date": sold_date or "N/A",
        "title": title or "N/A",
        "sold_price": sold_price or "N/A",
        "seller_id": seller_id or "N/A",
        "url": url,
        "timestamp": datetime.now(UTC).isoformat() + 'Z',
        "publicId": public_id.split('/')[-1]
    }

# Step 4: Upload file to FTP server
def upload_to_ftp(local_path, remote_path):
    print(f"Uploading {local_path} to FTP...")
    with FTP(FTP_SERVER) as ftp:
        ftp.login(user=FTP_USERNAME, passwd=FTP_PASSWORD)
        with open(local_path, 'rb') as file:
            ftp.storbinary(f'STOR {remote_path}', file)
        ftp.quit()
    print(f"Uploaded to {remote_path}.")

# Main automation
def main():
    images = list_cloudinary_images()
    
    results = []
    for url, public_id in images:
        try:
            start_time = time.time()
            raw_ocr = ocr_extract_text(url)
            parsed = parse_ocr_to_json(raw_ocr, url, public_id)  # Fixed: Added missing closing parenthesis and public_id
            results.append(parsed)
            print(f"Processed {public_id} in {time.time() - start_time:.2f} seconds.")
        except Exception as e:
            print(f"Error processing {url}: {e}")
    
    # Save to local JSON file
    output_path = 'data/processed_listings.json'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4)
    print(f"Saved to {output_path}")

    # Upload to FTP server
    remote_path = 'public_html/data/processed_listings.json'
    try:
        upload_to_ftp(output_path, remote_path)
    except Exception as e:
        print(f"FTP upload failed: {e}")

    # Commit and push to GitHub
    try:
        subprocess.run(['git', 'config', '--global', 'user.name', 'GitHub Action'], check=True)
        subprocess.run(['git', 'config', '--global', 'user.email', 'action@github.com'], check=True)
        subprocess.run(['git', 'add', output_path], check=True)
        subprocess.run(['git', 'commit', '-m', f'Update processed_listings.json at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print('Committed and pushed to GitHub')
    except subprocess.CalledProcessError as e:
        print(f'Git error: {e}, continuing without commit')

if __name__ == '__main__':
    main()
