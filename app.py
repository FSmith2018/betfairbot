import subprocess
import sys
import importlib.util
import os
import json
import logging
import datetime
from datetime import timedelta, timezone

# --- PART 1: AUTO-INSTALLER ---
def check_and_install_requirements(requirements_file="requirements.txt"):
    if not os.path.exists(requirements_file):
        print(f"⚠️  Warning: {requirements_file} not found. Skipping auto-install.")
        return

    print("⚙️  Checking dependencies...")
    lines = []
    # Handle various encodings (UTF-8, UTF-16, etc.)
    for encoding in ['utf-8', 'utf-16', 'utf-16-le', 'cp1252']:
        try:
            with open(requirements_file, "r", encoding=encoding) as f:
                content = f.read()
                if '\x00' not in content: 
                    lines = content.splitlines()
                    break
        except UnicodeError:
            continue

    if not lines:
        print(f"❌ Error: Could not read {requirements_file}. Please save it as UTF-8.")
        return

    requirements = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    missing = []
    
    for req in requirements:
        clean_req = req.replace('\x00', '').replace('\ufeff', '')
        if not clean_req: continue
        
        pkg_name = clean_req.split("==")[0].split(">=")[0].split("<=")[0].lower()
        if importlib.util.find_spec(pkg_name) is None:
            missing.append(clean_req)

    if missing:
        print(f"🛠️  Installing missing packages: {', '.join(missing)}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print("✅ Installation complete.\n")
        except subprocess.CalledProcessError as e:
            print(f"❌ Error installing packages: {e}")
            sys.exit(1)
    else:
        print("✅ All dependencies are installed.\n")

check_and_install_requirements()

# --- PART 2: IMPORTS ---
import betfairlightweight
from betfairlightweight import filters

# --- CONFIGURATION ---
CREDENTIALS_PATH = r"credentials.json"

# --- PART 3: MAIN SCRIPT ---
def main():
    # 1. Load Credentials
    try:
        with open(CREDENTIALS_PATH) as f:
            cred = json.load(f)
            username = cred['username']
            password = cred['password']
            app_key = cred['app_key']
    except FileNotFoundError:
        print(f"❌ Error: Could not find credentials file at {CREDENTIALS_PATH}")
        return

    # 2. Initialize Client
    trading = betfairlightweight.APIClient(
        username=username,
        password=password,
        app_key=app_key
    )

    # 3. Perform Main Login
    print("🔐 Logging in to Betfair Main API...")
    try:
        trading.login_interactive()
    except Exception as e:
        print(f"❌ Main Login failed: {e}")
        return

    # 4. Perform Race Card Service Login (THE FIX)
    print("🐎 Logging in to Race Card Service...")
    try:
        trading.race_card.login()
    except Exception as e:
        print(f"❌ Race Card Login failed: {e}")
        print("Note: This service sometimes requires a funded account or specific API permissions.")
        return

    # 5. Define Time Range (Next 7 Days)
    now = datetime.datetime.now(timezone.utc)
    next_week = now + timedelta(days=7)
    
    time_range = filters.time_range(
        from_=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        to=next_week.strftime("%Y-%m-%dT%H:%M:%SZ") 
    )

    print(f"📅 Scanning for Horse Racing between {now.date()} and {next_week.date()}...")

    # 6. Find Markets
    # Event Type 7 is Horse Racing
    market_filter = filters.market_filter(
        event_type_ids=['7'],
        market_countries=['GB', 'IE'], 
        market_type_codes=['WIN'],     
        market_start_time=time_range
    )

    market_catalogues = trading.betting.list_market_catalogue(
        filter=market_filter,
        max_results='5', 
        sort='FIRST_TO_START',
        market_projection=['EVENT', 'MARKET_START_TIME']
    )

    if not market_catalogues:
        print("❌ No upcoming races found.")
        return

    # Extract Market IDs
    market_ids = [m.market_id for m in market_catalogues]
    print(f"✅ Found {len(market_ids)} races. Fetching full Race Card details...\n")

    # 7. Fetch "Race Card" Data
    try:
        race_cards = trading.race_card.get_race_card(
            market_ids=market_ids
        )
    except Exception as e:
        print(f"⚠️ Error fetching Race Cards: {e}")
        return

    # 8. Display Data
    if not race_cards:
        print("⚠️ No Race Card data returned for these markets.")
        return

    for card in race_cards:
        race = card.race
        
        # Safe access to attributes (some might be None)
        course_name = race.course.name if race.course else "Unknown Course"
        race_title = race.race_title if race.race_title else "Unknown Race"
        going = race.going.name if race.going else "Unknown"
        
        print(f"🏆 {race.start_date} | {course_name} - {race_title}")
        print(f"   Distance: {race.distance}m | Going: {going}")
        print(f"   Prize: {card.prize}")
        
        print(f"   {'Runner Name':<20} | {'Jockey':<20} | {'Trainer':<20} | {'Form'}")
        print("-" * 80)
        
        for runner in card.runners:
            name = runner.name
            jockey = runner.jockey.name if runner.jockey else "N/A"
            trainer = runner.trainer.name if runner.trainer else "N/A"
            form = runner.recent_form if runner.recent_form else "-"
            
            print(f"   {name:<20} | {jockey:<20} | {trainer:<20} | {form}")
        
        print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
