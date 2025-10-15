import requests
import json
import re
from datetime import datetime
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
MAX_RESULTS = 500  # Cloudinary's max per request
OCR_DELAY = 20  # Seconds to wait between OCR requests (180 per hour = 1 every 20 seconds)

# Step 1: List ALL images from Cloudinary with pagination
def list_cloudinary_images():
    url = f'https://api.cloudinary.com/v1_1/{CLOUD_NAME}/resources/image'
    auth = base64.b64encode(f'{API_KEY}:{API_SECRET}'.encode()).decode()
    headers = {'Authorization': f'Basic {auth}'}
    
    all_resources = []
    next_cursor = None
    page = 1
    
    while True:
        params = {
            'type': 'upload',
            'prefix': FOLDER_PREFIX,
            'max_results': MAX_RESULTS,
            'direction': 'desc'
        }
        
        if next_cursor:
            params['next_cursor'] = next_cursor
        
        print(f'Fetching page {page} from Cloudinary...')
        response = requests.get(url, params=params, headers=headers)
        
        if response.status_code != 200:
            raise Exception(f'Error listing images: {response.text}')
        
        data = response.json()
        resources = data.get('resources', [])
        all_resources.extend(resources)
        
        print(f'  Retrieved {len(resources)} images (Total so far: {len(all_resources)})')
        
        # Check if there are more pages
        next_cursor = data.get('next_cursor')
        if not next_cursor:
            print(f'Finished fetching all images. Total: {len(all_resources)}')
            break
        
        page += 1
    
    # Filter for valid image formats and return tuples
    valid_images = [(res['secure_url'], res['public_id']) for res in all_resources 
                    if res['format'] in ['jpg', 'png', 'webp']]
    
    print(f'Valid images (jpg/png/webp): {len(valid_images)}')
    return valid_images

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

# Step 5: Load existing JSON data
def load_existing_json(filepath):
    """Load existing JSON file if it exists, return empty list if not."""
    # Ensure data directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f'Loaded {len(data)} existing entries from {filepath}')
                return data
        except Exception as e:
            print(f'Error loading existing JSON: {e}')
            return []
    else:
        print(f'No existing JSON found at {filepath}, starting fresh.')
        return []

# Step 6: Determine which images need processing
def filter_images_to_process(all_images, existing_data):
    """
    Returns list of images that need OCR processing.
    Includes:
    - New images (not in existing data)
    - Images with success status of "reprocess" or "fail"
    """
    # Create lookup dictionary by public_id
    existing_dict = {entry.get('public_id'): entry for entry in existing_data if entry.get('public_id')}
    
    images_to_process = []
    
    for url, public_id in all_images:
        pid = public_id.split('/')[-1]
        
        # Check if this image exists in our data
        if pid not in existing_dict:
            # New image - needs processing
            images_to_process.append((url, public_id, 'new'))
        else:
            # Existing image - check success status
            existing_entry = existing_dict[pid]
            success_status = existing_entry.get('success', 'fail')
            
            if success_status in ['reprocess', 'fail']:
                # Needs reprocessing
                images_to_process.append((url, public_id, success_status))
    
    return images_to_process

# Main automation
def main():
    images = list_cloudinary_images()
    print(f'Found {len(images)} images from Cloudinary.')
    
    # Load existing data
    output_path = 'data/EbayListings.json'
    existing_data = load_existing_json(output_path)
    
    # Determine which images need processing
    images_to_process = filter_images_to_process(images, existing_data)
    
    # Count by status
    new_count = sum(1 for _, _, status in images_to_process if status == 'new')
    reprocess_count = sum(1 for _, _, status in images_to_process if status == 'reprocess')
    fail_count = sum(1 for _, _, status in images_to_process if status == 'fail')
    
    print(f'\n=== Processing Plan ===')
    print(f'Total images in Cloudinary: {len(images)}')
    print(f'Already complete: {len(existing_data) - reprocess_count - fail_count}')
    print(f'New images to process: {new_count}')
    print(f'Failed to reprocess: {fail_count}')
    print(f'Partial to reprocess: {reprocess_count}')
    print(f'Total to process: {len(images_to_process)}')
    
    if len(images_to_process) == 0:
        print('\n✓ All images have been successfully processed!')
        return
    
    # Estimate time
    estimated_minutes = (len(images_to_process) * OCR_DELAY) / 60
    print(f'\nEstimated time: {estimated_minutes:.1f} minutes ({OCR_DELAY}s delay between requests)')
    print(f'Rate limit: {3600 / OCR_DELAY:.0f} requests per hour\n')
    
    # Create lookup for existing data by public_id for easy updating
    existing_dict = {entry.get('public_id'): entry for entry in existing_data if entry.get('public_id')}
    
    success_count = 0
    failed_count = 0
    reprocess_needed = 0
    
    for idx, (url, public_id, reason) in enumerate(images_to_process, 1):
        pid = public_id.split('/')[-1]
        print(f'\n[{idx}/{len(images_to_process)}] Processing: {pid} (reason: {reason})')
        
        try:
            raw_text = ocr_extract_text(url)
            parsed = parse_ocr_to_json(raw_text, url, public_id)
            
            # Update or add to existing dict
            existing_dict[pid] = parsed
            
            if parsed["success"] == "complete":
                success_count += 1
                print(f'✓ Successfully extracted all fields')
            elif parsed["success"] == "reprocess":
                reprocess_needed += 1
                print(f'⚠ Partial extraction - will reprocess next run')
            else:
                failed_count += 1
                print(f'✗ Failed to extract fields')
                
        except Exception as e:
            failed_count += 1
            error_msg = str(e)
            print(f'✗ Error: {error_msg}')
            
            # Add/update failed entry
            existing_dict[pid] = {
                "success": "fail",
                "sold_date": None,
                "title": f"Error: {error_msg[:50]}",
                "sold_price": None,
                "seller": None,
                "image_url": url,
                "processed_at": datetime.utcnow().isoformat() + 'Z',
                "public_id": pid
            }
        
        # Rate limiting: wait between requests (except on last item)
        if idx < len(images_to_process):
            print(f'Waiting {OCR_DELAY} seconds before next request...')
            time.sleep(OCR_DELAY)
    
    # Convert dict back to list for JSON output
    results = list(existing_dict.values())
    
    print(f'\n=== Processing Summary ===')
    print(f'Total entries in JSON: {len(results)}')
    print(f'Successfully completed: {success_count}')
    print(f'Need reprocessing: {reprocess_needed}')
    print(f'Failed: {failed_count}')
    
    # Calculate overall stats
    complete_total = sum(1 for r in results if r.get('success') == 'complete')
    reprocess_total = sum(1 for r in results if r.get('success') == 'reprocess')
    fail_total = sum(1 for r in results if r.get('success') == 'fail')
    
    print(f'\n=== Overall Stats ===')
    print(f'Complete: {complete_total}')
    print(f'Need reprocessing: {reprocess_total}')
    print(f'Failed: {fail_total}')
    
    # Save to local JSON file
    output_path = 'data/EbayListings.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4, ensure_ascii=False)
    print(f'\nSaved {len(results)} total entries to {output_path}')

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
        
        commit_message = f'Update EbayListings.json - Added {len(new_images)} new entries ({success_count} success, {failed_count} failed) at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
        subprocess.run(['git', 'commit', '-m', commit_message], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print('Committed and pushed to GitHub')
    except subprocess.CalledProcessError as e:
        print(f'Git error: {e}, continuing without commit')

if __name__ == '__main__':
    main()
