import os
import re
import sys
import json
import base64
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from Crypto.Cipher import AES

# Set terminal encoding to UTF-8
sys.stdout.reconfigure(encoding="utf-8")

# Configuration
BASE_URL = "https://mymodi.top/"
OUT_DIR = "decrypted_output"

STATIC_KEY = b"6ayJ7jo@ao#pxVc%"
STATIC_IV = b"HsjJTCA7jJztpL2w"

# Ensure output directory structure
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "cats"), exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "channels"), exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "event_channels"), exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "highlight_channels"), exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "highlights"), exist_ok=True)

def check_adb_devices():
    try:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
        lines = res.stdout.strip().splitlines()
        devices = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices
    except Exception:
        return []

def get_device_paths():
    try:
        res = subprocess.run(["adb", "shell", "pm", "path", "com.sportzx.live"], capture_output=True, text=True, check=True)
        apk_path = res.stdout.strip().replace("package:", "")
        if not apk_path:
            return None, None
        lib_dir = apk_path.replace("base.apk", "") + "lib/x86_64"
        lib_path = f"{lib_dir}/libnative-lib.so"
        return apk_path, lib_path
    except Exception as e:
        print(f"Failed to find device app paths: {e}")
        return None, None

def ensure_decryptor_jar():
    local_jar_path = "Decryptor.jar"
    try:
        subprocess.run(["adb", "push", local_jar_path, "/data/local/tmp/Decryptor.jar"], check=True, capture_output=True)
        print("Decryptor.jar verified and pushed to emulator.")
    except Exception as e:
        print(f"Failed to push Decryptor.jar: {e}")

def clean_and_decode_b64(encrypted_b64):
    clean_str = "".join(encrypted_b64.split())
    std_b64 = clean_str.replace("-", "+").replace("_", "/")
    padding = len(std_b64) % 4
    if padding:
        std_b64 += "=" * (4 - padding)
    try:
        return base64.b64decode(std_b64)
    except Exception:
        return base64.urlsafe_b64decode(std_b64)

def decrypt_cbc(ciphertext_bytes, key, iv):
    if len(ciphertext_bytes) % 16 != 0:
        ciphertext_bytes = ciphertext_bytes[:len(ciphertext_bytes) - (len(ciphertext_bytes) % 16)]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(ciphertext_bytes)
    if len(decrypted) > 0:
        pad_len = decrypted[-1]
        if 1 <= pad_len <= 16 and all(x == pad_len for x in decrypted[-pad_len:]):
            decrypted = decrypted[:-pad_len]
    return decrypted


emulator_lock = threading.Lock()

def decrypt_via_emulator(payload, apk_path, lib_path):
    with emulator_lock:
        return _decrypt_via_emulator_locked(payload, apk_path, lib_path)

def _decrypt_via_emulator_locked(payload, apk_path, lib_path):
    temp_file = "temp_payload.txt"
    device_file = "/data/local/tmp/payload.txt"
    try:
        subprocess.run(["adb", "root"], capture_output=True)
        subprocess.run(["adb", "wait-for-device"], capture_output=True)
        whoami_res = subprocess.run(["adb", "shell", "whoami"], capture_output=True)
        whoami_out = whoami_res.stdout.decode("utf-8", errors="ignore")
        is_root = "root" in whoami_out
        
        def run_root_cmd(cmd):
            if is_root:
                subprocess.run(["adb", "shell", cmd], capture_output=True)
            else:
                res = subprocess.run(["adb", "shell", f"su -c '{cmd}'"], capture_output=True)
                res_err = res.stderr.decode("utf-8", errors="ignore")
                res_out = res.stdout.decode("utf-8", errors="ignore")
                if "invalid uid/gid" in res_err or "invalid uid/gid" in res_out:
                    subprocess.run(["adb", "shell", f"su root {cmd}"], capture_output=True)

        pid_check = subprocess.run(["adb", "shell", "pidof com.sportzx.live"], capture_output=True)
        pid_out = pid_check.stdout.decode("utf-8", errors="ignore").strip()
        if not pid_out:
            print("      [Frida Fallback] App is not running. Launching SportzX...")
            run_root_cmd("setenforce 0")
            subprocess.run(["adb", "shell", "am start -n com.sportzx.live/com.sportzx.live.activities.SplashActivity"], capture_output=True)
            for _ in range(12):
                pid_check = subprocess.run(["adb", "shell", "pidof com.sportzx.live"], capture_output=True)
                pid_out = pid_check.stdout.decode("utf-8", errors="ignore").strip()
                if pid_out:
                    break
                time.sleep(1)
            time.sleep(12)
        
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(payload)
        subprocess.run(["adb", "push", temp_file, device_file], check=True, capture_output=True)
        
        run_root_cmd("rm -f /data/user/0/com.sportzx.live/cache/decrypted_raw.bin")
        
        frida_ps = subprocess.run(["adb", "shell", "ps -A | grep frida-server"], capture_output=True)
        frida_ps_out = frida_ps.stdout.decode("utf-8", errors="ignore")
        if "frida-server" not in frida_ps_out:
            check_fs = subprocess.run(["adb", "shell", "ls /data/local/tmp/frida-server"], capture_output=True)
            check_fs_err = check_fs.stderr.decode("utf-8", errors="ignore")
            check_fs_out = check_fs.stdout.decode("utf-8", errors="ignore")
            if "No such file" in check_fs_err or "frida-server" not in check_fs_out:
                print("      [Frida Fallback] frida-server not found on device. Preparing push...")
                if os.path.exists("frida-server"):
                    subprocess.run(["adb", "push", "frida-server", "/data/local/tmp/frida-server"], check=True)
                elif os.path.exists("frida-server.xz"):
                    print("      [Frida Fallback] Extracting frida-server.xz on host...")
                    import lzma
                    with lzma.open("frida-server.xz", "rb") as f_in:
                        with open("frida-server", "wb") as f_out:
                            f_out.write(f_in.read())
                    subprocess.run(["adb", "push", "frida-server", "/data/local/tmp/frida-server"], check=True)
                else:
                    print("      [Frida Fallback] Warning: frida-server binary or xz archive not found locally.")
                run_root_cmd("chmod 755 /data/local/tmp/frida-server")

            print("      [Frida Fallback] Starting frida-server...")
            if is_root:
                subprocess.Popen(["adb", "shell", "nohup /data/local/tmp/frida-server > /dev/null 2>&1 &"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                test_mm = subprocess.run(["adb", "shell", "su -mm -c 'id'"], capture_output=True)
                test_mm_err = test_mm.stderr.decode("utf-8", errors="ignore")
                test_mm_out = test_mm.stdout.decode("utf-8", errors="ignore")
                if "invalid uid/gid" in test_mm_err or "invalid uid/gid" in test_mm_out:
                    subprocess.Popen(["adb", "shell", "su root nohup /data/local/tmp/frida-server > /dev/null 2>&1 &"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(["adb", "shell", "su -mm -c 'nohup /data/local/tmp/frida-server > /dev/null 2>&1 &'"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(10):
                res = subprocess.run(["frida-ps", "-U"], capture_output=True)
                if res.returncode == 0:
                    break
                time.sleep(1.5)
            
        pid_res = subprocess.run(["adb", "shell", "pidof com.sportzx.live"], capture_output=True)
        pid = pid_res.stdout.decode("utf-8", errors="ignore").strip()
        if pid:
            pid = pid.split()[0]
        else:
            ps_cmd = subprocess.run(["adb", "shell", "ps | grep com.sportzx.live"], capture_output=True)
            ps_out = ps_cmd.stdout.decode("utf-8", errors="ignore")
            match = re.search(r'\s+(\d+)\s+', ps_out)
            if match:
                pid = match.group(1)
        
        if pid:
            frida_cmd = ["frida", "-U", "-p", pid, "-l", "decrypt_script.js"]
        else:
            frida_cmd = ["frida", "-U", "-n", "com.sportzx.live", "-l", "decrypt_script.js"]
        output = ""
        stderr_output = ""
        try:
            res = subprocess.run(frida_cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=15)
            output = res.stdout.decode("utf-8", errors="ignore") if res.stdout else ""
            stderr_output = res.stderr.decode("utf-8", errors="ignore") if res.stderr else ""
        except subprocess.TimeoutExpired as te:
            output = te.stdout.decode("utf-8", errors="ignore") if te.stdout else ""
            stderr_output = te.stderr.decode("utf-8", errors="ignore") if te.stderr else ""
        except Exception as fe:
            print(f"      [Frida Fallback] process error: {fe}")
                
        success = False
        saved_path = None
        for line in output.splitlines():
            if "SUCCESS!" in line:
                success = True
                parts = line.split("saved to:")
                if len(parts) > 1:
                    saved_path = parts[1].strip()
                break
            
        if not success or not saved_path:
            print("      [Frida Fallback] Frida decryption failed or output path not parsed.")
            print(f"      [Frida Debug] stdout: {output}")
            print(f"      [Frida Debug] stderr: {stderr_output}")
            saved_path = "/data/user/0/com.sportzx.live/cache/decrypted_raw.bin"
            
        local_temp = os.path.join(os.getcwd(), "temp_decrypted.bin")
        if os.path.exists(local_temp):
            os.remove(local_temp)
            
        if is_root:
            subprocess.run(["adb", "shell", f"cp {saved_path} /data/local/tmp/decrypted_raw.bin"], capture_output=True)
            subprocess.run(["adb", "shell", "chmod 666 /data/local/tmp/decrypted_raw.bin"], capture_output=True)
        else:
            res = subprocess.run(["adb", "shell", f"su -c 'cp {saved_path} /data/local/tmp/decrypted_raw.bin && chmod 666 /data/local/tmp/decrypted_raw.bin'"], capture_output=True)
            res_err = res.stderr.decode("utf-8", errors="ignore")
            res_out = res.stdout.decode("utf-8", errors="ignore")
            if "invalid uid/gid" in res_err or "invalid uid/gid" in res_out:
                subprocess.run(["adb", "shell", f"su root 'cp {saved_path} /data/local/tmp/decrypted_raw.bin && chmod 666 /data/local/tmp/decrypted_raw.bin'"], capture_output=True)
                
        subprocess.run(["adb", "pull", "/data/local/tmp/decrypted_raw.bin", local_temp], capture_output=True)
        
        raw_bytes = b""
        if os.path.exists(local_temp):
            with open(local_temp, "rb") as lf:
                raw_bytes = lf.read()
            os.remove(local_temp)
        subprocess.run(["adb", "shell", "rm -f /data/local/tmp/decrypted_raw.bin"], capture_output=True)
        
        if len(raw_bytes) == 0:
            print("      [Frida Fallback] Decrypted file is empty or not readable.")
            return None
            
        try:
            text = raw_bytes.decode("utf-16be", errors="ignore").strip()
        except Exception:
            low_bytes = bytes(raw_bytes[i+1] for i in range(0, len(raw_bytes)-1, 2))
            text = low_bytes.decode("utf-8", errors="ignore").strip()

        start_idx = -1
        first_bracket = text.find('[')
        first_brace = text.find('{')
        if first_bracket != -1 and first_brace != -1:
            start_idx = min(first_bracket, first_brace)
        elif first_bracket != -1:
            start_idx = first_bracket
        elif first_brace != -1:
            start_idx = first_brace

        if start_idx != -1:
            text = text[start_idx:]

        last_bracket = text.rfind(']')
        last_brace = text.rfind('}')
        end_idx = max(last_bracket, last_brace)
        if end_idx != -1:
            text = text[:end_idx + 1]

        if not text:
            print("      [Frida Fallback] Output does not contain valid JSON boundaries.")
            return None

        try:
            return json.loads(text, strict=False)
        except Exception as je:
            print(f"      [Frida Fallback] json.loads initial attempt failed: {je}")
            if last_bracket != -1 and text.startswith('['):
                try:
                    return json.loads(text[:last_bracket + 1], strict=False)
                except Exception:
                    pass
            if last_brace != -1 and text.startswith('{'):
                try:
                    return json.loads(text[:last_brace + 1], strict=False)
                except Exception:
                    pass
            cleaned_text = re.sub(r',(\s*[\]}])', r'\1', text)
            try:
                return json.loads(cleaned_text, strict=False)
            except Exception as final_e:
                print(f"      [Frida Fallback] JSON parsing recovery failed: {final_e}")
                return None
            
    except Exception as e:
        print(f"      [Frida Fallback] Unexpected error: {e}")
        return None
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

def decrypt_data(payload, apk_path=None, lib_path=None):
    try:
        enc_bytes = clean_and_decode_b64(payload)
        
        if len(enc_bytes) >= 20 and enc_bytes[:4] == b'\xde\xad\xbe\xef':
            iv = enc_bytes[4:20]
            ciphertext = enc_bytes[20:]
            dec = decrypt_cbc(ciphertext, STATIC_KEY, iv)
        elif len(enc_bytes) >= 21 and enc_bytes[1:5] == b'\xde\xad\xbe\xef':
            iv = enc_bytes[5:21]
            ciphertext = enc_bytes[21:]
            dec = decrypt_cbc(ciphertext, STATIC_KEY, iv)
        elif len(enc_bytes) >= 17 and enc_bytes[0] == 2:
            iv = enc_bytes[1:17]
            ciphertext = enc_bytes[17:]
            dec = decrypt_cbc(ciphertext, STATIC_KEY, iv)
        else:
            dec = decrypt_cbc(enc_bytes, STATIC_KEY, STATIC_IV)
            
        dec_str = dec.decode("utf-8", errors="ignore").strip().rstrip('\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10').strip()
        
        if dec_str.startswith('[') and not dec_str.endswith(']'):
            last_bracket = dec_str.rfind(']')
            if last_bracket >= 0:
                dec_str = dec_str[:last_bracket + 1]

        try:
            return json.loads(dec_str, strict=False)
        except Exception:
            last_bracket = dec_str.rfind(']')
            if last_bracket >= 0:
                clean_json = dec_str[:last_bracket + 1]
                return json.loads(clean_json, strict=False)
                
    except Exception as e:
        print(f"      Decryption attempt failed: {e}")
        if apk_path and lib_path:
            try:
                print("      Trying emulator JNI fallback...")
                return decrypt_via_emulator(payload, apk_path, lib_path)
            except Exception as jnie:
                print(f"      JNI fallback failed: {jnie}")
        return None

def fetch_and_decrypt_json(url_path, apk_path=None, lib_path=None):
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
            
        return decrypt_data(payload, apk_path, lib_path)
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
        "api_usage_guide": {
            "categories_and_channels_flow": {
                "step_1_fetch_categories": "Fetch '/cats.json' to get the menu category list (e.g. Sports, Bangla, Entertainment).",
                "step_2_fetch_subcategory_channels": "For any category, look at the 'catLink' field (e.g. 'cats/bangla.json'). Fetch this file from 'base_url + /cats/{catLink}' to get the channels in that category.",
                "step_3_get_stream_details": "Each channel in the subcategory list has a unique 'id' (e.g. '7'). Fetch 'base_url + /channels/{id}.json' (e.g. '/channels/7.json') to get the decrypted M3U8 URLs, referers, and ClearKey DRM details."
            },
            "live_events_flow": {
                "step_1_fetch_events": "Fetch '/events.json' to get the list of active/upcoming live sports matches.",
                "step_2_get_stream_details": "Each live event has a unique 'id' (e.g. 50008). Fetch 'base_url + /event_channels/{id}.json' (e.g. '/event_channels/50008.json') to get the decrypted streaming links. Note: These event channels are created dynamically and are only accessible while the match is live."
            },
            "highlights_flow": {
                "step_1_fetch_highlights": "Fetch '/highlights.json' to get the list of available sports highlights.",
                "step_2_get_stream_details": "Each highlight has a unique 'id' (e.g. 100027). Fetch 'base_url + /highlight_channels/{id}.json' (e.g. '/highlight_channels/100027.json') to get the decrypted highlights play links."
            },
            "simplified_single_request_flow": {
                "recommendation": "If you are building a website or app and want to avoid multiple fetch requests for live events, fetch '/events_with_channels.json' directly. It has all active live matches pre-merged with their decrypted play links inside the 'decoded_channels' field."
            }
        },
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
            "subcategory_channels": {
                "path": "/cats/{catLink}.json",
                "description": "List of channels inside a specific subcategory (e.g. sports, bangla).",
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
                "usage_flow": "To play a live match/event: Fetch its stream links using 'base_url + /event_channels/{id}.json' (e.g. '/event_channels/50008.json')."
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
                "usage_flow": "To play a highlight: Fetch its stream links from 'base_url + /highlight_channels/{id}.json'."
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

    devices = check_adb_devices()
    apk_path, lib_path = None, None
    if not devices:
        print("WARNING: No emulator/device detected via ADB.")
        print("Continuing with local decryption fallback only.")
    else:
        print(f"Connected devices: {devices}")
        print("Ensuring adb runs as root...")
        subprocess.run(["adb", "root"], capture_output=True)
        subprocess.run(["adb", "wait-for-device"], capture_output=True)
        apk_path, lib_path = get_device_paths()
        if apk_path and lib_path:
            ensure_decryptor_jar()
            print("Emulator decryption engine is READY!")

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
        data = fetch_and_decrypt_json(filename, apk_path, lib_path)
        if data:
            save_json(data, filename)
            decrypted_main[filename] = data
            print(f"  [SUCCESS] Decrypted and saved {filename} ({len(data)} items)")
        else:
            print(f"  [WARNING] Could not fetch or decrypt {filename}")

    # 2. Fetch and Decrypt subcategory files and collect TV channel IDs
    cats_data = decrypted_main.get("cats.json", [])
    tv_channel_ids = set()
    
    print("\nProcessing Subcategories from cats.json...")
    for cat in cats_data:
        title = cat.get("title")
        cat_link = cat.get("catLink")
        if not cat_link or cat_link.startswith("http"):
            continue
            
        # Standardize path
        if not "/" in cat_link:
            paths_to_try = [f"cats/{cat_link.lower()}.json", f"{cat_link.lower()}.json"]
        else:
            paths_to_try = [cat_link]
            
        sub_data = None
        used_path = None
        for path in paths_to_try:
            sub_data = fetch_and_decrypt_json(path, apk_path, lib_path)
            if sub_data:
                used_path = path
                break
                
        if sub_data:
            save_json(sub_data, used_path)
            print(f"  [SUCCESS] Decrypted category: {title} ({used_path}) -> {len(sub_data)} channels")
            for ch in sub_data:
                ch_id = ch.get("id")
                if ch_id:
                    tv_channel_ids.add(str(ch_id))
        else:
            print(f"  [WARNING] Category failed to load: {title} (Tried paths: {paths_to_try})")

    # 3. Collect Live Event IDs and Highlights IDs separately
    event_channel_ids = set()
    events_data = decrypted_main.get("events.json", [])
    for event in events_data:
        ev_id = event.get("id")
        if ev_id:
            event_channel_ids.add(str(ev_id))
            
    highlight_channel_ids = set()
    highlights_data = decrypted_main.get("highlights.json", [])
    if isinstance(highlights_data, list):
        for hl in highlights_data:
            hl_id = hl.get("id")
            if hl_id:
                highlight_channel_ids.add(str(hl_id))

    print(f"\nCollected IDs to decrypt:")
    print(f"  - TV Channels: {len(tv_channel_ids)}")
    print(f"  - Live Events: {len(event_channel_ids)}")
    print(f"  - Highlights: {len(highlight_channel_ids)}")

    # 4. Fetch and Decrypt all channels in parallel (saving to respective subfolders)
    print("\nFetching and decrypting details in parallel...")
    decrypted_event_channels = {}
    
    # We build tasks list of tuples: (channel_id, local_subfolder)
    tasks = []
    for ch_id in tv_channel_ids:
        tasks.append((ch_id, "channels"))
    for ch_id in event_channel_ids:
        tasks.append((ch_id, "event_channels"))
    for ch_id in highlight_channel_ids:
        tasks.append((ch_id, "highlight_channels"))

    def worker(ch_id, folder):
        # On remote server, all files are stored in channels/{ch_id}.json
        remote_path = f"channels/{ch_id}.json"
        data = fetch_and_decrypt_json(remote_path, apk_path, lib_path)
        return ch_id, folder, data

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(worker, t[0], t[1]) for t in tasks]
        
        success_count = 0
        for future in as_completed(futures):
            ch_id, folder, data = future.result()
            if data:
                # Save locally under decrypted_output/{folder}/{ch_id}.json
                local_filename = os.path.join(folder, f"{ch_id}.json")
                save_json(data, local_filename)
                
                if folder == "event_channels":
                    decrypted_event_channels[ch_id] = data
                    
                success_count += 1
                if success_count % 10 == 0 or success_count == len(tasks):
                    print(f"  Progress: Decrypted {success_count}/{len(tasks)} files...")
                    
    print(f"Successfully decrypted and saved {success_count} files across directories.")

    # 5. Build combined events_with_channels.json file using event_channels
    print("\nConsolidating combined events_with_channels.json...")
    events_with_channels = []
    for event in events_data:
        event_id = str(event.get("id"))
        event_copy = dict(event)
        
        channels_info = decrypted_event_channels.get(event_id)
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
