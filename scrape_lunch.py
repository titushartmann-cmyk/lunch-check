import os
import requests
import json
import re
from html.parser import HTMLParser

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_FILE = os.path.join(BASE_DIR, "lunch_app.html")
URL = "https://directory.lunch-check.ch/LunchCheck/LC_Directory.aspx"

class LunchTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.rows = []
        self.cell_buffer = ""
        # The main grid usually has a specific ID or class, but we'll grab the main table structure.
        # ASP.NET GridViews usually render as <table> with rules="all" or similar.
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'table':
            # Identify the correct table if possible, or just grab all tables
            if 'id' in attrs_dict and 'GridView1' in attrs_dict['id']:
                self.in_table = True
        
        if self.in_table:
            if tag == 'tr':
                self.in_row = True
                self.current_row = []
            elif tag == 'td':
                self.in_cell = True
                self.cell_buffer = ""
    
    def handle_endtag(self, tag):
        if self.in_table:
            if tag == 'table':
                self.in_table = False
            elif tag == 'tr':
                self.in_row = False
                if self.current_row:
                    self.rows.append(self.current_row)
            elif tag == 'td':
                self.in_cell = False
                self.current_row.append(self.cell_buffer.strip())

    def handle_data(self, data):
        if self.in_cell:
            self.cell_buffer += data

def scrape_data():
    print(f"Fetching data from {URL}...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; LunchScraper/1.0)'}
        res = requests.get(URL, headers=headers, timeout=30)
        res.raise_for_status()
        html = res.text
        
        # Regex extraction based on ASP.NET IDs
        # Names: ..._Label3
        # Addr: ..._Label5
        # Zip: ..._Label7
        # City: ..._Label8
        # Url: ..._LinkButton1
        
        # check basic count
        names = re.findall(r'id=".*?_Label3">(.*?)</span>', html)
        addrs = re.findall(r'id=".*?_Label5">(.*?)</span>', html)
        zips = re.findall(r'id=".*?_Label7">(.*?)</span>', html)
        cities = re.findall(r'id=".*?_Label8">(.*?)</span>', html)
        
        # URLs are trickier because they might be empty or have different attributes
        # We look for the anchor tag with LinkButton1 ID and capture its content
        urls = re.findall(r'id=".*?_LinkButton1".*?>(.*?)</a>', html)
        
        print(f"Found {len(names)} items.")
        
        data = []
        min_len = min(len(names), len(addrs), len(zips), len(cities))
        
        for i in range(min_len):
            # Clean up URL (sometimes it's empty)
            website = urls[i] if i < len(urls) else ""
            if "javascript:" in website: website = "" # Garbage check
            
            item = {
                'Restaurant': names[i].strip(),
                'Adresse': addrs[i].strip(),
                'PLZ': zips[i].strip(),
                'Ort': cities[i].strip(),
                'Website': website.strip()
            }
            data.append(item)
            
        return data

    except Exception as e:
        print(f"Error scraping: {e}")
        return []

def inject_to_app(data):
    if not os.path.exists(APP_FILE):
        print(f"Error: {APP_FILE} not found.")
        return

    print(f"Injecting {len(data)} items into {APP_FILE}...")
    
    with open(APP_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # Create JSON string
    json_data = json.dumps(data, ensure_ascii=False)
    
    # We look for `let appData = [];` or `let appData = [...];`
    # Regex replacement
    new_content = re.sub(
        r'let appData\s*=\s*(?:\[.*?\]|\[\]);',
        f'let appData = {json_data};',
        content,
        flags=re.DOTALL
    )
    
    # Also update the auto-run logic to handle pre-filled data
    # (The existing initApp logic in lunch_app.html basically looks for appData length)
    
    with open(APP_FILE, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    print("Injection complete.")

def main():
    data = scrape_data()
    if data:
        inject_to_app(data)
        print("Success! Open lunch_app.html to view the latest data.")
    else:
        print("No data found.")

if __name__ == "__main__":
    main()
