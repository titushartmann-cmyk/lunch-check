import os
import requests
import json
import re
import time
import urllib.parse
from html.parser import HTMLParser

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_FILE = os.path.join(BASE_DIR, "index.html")
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

def get_form_data(html):
    """Extracts all form fields needed for ASP.NET PostBack."""
    data = {}
    # Extract basic inputs
    inputs = re.findall(r'<input[^>]*name="([^"]*)"[^>]*value="([^"]*)"[^>]*>', html)
    for name, value in inputs:
        data[name] = value
        
    # Extract hidden inputs that might have empty values not caught above (regex improvements)
    # Simple regex for inputs
    # We specifically need __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION
    for key in ['__VIEWSTATE', '__VIEWSTATEGENERATOR', '__EVENTVALIDATION']:
        if key not in data:
            match = re.search(r'id="' + key + r'" value="(.*?)"', html)
            if match:
                data[key] = match.group(1)
            
    return data

def scrape_data():
    print(f"Fetching data from {URL}...")
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; LunchScraper/1.0)'})
    
    try:
        # 1. Initial GET to get ViewState
        res = session.get(URL, timeout=30)
        res.raise_for_status()
        
        # 2. Prepare POST for 500 items
        form_data = get_form_data(res.text)
        
        # Determine the uniqueID of the dropdown. From debug analysis:
        # name="ctl00$SheetContentPlaceHolder$ctl00$ctl01$ddlPageSize"
        ddl_name = "ctl00$SheetContentPlaceHolder$ctl00$ctl01$ddlPageSize"
        
        form_data['__EVENTTARGET'] = ddl_name
        form_data['__EVENTARGUMENT'] = ''
        form_data[ddl_name] = '500' # Request 500 items
        
        # Remove button clicks if any were captured (usually not in hidden fields)
        
        print("Requesting 500 items (PostBack)...")
        res_post = session.post(URL, data=form_data, timeout=60)
        res_post.raise_for_status()
        html = res_post.text
        
        # 3. Extract Data from POST response
        # Regex extraction based on ASP.NET IDs
        names = re.findall(r'id=".*?_Label3">(.*?)</span>', html)
        addrs = re.findall(r'id=".*?_Label5">(.*?)</span>', html)
        zips = re.findall(r'id=".*?_Label7">(.*?)</span>', html)
        cities = re.findall(r'id=".*?_Label8">(.*?)</span>', html)
        urls = re.findall(r'id=".*?_LinkButton1".*?>(.*?)</a>', html)
        
        print(f"Found {len(names)} items.")
        
        data = []
        min_len = min(len(names), len(addrs), len(zips), len(cities))
        
        print(f"Enriching {min_len} items (Geocoding)... this may take a while.")
        
        for i in range(min_len):
            website = urls[i] if i < len(urls) else ""
            if "javascript:" in website: website = "" 
            
            # Basic Item
            item = {
                'Restaurant': names[i].strip(),
                'Adresse': addrs[i].strip(),
                'PLZ': zips[i].strip(),
                'Ort': cities[i].strip(),
                'Website': website.strip(),
                'cuisine': None,
                'lat': None,
                'lon': None,
                'walkingTime': 999 
            }
            
            # Enrich
            try:
                query = f"{item['Adresse']} {item['Ort']}"
                # Use Photon API
                geo_url = f"https://photon.komoot.io/api/?q={urllib.parse.quote(query)}&limit=1"
                geo_res = requests.get(geo_url, timeout=5)
                if geo_res.status_code == 200:
                    geo_data = geo_res.json()
                    if geo_data['features']:
                        feat = geo_data['features'][0]
                        item['lon'] = feat['geometry']['coordinates'][0]
                        item['lat'] = feat['geometry']['coordinates'][1]
                        
                        # Extract Cuisine
                        props = feat['properties']
                        c_val = props.get('cuisine')
                        if not c_val:
                            osm_val = props.get('osm_value')
                            if osm_val and osm_val not in ['yes', 'restaurant', 'fast_food', 'cafe', 'bar']:
                                c_val = osm_val
                        
                        item['cuisine'] = c_val.capitalize() if c_val else "International"
                    else:
                        item['cuisine'] = "International"
            except Exception as err:
                print(f"Enrichment error for {item['Restaurant']}: {err}")
                item['cuisine'] = "International"

            data.append(item)
            # Rate limit compliance (Photon is generous but let's be safe)
            time.sleep(0.5)
            
            if i % 10 == 0:
                print(f"Processed {i}/{min_len}...")
            
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
