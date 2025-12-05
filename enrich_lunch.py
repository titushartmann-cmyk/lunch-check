import csv
import glob
import os
import requests
import json
import time
from datetime import datetime
from urllib.parse import quote

# Configuration
# Script searches the directory where it is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "lunch_widget.html")
TEMPLATE_FILE = os.path.join(BASE_DIR, "widget_template.html")

# Limit items for demo purposes to avoid long runtimes (rate limits)
LIMIT = 50

# OSRM Demo Server
OSRM_URL = "http://router.project-osrm.org/route/v1/foot/"

# Header for Geocoding
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; LunchWidget/1.0)'
}

def find_input_file(directory):
    """Finds a CSV file with 'export' or 'lunch' in the name."""
    print(f"Searching in {directory}...")
    try:
        candidates = glob.glob(os.path.join(directory, "*.csv"))
        for f in candidates:
            filename = os.path.basename(f).lower()
            if "lunch" in filename or "export" in filename:
                print(f"Found input file: {f}")
                return f
        
        # Fallback
        for f in candidates:
             if "mock" not in f.lower() and "export" not in f.lower():
                 pass
             if "mock" not in f.lower(): 
                print(f"Found candidate input file: {f}")
                return f

    except Exception as e:
        print(f"Could not search directory: {e}")
    
    return None

def geocode_address(address):
    """Geocode address using Photon (Komoot)."""
    try:
        # Use Photon API (Komoot) - usually faster and fewer blocks than standard Nominatim
        url = f"https://photon.komoot.io/api/?q={quote(address)}&limit=1"
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data and data['features']:
                # Photon returns [lon, lat]
                coords = data['features'][0]['geometry']['coordinates']
                return float(coords[1]), float(coords[0]) # Return lat, lon
    except Exception as e:
        print(f"Geocoding error for {address}: {e}")
    return None, None

def get_walking_time(start_coords, end_coords):
    """Get walking duration from OSRM."""
    if not start_coords or not end_coords:
        return "N/A", 999
    
    try:
        coords = f"{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}"
        url = f"{OSRM_URL}{coords}?overview=false"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data['code'] == 'Ok' and data['routes']:
                duration_seconds = data['routes'][0]['duration']
                minutes = int(duration_seconds / 60)
                return f"{minutes} min", minutes
    except Exception as e:
        print(f"Routing error: {e}")
    
    return "N/A", 999

def read_csv(filepath):
    """Read CSV file and return list of dicts."""
    items = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            header = f.readline()
            delimiter = ';' if ';' in header else ','
            
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                items.append(row)
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return items

def render_template(items):
    """Simple template rendering."""
    print(f"Rendering {len(items)} items...")
    try:
        if not os.path.exists(TEMPLATE_FILE):
             print(f"Error: Template file not found at {TEMPLATE_FILE}")
             return

        with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
            template = f.read()
        
        start_tag = "{% for item in items %}"
        end_tag = "{% endfor %}"
        
        if start_tag not in template or end_tag not in template:
            print("Template tags not found.")
            return

        pre_loop, rest = template.split(start_tag)
        loop_content, post_loop = rest.split(end_tag)
        
        rendered_items = ""
        
        for item in items:
            item_html = loop_content
            
            # Additional keys created by enrichment
            item_html = item_html.replace("{{ item.walking_time }}", str(item.get('walking_time', 'N/A')))
            item_html = item_html.replace("{{ item.walking_time_raw }}", str(item.get('walking_time_raw', 999)))
            item_html = item_html.replace("{{ item.maps_url }}", str(item.get('maps_url', '#')))
            
            # Replace basic variables from CSV
            for key, value in item.items():
                if value is None: value = ""
                # Avoid re-replacing the special keys if they exist in CSV (unlikely but safe)
                if key not in ['walking_time', 'walking_time_raw', 'maps_url']:
                    item_html = item_html.replace(f"{{{{ item.{key} }}}}", str(value))
            
            rendered_items += item_html

        final_html = pre_loop + rendered_items + post_loop
        final_html = final_html.replace("{{ generation_date }}", datetime.now().strftime("%Y-%m-%d"))
        final_html = final_html.replace("{{ items_count }}", str(len(items)))
        
        # Save output
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(final_html)
        print(f"Widget generated successfully at: {OUTPUT_FILE}")
        
    except Exception as e:
        print(f"Error rendering template: {e}")

def main():
    print("Starting Lunch Widget Generator...")
    
    # 1. Find Data
    input_file = find_input_file(BASE_DIR)
    if not input_file:
        print(f"No input file found in {BASE_DIR}. Please ensure your export file is there.")
        return

    # 2. Read Data
    items = read_csv(input_file)
    print(f"Loaded {len(items)} restaurants. Processing top {LIMIT} for demo...")
    items = items[:LIMIT]
    
    if not items:
        print("No items found in CSV.")
        return
    
    # 3. Enrich Data
    # Central Zurich (Paradeplatz)
    user_coords = (47.3696, 8.5380) 
    print(f"Calculating walking time from Central Zurich...")
    
    for item in items:
        address = f"{item.get('Adresse', '')}, {item.get('PLZ', '')} {item.get('Ort', '')}"
        
        # Geocode
        lat, lon = geocode_address(address)
        
        if lat and lon:
            # Get Walking Time
            walking_time_str, walking_time_raw = get_walking_time(user_coords, (lat, lon))
            item['walking_time'] = walking_time_str
            item['walking_time_raw'] = walking_time_raw
        else:
            item['walking_time'] = "?"
            item['walking_time_raw'] = 999
            
        # Pre-calculate Maps URL
        # destination format: Address, City
        dest = f"{item.get('Adresse', '')}, {item.get('Ort', '')}"
        item['maps_url'] = f"https://www.google.com/maps/dir/?api=1&destination={quote(dest)}"

    # 4. Generate Widget
    render_template(items)

if __name__ == "__main__":
    main()
