#!/usr/bin/env python3

import sys 
import requests
import time
from urllib.parse import urlencode, quote

# --- CONSTANTS ---
# Robustness settings for connection
TIMEOUT_SEC = 35 # Generous timeout to handle slow AP startup
MAX_RETRIES = 3 # Max attempts for the initial login phase
RETRY_DELAY = 5 # Seconds to wait between retries

# API Endpoints
URL_LOGIN = "/?username={username}&password={pass_hash}" 
URL_LOAD_CONFIG = "/data/scheduler.association.json?operation=load"
URL_SAVE_CONFIG = "/data/scheduler.association.json?"
URL_LOGOUT = "/logout.html"

# Scheduler Configuration Constant Values
ACTION_ON = "1"
ACTION_OFF = "0"

def control_wifi(host, user, pass_hash, target_ssid, target_band, state):
    """
    Controls the Wi-Fi state (on/off) for a specific SSID and Band on the Access Point.

    Args:
        host (str): The AP's DNS or IP (e.g., 192.168.0.1).
        user (str): Username (used in the final POST, but often 'admin').
        pass_hash (str): The pre-hashed password for authentication.
        target_ssid (str): The SSID to modify (e.g., 'Wi-Fi-Guest').
        target_band (str): The Band to modify (e.g., '5GHz' or '2.4GHz').
        state (str): 'on' or 'off'.
    """
    
    # Ensure URL starts with HTTPS
    if not host.lower().startswith("https://") and not host.lower().startswith("http://"):
        base_url = "https://" + host

    # Map desired state to the AP's action value (0=off, 1=on)
    target_action = ACTION_ON if state.lower() == 'on' else ACTION_OFF

    # Use a single session to handle all cookies automatically
    with requests.Session() as s:
        
        # --- 1. AUTHENTICATION LOOP (Robust Login - Direct POST) ---
        retry_count = 0
        logged_in = False
        
        # Build the full login URL with credentials as query parameters
        login_url_full = f"{base_url}{URL_LOGIN.format(username=user, pass_hash=pass_hash)}"
        
        while retry_count < MAX_RETRIES and not logged_in:
            try:
                print(f"Attempting login (Try {retry_count + 1}/{MAX_RETRIES})...")
                
                # Direct POST to the login URL to establish session (retrieves session cookie)
                s.post(login_url_full, timeout=TIMEOUT_SEC, verify=False) 
                
                logged_in = True 
                
            except requests.exceptions.Timeout:
                retry_count += 1
                if retry_count < MAX_RETRIES:
                    print(f"Connection timed out. Retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                else:
                    print(f"FATAL: Failed to connect after {MAX_RETRIES} attempts due to timeout.", file=sys.stderr)
                    sys.exit(1)
            
            except requests.exceptions.RequestException as e:
                print(f"FATAL: Critical connection error during login POST: {e}", file=sys.stderr)
                sys.exit(1)
        
        if not logged_in:
             print("FATAL: Authentication failed unexpectedly.", file=sys.stderr); sys.exit(1)
             
        # --- 2. LOAD CONFIGURATION (POST /data/scheduler.association.json?operation=load) ---
        # Retrieve the current state of ALL associations to modify and send back the complete list.
        try:
            print("Loading current configuration...")
            load_url_full = f"{base_url}{URL_LOAD_CONFIG}"

            headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Host": f"{host}",
            "Origin": f"{base_url}",
            "Referer": f"{base_url}/",
            "X-Requested-With": "XMLHttpRequest"
            }

            response_load = s.post(load_url_full, headers=headers, timeout=TIMEOUT_SEC, verify=False)
            response_load.raise_for_status() # Check for HTTP errors
            config_data = response_load.json()
            
            if not config_data.get('success') or not config_data.get('data'):
                print(f"FATAL: Failed to load config. Response: {response_load.text}", file=sys.stderr)
                sys.exit(1)
                
            associations = config_data['data']
            
        except requests.exceptions.RequestException as e:
            print(f"FATAL: Error loading scheduler config: {e}", file=sys.stderr); sys.exit(1)
        
        # --- 3. MODIFY CONFIGURATION ---
        # Find the specific entry and update its 'action' attribute.
        found_target = False
        for entry in associations:
            if entry['ssid'] == target_ssid and entry['band'] == target_band:
                entry['action'] = int(target_action)
                found_target = True
                print(f"Configuration modified for {target_ssid} ({target_band}). New action: {target_action}")
                
        if not found_target:
            print(f"FATAL: Could not find configuration for SSID '{target_ssid}' on band '{target_band}'.", file=sys.stderr)
            sys.exit(1)

        # --- 4. FORMAT PAYLOAD (Reconstructing the column-style URL string) ---
        
        # Initialize lists to hold the values for concatenation
        ssid_list = []
        band_list = []
        ml_list = []
        profileName_list = []
        profileId_list = []
        action_list = []
        
        for entry in associations:
            ssid_list.append(entry['ssid'])
            band_list.append(entry['band'])
            ml_list.append(str(entry['ml']))
            profileName_list.append(entry['profileName'])
            action_list.append(str(entry['action'])) # The modified action value is now a string '0' or '1'
        
        # Concatenate lists into the required URL format using %0A as the separator
        separator = "\n"
        
        final_payload_params = {
            'operation': "save", 
            'ssid': separator.join(ssid_list),
            'band': separator.join(band_list),
            'ml': separator.join(ml_list),
            'profile': separator.join(profileName_list),
            'action': separator.join(action_list),
        }
        
        # Use requests.Request to build the full URL with correct encoding for the query string
        save_url_full = f"{base_url}{URL_SAVE_CONFIG}" + urlencode(final_payload_params, quote_via=quote)

        headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Host": f"{host}",
        "Origin": f"{base_url}",
        "Referer": f"{base_url}/",
        "X-Requested-With": "XMLHttpRequest"
        }

        # --- 5. SAVE CONFIGURATION (POST /data/scheduler.association.json?operation=save) ---
        try:
            print("Sending modified configuration to the AP...")
            
            # Execute the POST request using the fully constructed URL
            response_save = s.post(save_url_full, timeout=TIMEOUT_SEC, headers=headers, verify=False)
            response_save.raise_for_status()
            save_response_json = response_save.json()
            
            # Verification based on the expected JSON response
            if save_response_json.get('success'):
                print(f"SUCCESS: Wi-Fi '{target_ssid}' ({target_band}) set to {state.upper()} successfully.")
            else:
                print(f"ERROR: Wi-Fi command failed. Response: {response_save.text}", file=sys.stderr); sys.exit(1)

        except requests.exceptions.RequestException as e:
            print(f"FATAL: Error during POST Save Command: {e}", file=sys.stderr); sys.exit(1)
        
        # --- 6. LOGOUT (Optional but recommended) ---
        try:
            response =s.get(f"{base_url}{URL_LOGOUT}", timeout=TIMEOUT_SEC, verify=False)
            response.raise_for_status() 
            print("Logout success !")
        except requests.exceptions.RequestException as e:
            print(f"Failed logout: {e}")
            # Ignore logout failure
            pass

if __name__ == "__main__":
    if len(sys.argv) != 7:
        print("Usage: python ap_wifi_control.py [HOST] [USER] [PASS_HASH] [SSID] [BAND] [STATE (on/off)]", file=sys.stderr)
        sys.exit(1)

    # Argument validation and assignment
    host = sys.argv[1]
    user = sys.argv[2]
    pass_hash = sys.argv[3]
    target_ssid = sys.argv[4]
    target_band = sys.argv[5]
    state = sys.argv[6]
   
    control_wifi(host, user, pass_hash, target_ssid, target_band, state)
