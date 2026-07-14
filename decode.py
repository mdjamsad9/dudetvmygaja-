import os
import re
import sys
import json
import base64
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from Crypto.Cipher import AES

# Set terminal encoding to UTF-8
sys.stdout.reconfigure(encoding="utf-8")

# Configuration
BASE_URL = "https://raw.githubusercontent.com/anshulajoy10/mygaja/main/"
OUT_DIR = "decrypted_output"

STATIC_KEY = b"6ayJ7jo@ao#pxVc%"
STATIC_IV = b"HsjJTCA7jJztpL2w"

# Ensure output directory structure
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "cats"), exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "channels"), exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "highlights"), exist_ok=True)

def clean_and_decode_b64(encrypted_b64):
    clean_str = "".join(encrypted_b64.split())
    padding = len(clean_str) % 4
    if padding:
        clean_str += "=" * (4 - padding)
    try:
        return base64.urlsafe_b64decode(clean_str)
    except Exception:
        return base64.b64decode(clean_str)

def decrypt_cbc(ciphertext_bytes, key, iv):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(ciphertext_bytes)
    if len(decrypted) > 0:
        pad_len = decrypted[-1]
        if 1 <= pad_len <= 16 and all(x == pad_len for x in decrypted[-pad_len:]):
            decrypted = decrypted[:-pad_len]
    return decrypted

def fetch_and_decrypt_json(url_path):
    # Properly escape URL paths (handles spaces and special characters)
    escaped_path = urllib.parse.quote(url_path)
    url = f"{BASE_URL}{escaped_path}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            raw_data = res.read().decode("utf-8")
            if not raw_data.strip():
                return None
            response_json = json.loads(raw_data)
            
        payload = response_json.get("data")
        if not payload:
            return None
            
        enc_bytes = clean_and_decode_b64(payload)
        
        # Check for DEADBEEF format (starts with \xde\xad\xbe\xef)
        if len(enc_bytes) >= 20 and enc_bytes[:4] == b'\xde\xad\xbe\xef':
            iv = enc_bytes[4:20]
            ciphertext = enc_bytes[20:]
            dec_bytes = decrypt_cbc(ciphertext, STATIC_KEY, iv)
        else:
            dec_bytes = decrypt_cbc(enc_bytes, STATIC_KEY, STATIC_IV)
            
        dec_str = dec_bytes.decode("utf-8", errors="ignore")
        # Clean trailing PKCS7 padding bytes just in case
        dec_str = dec_str.rstrip('\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10')
        
        return json.loads(dec_str)
    except urllib.error.HTTPError as he:
        if he.code == 404:
            return None
        print(f"HTTP Error fetching {url_path}: {he.code} {he.reason}")
        return None
    except Exception as e:
        print(f"Error processing {url_path}: {e}")
        return None

def write_api_specification(out_dir):
    spec = {
        "api_name": "DUDE TV (Gaja TV) Decrypted API Database",
        "base_url": "https://mdjamsad9.github.io/dudetvmygaja-/decrypted_output",
        "description": "This is a clean, fully decrypted mirror of the Gaja TV API database, hosted via GitHub Pages and automatically updated every 5 minutes.",
        "endpoints": {
            "categories_menu": {
                "path": "/cats.json",
                "description": "Main category menu list. Contains category titles, images, and links.",
                "fields": {
                    "id": "Unique category identifier",
                    "title": "Category display name",
                    "image": "Category thumbnail URL",
                    "catLink": "Path to the subcategory channels list (e.g. 'cats/bangla.json') or an external stream link"
                },
                "usage_flow": "Step 1: Fetch this file to render the menu. When the user selects a category, fetch its subcategory file from 'base_url + /cats/{catLink}'."
            },
            "sports_channels": {
                "path": "/cats/sports.json",
                "description": "List of standard sports channels.",
                "fields": {
                    "id": "Unique channel identifier (e.g. '7')",
                    "title": "Channel display name",
                    "image": "Channel logo URL",
                    "catLink": "Subcategory category path"
                },
                "usage_flow": "To play a channel: Fetch its stream details from 'base_url + /channels/{id}.json' (e.g. '/channels/7.json')."
            },
            "live_events": {
                "path": "/events.json",
                "description": "List of live and upcoming sports matches and events.",
                "fields": {
                    "id": "Unique event identifier (e.g. 50008)",
                    "title": "Event title",
                    "eventInfo": "Object containing team names, flags, start time, and end time"
                },
                "usage_flow": "To play a live match/event: Fetch its stream links using 'base_url + /channels/{id}.json' (e.g. '/channels/50008.json')."
            },
            "live_events_combined": {
                "path": "/events_with_channels.json",
                "description": "A consolidated database combining all live events directly with their decrypted channel stream links. Recommended for web and single-page apps to avoid multiple fetch requests.",
                "fields": {
                    "id": "Event identifier",
                    "title": "Event title",
                    "eventInfo": "Event team information",
                    "decoded_channels": "Array of decrypted play links and ClearKey DRM keys",
                    "channel_status": "Status of the event stream ('live' or 'unavailable')"
                },
                "usage_flow": "Fetch this file to display live events. If 'channel_status' is 'live', play the stream directly from 'decoded_channels' without making separate fetch requests."
            },
            "highlights": {
                "path": "/highlights.json",
                "description": "List of sports highlights videos.",
                "fields": {
                    "id": "Unique highlight identifier",
                    "title": "Highlight title",
                    "image": "Highlight thumbnail URL"
                },
                "usage_flow": "To play a highlight: Fetch its stream links from 'base_url + /channels/{id}.json'."
            },
            "app_settings": {
                "path": "/app_data.json",
                "description": "App notice, version config, update URLs, and sponsorship ads configurations.",
                "fields": {
                    "sig": "Signature hash",
                    "dataRows": "Key-value rows of app configurations (Version, Website, Message, Update Link, Email)"
                }
            }
        }
    }
    
    spec_file = os.path.join(out_dir, "api_specification.json")
    with open(spec_file, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)

def save_json(data, filename):
    out_path = os.path.join(OUT_DIR, filename)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def main():
    print("=== Gaja GitHub Auto-Decoder Starting ===")
    print(f"Target Repository Raw URL: {BASE_URL}")
    print(f"Output Directory: {os.path.abspath(OUT_DIR)}")
    print("------------------------------------------")

    # 1. Fetch and Decrypt main config files
    main_files = [
        "cats.json",
        "eventcats.json",
        "events.json",
        "highlights.json",
        "app.json",
        "app_data.json",
        "app_new.json"
    ]
    
    decrypted_main = {}
    for filename in main_files:
        print(f"Processing {filename}...")
        data = fetch_and_decrypt_json(filename)
        if data:
            save_json(data, filename)
            decrypted_main[filename] = data
            print(f"  [SUCCESS] Decrypted and saved {filename} ({len(data)} items)")
        else:
            print(f"  [WARNING] Could not fetch or decrypt {filename}")

    # 2. Fetch and Decrypt subcategory files
    cats_data = decrypted_main.get("cats.json", [])
    unique_channel_ids = set()
    
    print("\nProcessing Subcategories from cats.json...")
    for cat in cats_data:
        title = cat.get("title")
        cat_link = cat.get("catLink")
        if not cat_link or cat_link.startswith("http"):
            continue
            
        # Standardize path
        if not "/" in cat_link:
            # e.g. "Sports" -> try both "cats/sports.json" and "sports.json"
            paths_to_try = [f"cats/{cat_link.lower()}.json", f"{cat_link.lower()}.json"]
        else:
            paths_to_try = [cat_link]
            
        sub_data = None
        used_path = None
        for path in paths_to_try:
            sub_data = fetch_and_decrypt_json(path)
            if sub_data:
                used_path = path
                break
                
        if sub_data:
            save_json(sub_data, used_path)
            print(f"  [SUCCESS] Decrypted category: {title} ({used_path}) -> {len(sub_data)} channels")
            # Collect channel IDs
            for ch in sub_data:
                ch_id = ch.get("id")
                if ch_id:
                    unique_channel_ids.add(str(ch_id))
        else:
            print(f"  [WARNING] Category failed to load: {title} (Tried paths: {paths_to_try})")

    # 3. Collect additional channel IDs from events and highlights
    events_data = decrypted_main.get("events.json", [])
    for event in events_data:
        ev_id = event.get("id")
        if ev_id:
            unique_channel_ids.add(str(ev_id))
            
    highlights_data = decrypted_main.get("highlights.json", [])
    if isinstance(highlights_data, list):
        for hl in highlights_data:
            hl_id = hl.get("id")
            if hl_id:
                unique_channel_ids.add(str(hl_id))

    print(f"\nCollected {len(unique_channel_ids)} unique channel/event stream IDs.")

    # 4. Fetch and Decrypt all unique channels in parallel
    print("Fetching and decrypting channel details in parallel...")
    decrypted_channels = {}
    
    def worker(ch_id):
        path = f"channels/{ch_id}.json"
        data = fetch_and_decrypt_json(path)
        return ch_id, data, path

    # Using 12 threads for faster parallel downloads
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(worker, ch_id) for ch_id in unique_channel_ids]
        
        success_count = 0
        for future in as_completed(futures):
            ch_id, data, path = future.result()
            if data:
                save_json(data, path)
                decrypted_channels[ch_id] = data
                success_count += 1
                if success_count % 10 == 0 or success_count == len(unique_channel_ids):
                    print(f"  Progress: Decrypted {success_count} channels...")
                    
    print(f"Successfully decrypted and saved {success_count} individual channels.")

    # 5. Build combined events_with_channels.json file
    print("\nConsolidating combined events_with_channels.json...")
    events_with_channels = []
    for event in events_data:
        event_id = str(event.get("id"))
        event_copy = dict(event)
        
        # Check if we have decrypted channel data for this event
        channels_info = decrypted_channels.get(event_id)
        if channels_info:
            event_copy["decoded_channels"] = channels_info
            event_copy["channel_status"] = "live"
        else:
            event_copy["decoded_channels"] = []
            event_copy["channel_status"] = "unavailable"
            
        events_with_channels.append(event_copy)
        
    save_json(events_with_channels, "events_with_channels.json")
    print("  [SUCCESS] Saved events_with_channels.json")

    # Generate API Specification
    print("\nGenerating api_specification.json...")
    write_api_specification(OUT_DIR)
    print("  [SUCCESS] Saved api_specification.json")

    print("\n==========================================")
    print("DECRYPTION AND PROCESSING COMPLETE!")
    print("All files saved to: decrypted_output/")
    print("==========================================")

if __name__ == "__main__":
    main()
