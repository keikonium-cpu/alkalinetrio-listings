import requests
import json
import re
from datetime import datetime
import base64
import os
from ftplib import FTP
import subprocess

# Retrieve secrets from GitHub Actions environment variables
CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
API_KEY = os.getenv('CLOUDINARY_API_KEY')
API_SECRET = os.getenv('CLOUDINARY_API_SECRET')
OCR_API_KEY = os.getenv('OCR_API_KEY')
FTP_SERVER = os.getenv('FTP_SERVER')
FTP_USERNAME = os.getenv('FTP_USERNAME')
FTP_PASSWORD = os.getenv('FTP_PASSWORD')
FOLDER_PREFIX = 'website-screenshots/'
MAX_RESULTS = 100

# Step 1: List images from Cloudinary
def list_cloudinary_images():
    url = f'https://api.cloudinary.com/v1_1/{CLOUD_NAME}/resources/image'
    params = {
        'type': 'upload',
        'prefix': FOLDER_PREFIX,
        'max_results': MAX_RESULTS,
        'direction': 'desc'
    }
    auth = base64.b64encode(f'{API_KEY}:{API_SECRET}'.encode()).decode()
    headers = {'Authorization': f'Basic {auth}'}
    
    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        raise Exception(f'Error listing images: {response.text}')
    
    resources = response.json().get('resources', [])
    return [(res['secure_url'], res['public_id']) for res in resources if res['format'] in ['jpg', 'png', 'webp']]

# Step 2: OCR extract text from image URL
def ocr_extract_text(image_url):
    ocr_url = 'https://api.ocr.space/parse/imageurl'
    params = {
        'apikey': OCR_API_KEY,
        'url': image_url,
        'language': 'eng',
        'isOverlayRequired': 'true'  # Changed to true to get overlay with lines
    }
    response = requests.get(ocr_url, params=params)
    if response.status_code != 200:
        raise Exception(f'OCR error: {response.text}')
    
    result = response.json()
    if result.get('OCRExitCode') != 1:
        raise Exception(f'OCR failed: {result.get("ErrorMessage")}')
    
    return result

# Step 3: Parse OCR text to structured dict
def parse_ocr_to_json(ocr_result, url, public_id):
    try:
        lines = ocr_result['ParsedResults'][0]['Overlay']['Lines']
    except KeyError:
        return {
            "sold_date": "N/A",
            "title": "N/A",
            "sold_price": "N/A",
            "seller_id": "N/A",
            "url": url,
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "publicId": public_id.split('/')[-1]
        }
    
    sold_date = None
    title = ""
    sold_price = None
    seller_id = None
    in_title = False
    
    for line in lines:
        text = line['LineText'].strip()
        if not text:
            continue
        
        if sold_date is None and text.startswith('Sold '):
            sold_date = text.replace('Sold ', '', 1)
            in_title = True
            continue
        
        if in_title and sold_price is None:
            if text.startswith('$'):
                sold_price = text.split()[0] if ' ' in text else text  # Take only the price if more on line
                in_title = False
            elif len(text) > 20 and not text.lower().startswith('brand new'):  # Assume title is long, skip "Brand New" or short artifacts
                if title:
                    title += ' ' + text
                else:
                    title = text
            continue  # Skip short lines or condition like "Brand New"
        
        if '% positive' in text.lower():
            # Extract seller_id: characters before the percentage, matching allowed chars
            seller_match = re.match(r'([a-zA-Z0-9._-]+)\s+\d{1,3}(\.\d+)?%\s+positive', text, re.IGNORECASE)
            if seller_match:
                seller_id = seller_match.group(1)
    
    # If multiple prices, we took the first one starting with $
    # For seller, assumed on its own line or shared
    
    now = datetime.utcnow().isoformat() + 'Z'
    
    return {
        "sold_date": sold_date or "N/A",
        "title": title or "N/A",
        "sold_price": sold_price or "N/A",
        "seller_id": seller_id or "N/A",
        "url": url,
        "timestamp": now,
        "publicId": public_id.split('/')[-1]
    }

# Step 4: Upload file to FTP server
def upload_to_ftp(local_path, remote_path):
    with FTP(FTP_SERVER) as ftp:
        ftp.login(user=FTP_USERNAME, passwd=FTP_PASSWORD)
        with open(local_path, 'rb') as file:
            ftp.storbinary(f'STOR {remote_path}', file)
        ftp.quit()
    print(f'Uploaded {local_path} to {remote_path}')

# Main automation
def main():
    images = list_cloudinary_images()
    print(f'Found {len(images)} images to process.')
    
    results = []
    for url, public_id in images:
        try:
            raw_ocr = ocr_extract_text(url)
            parsed = parse_ocr_to_json(raw_ocr, url, public_id)
            results.append(parsed)
            print(f'Processed: {public_id}')
        except Exception as e:
            print(f'Error processing {url}: {e}')
    
    # Save to local JSON file
    output_path = 'data/processed_listings.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4)
    print(f'Saved to {output_path}')

    # Upload to FTP server
    remote_path = 'public_html/data/processed_listings.json'
    upload_to_ftp(output_path, remote_path)

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
