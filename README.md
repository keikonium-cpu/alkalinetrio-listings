# alkalinetrio-listings
Capturing Alkaline Trio Listings

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
