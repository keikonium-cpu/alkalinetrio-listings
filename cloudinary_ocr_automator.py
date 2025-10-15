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
MAX_RESULTS = 20

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
        'isOverlayRequired': 'false',
        'OCREngine': 2  # Try engine 2 for better accuracy
    }
    response = requests.get(ocr_url, params=params)
    if response.status_code != 200:
        raise Exception(f'OCR error: {response.text}')
    
    result = response.json()
    if result.get('OCRExitCode') != 1:
        raise Exception(f'OCR failed: {result.get("ErrorMessage")}')
    
    # Get the full ParsedText
    parsed_text = result['ParsedResults'][0]['ParsedText'].strip()
    
    # Log the raw OCR output for debugging
    print(f"\n--- RAW OCR OUTPUT ---")
    print(parsed_text)
    print(f"--- END RAW OUTPUT ---\n")
    
    return parsed_text

# Step 3: Parse OCR text to structured dict
def parse_ocr_to_json(raw_text, url, public_id):
    # Replace newlines and carriage returns with spaces for easier parsing
    clean_text = re.sub(r'[\r\n]+', ' ', raw_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    print(f"Clean text: {clean_text[:200]}...")  # Debug output
    
    # Extract sold date - more flexible pattern
    sold_date_match = re.search(r'Sold\s+([A-Za-z]{3}\s+\d{1,2},?\s+\d{4})', clean_text, re.IGNORECASE)
    
    # Extract title - look for text between date and condition/price indicators
    # Title typically comes after "Sold [date]" and before "Brand New", "Pre-Owned", or price
    title_match = re.search(
        r'Sold\s+[A-Za-z]{3}\s+\d{1,2},?\s+\d{4}\s+(.+?)(?:\s+(?:Brand New|Pre-Owned|New|Used|\$\d+))',
        clean_text,
        re.IGNORECASE
    )
    
    # Extract price - look for dollar amount
    price_match = re.search(r'\$(\d+\.\d{2})', clean_text)
    
    # Extract seller - look for various seller patterns
    # Pattern 1: "username 99.5% positive (1K)" or similar
    seller_match = re.search(
        r'(?:^|\s)([a-zA-Z0-9_-]+)\s+\d{2,3}(?:\.\d+)?%\s+positive',
        clean_text,
        re.IGNORECASE
    )
    
    # If first pattern fails, try alternative patterns
    if not seller_match:
        # Pattern 2: Look for seller after specific keywords
        seller_match = re.search(r'seller[:\s]+([a-zA-Z0-9_-]+)', clean_text, re.IGNORECASE)
    
    # Extract item ID if present
    item_id_match = re.search(r'(?:Item|ID)[:\s#]*(\d+)', clean_text, re.IGNORECASE)
    
    now = datetime.utcnow().isoformat() + 'Z'
    
    # Build result - only include fields needed for website
    result = {
        "sold_date": sold_date_match.group(1) if sold_date_match else None,
        "title": title_match.group(1).strip() if title_match else None,
        "sold_price": price_match.group(1) if price_match else None,
        "seller": seller_match.group(1) if seller_match else None,
        "image_url": url,
        "processed_at": now,
        "public_id": public_id.split('/')[-1]
    }
    
    return result

# Step 4: Upload file to FTP server
def upload_to_ftp(local_path, remote_path):
    try:
        with FTP(FTP_SERVER) as ftp:
            ftp.login(user=FTP_USERNAME, passwd=FTP_PASSWORD)
            with open(local_path, 'rb') as file:
                ftp.storbinary(f'STOR {remote_path}', file)
            ftp.quit()
        print(f'Uploaded {local_path} to {remote_path}')
    except Exception as e:
        print(f'FTP upload error: {e}')
        raise

# Main automation
def main():
    images = list_cloudinary_images()
    print(f'Found {len(images)} images to process.')
    
    results = []
    success_count = 0
    failed_count = 0
    
    for url, public_id in images:
        try:
            raw_text = ocr_extract_text(url)
            parsed = parse_ocr_to_json(raw_text, url, public_id)
            results.append(parsed)
            
            if parsed["success"]:
                success_count += 1
                print(f'✓ Successfully processed: {public_id}')
            else:
                failed_count += 1
                print(f'✗ Failed to extract all fields: {public_id}')
                
        except Exception as e:
            failed_count += 1
            print(f'✗ Error processing {url}: {e}')
            # Add failed entry
            results.append({
                "success": False,
                "error": str(e),
                "image_url": url,
                "public_id": public_id.split('/')[-1],
                "processed_at": datetime.utcnow().isoformat() + 'Z'
            })
    
    print(f'\n=== Summary ===')
    print(f'Total: {len(images)}')
    print(f'Success: {success_count}')
    print(f'Failed: {failed_count}')
    
    # Ensure data directory exists
    os.makedirs('data', exist_ok=True)
    
    # Save to local JSON file
    output_path = 'data/EbayListings.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4, ensure_ascii=False)
    print(f'\nSaved to {output_path}')

    # Upload to FTP server
    try:
        remote_path = 'public_html/data/EbayListings.json'
        upload_to_ftp(output_path, remote_path)
    except Exception as e:
        print(f'Warning: FTP upload failed but continuing: {e}')

    # Commit and push to GitHub
    try:
        subprocess.run(['git', 'config', '--global', 'user.name', 'GitHub Action'], check=True)
        subprocess.run(['git', 'config', '--global', 'user.email', 'action@github.com'], check=True)
        subprocess.run(['git', 'add', output_path], check=True)
        subprocess.run(['git', 'commit', '-m', f'Update EbayListings.json - {success_count} success, {failed_count} failed at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print('Committed and pushed to GitHub')
    except subprocess.CalledProcessError as e:
        print(f'Git error: {e}, continuing without commit')

if __name__ == '__main__':
    main()
