name: Extract eBay Listings

on:
  schedule:
    # Runs at 7 AM EST (11 UTC) and 7 PM EST (23 UTC)
    - cron: '0 11,23 * * *'
  workflow_dispatch:  # Allows manual trigger for testing

permissions:
  contents: write

jobs:
  extract:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout repo
      uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y tesseract-ocr
        
        # Install Chrome for Selenium
        wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
        sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
        sudo apt-get update
        sudo apt-get install -y google-chrome-stable
        
        # Verify installations
        tesseract --version
        google-chrome --version

    - name: Install Python dependencies
      run: pip install -r requirements.txt

    - name: Run extraction script
      run: python extract_ebay.py

    - name: Upload to server via FTP
      if: success()
      uses: SamKirkland/FTP-Deploy-Action@v4.3.4
      with:
        server: ${{ secrets.FTP_SERVER }}
        username: ${{ secrets.FTP_USERNAME }}
        password: ${{ secrets.FTP_PASSWORD }}
        local-dir: ./data/
        server-dir: /public_html/data/
        dangerous-clean-slate: false

    - name: Commit and push updated JSON
      if: success()
      run: |
        git config user.name "GitHub Action"
        git config user.email "actions@github.com"
        git add data/ebaylistings.json
        git commit -m "Update ebaylistings.json - $(date)" || echo "No changes to commit"
        git push
