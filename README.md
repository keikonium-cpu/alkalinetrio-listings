# alkalinetrio-listings
Capturing Alkaline Trio Listings. This script captures the individual listings for each sold item on my sales.html page.

## Configuration

- `MAX_ITEMS_PER_CAPTURE`: Maximum items to capture per run (default: 60)
- `DELAY_BETWEEN_SCREENSHOTS`: Delay in milliseconds between screenshots (default: 300ms)
- Images are saved as WebP format for optimal quality and file size
- Total JSON storage is uncapped - all captured items are retained indefinitely

## Initial Setup

For initial capture of 240 items:
1. Update `MAX_ITEMS_PER_CAPTURE` to 240 in index.js
2. Set `TARGET_URL` to include `_ipg=240`
3. Run the script
4. Change back to 60 for weekly captures

## Weekly Captures

The script runs automatically every Friday at 6PM EST and captures up to 60 new items, appending them to the existing gallery without removing old items.

---

# eBay Data Extractor - Setup Guide

## Requirements

### System Requirements
- Python 3.11+
- Tesseract OCR 4.0+

### Python Dependencies (requirements.txt)
```
pytesseract>=0.3.10
opencv-python-headless>=4.8.0
Pillow>=10.0.0
requests>=2.31.0
beautifulsoup4>=4.12.0
numpy>=1.24.0
```

## Installation

### Local Installation

1. **Install Tesseract OCR**

   **Ubuntu/Debian:**
   ```bash
   sudo apt-get update
   sudo apt-get install tesseract-ocr libtesseract-dev
   ```

   **macOS:**
   ```bash
   brew install tesseract
   ```

   **Windows:**
   Download from: https://github.com/UB-Mannheim/tesseract/wiki

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the script**
   ```bash
   python extract_ebay_data.py
   ```

### GitHub Actions Setup

1. **Create repository structure:**
   ```
   your-repo/
   ├── .github/
   │   └── workflows/
   │       └── extract_data.yml
   ├── data/
   │   └── .gitkeep
   ├── extract_ebay_data.py
   ├── requirements.txt
   └── README.md
   ```

2. **Enable GitHub Actions**
   - Go to repository Settings → Actions → General
   - Allow "Read and write permissions" for workflows

3. **(Optional) Add FTP credentials for server upload**
   - Go to Settings → Secrets and variables → Actions
   - Add secrets:
     - `FTP_SERVER`: your-server.com
     - `FTP_USERNAME`: your-username
     - `FTP_PASSWORD`: your-password

4. **Trigger workflow**
   - Go to Actions tab → "Extract eBay Data with Tesseract" → Run workflow
   - Or wait for scheduled run (Sunday midnight UTC)

## Features

### ✅ Error Recovery
- Automatic retry of failed extractions
- Progress saved every 10 images
- Detailed error logging
- Continues processing even if some images fail

### ✅ Duplicate Detection
- MD5 hash-based deduplication
- Loads existing data to avoid reprocessing
- Tracks processed images across runs

### ✅ OCR Optimization
- Image preprocessing (grayscale, denoising, contrast enhancement)
- Adaptive thresholding for better text recognition
- Multiple OCR configurations tested

### ✅ Data Extraction
- **Sold Date**: Extracted from "Sold Oct 11, 2025" pattern
- **Title**: Product name and details
- **Price**: Sold price ($XX.XX)
- **Seller**: Username from "username 100% positive"
- **Raw Text**: Full OCR output for debugging

## Output Format

The script generates `data/EbayListings.json` with this structure:

```json
[
  {
    "item_id": "item001",
    "image_url": "https://res.cloudinary.com/...",
    "image_hash": "abc123...",
    "success": true,
    "processed_at": "2025-10-12T10:30:00",
    "sold_date": "Oct 11, 2025",
    "title": "Alkaline Trio - Good Mourning (Black Vinyl LP, 2003, Vagrant Records)",
    "sold_price": "69.99",
    "seller": "belkarina",
    "raw_text": "Full OCR text..."
  }
]
```

## Improving Accuracy

If OCR accuracy is low, try these adjustments:

1. **Adjust preprocessing** in `preprocess_image()`:
   ```python
   # Increase threshold block size
   thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                   cv2.THRESH_BINARY, 15, 2)  # Changed 11 to 15
   ```

2. **Try different PSM modes** in `extract_from_image_url()`:
   ```python
   custom_config = r'--oem 3 --psm 3'  # Try PSM 3, 4, 6, or 11
   ```

3. **Train Tesseract** with eBay-specific font data:
   - Create training data from your eBay screenshots
   - Follow: https://tesseract-ocr.github.io/tessdoc/Training-Tesseract.html

## Troubleshooting

**Issue: "Tesseract not found"**
- Ensure Tesseract is installed and in PATH
- Set path manually: `pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'`

**Issue: Low accuracy**
- Check image quality (should be at least 300 DPI equivalent)
- Verify images are loading correctly
- Review `raw_text` field in output to see what OCR detected

**Issue: No images found**
- Verify website structure hasn't changed
- Check that divs have `data-id="item###"` attributes
- Ensure images are from Cloudinary (URL contains "cloudinary")

## Cost Analysis

✅ **100% Free Solution**
- Tesseract: Open source
- GitHub Actions: 2,000 minutes/month free
- Storage: Free in repository
- 500+ images process in ~30-45 minutes

## License

MIT License - Free for personal and commercial use
