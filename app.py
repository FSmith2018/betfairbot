import subprocess
import sys
import importlib.util
import os
import json
import datetime
from datetime import timedelta, timezone

# --- PART 1: AUTO-INSTALLER ---
def check_and_install_requirements(requirements_file="requirements.txt"):
    if not os.path.exists(requirements_file): return
    # (Assuming dependencies are installed now for brevity)

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

    # 3. Logins
    print("🔐 Logging in...")
    try:
        trading.login_interactive()
        trading.race_card.login()
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return

    # 4. Define Time Range (Next 24 Hours)
    now = datetime.datetime.now(timezone.utc)
    end_time = now + timedelta(hours=24)
    
    time_range = filters.time_range(
        from_=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        to=end_time.strftime("%Y-%m-%dT%H:%M:%SZ") 
    )

    print(f"📅 Scanning for races between {now.strftime('%H:%M')} and {end_time.strftime('%H:%M')}...")

    # 5. Find Markets
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
        market_projection=['EVENT', 'MARKET_START_TIME', 'RUNNER_DESCRIPTION']
    )

    if not market_catalogues:
        print("❌ No upcoming races found.")
        return

    # Truth Source for IDs
    valid_markets = {m.market_id: m for m in market_catalogues}
    market_ids = list(valid_markets.keys())
    
    print(f"✅ Found {len(market_ids)} races. Fetching Deep Order Books...\n")

    # 6. Fetch DATA
    try:
        # A. Get Static Data (Form)
        race_cards = trading.race_card.get_race_card(market_ids=market_ids)
        
        # B. Get Live Price Data WITH DEPTH AND TRADED VOLUME
        # FIX: Added 'EX_TRADED' to ensure runner.total_matched is populated
        price_filter = filters.price_projection(
            price_data=['EX_BEST_OFFERS', 'EX_TRADED'], 
            ex_best_offers_overrides={'bestPricesDepth': 3} 
        )
        market_books = trading.betting.list_market_book(
            market_ids=market_ids,
            price_projection=price_filter
        )
    except Exception as e:
        print(f"⚠️ Error fetching data: {e}")
        return

    # 7. Create Deep Lookup
    price_map = {}
    for book in market_books:
        m_id = str(book.market_id)
        # Store Market Total Matched
        price_map[m_id] = {
            'market_total': book.total_matched,
            'runners': {}
        }
        
        for runner in book.runners:
            s_id = str(runner.selection_id)
            
            # Capture Top 3 Back Prices and Volumes
            back_depth = []
            if runner.ex.available_to_back:
                for price_point in runner.ex.available_to_back:
                    back_depth.append(f"{price_point.price} (£{int(price_point.size)})")
            
            # Capture Top 3 Lay Prices and Volumes
            lay_depth = []
            if runner.ex.available_to_lay:
                for price_point in runner.ex.available_to_lay:
                    lay_depth.append(f"{price_point.price} (£{int(price_point.size)})")

            # Store in map
            price_map[m_id]['runners'][s_id] = {
                'total_matched': runner.total_matched, # This will now be populated!
                'back': back_depth,
                'lay': lay_depth
            }

    # 8. Display Combined Data
    for i, card in enumerate(race_cards):
        if i >= len(market_ids): break 
        
        m_id = market_ids[i]
        race = card.race
        
        # Get Market Total Matched
        market_total = 0.0
        if m_id in price_map:
            market_total = price_map[m_id]['market_total']

        print(f"🏆 {race.start_date} | {race.course.name} - {race.race_title}")
        print(f"   (Market ID: {m_id}) | 💰 Market Volume: £{market_total:,.0f}")
        
        print(f"   {'Runner Name':<20} | {'Matched':<9} | {'Back Queue (Price/Vol)':<30} | {'Lay Queue (Price/Vol)':<30}")
        print("-" * 100)

        for runner in card.runners:
            name = runner.name
            
            # Link via Selection ID
            s_id = "Unknown"
            if runner.selections:
                s_id = str(runner.selections[0].selection_id)

            # Get Data
            runner_matched = "£0"
            back_str = "-"
            lay_str = "-"
            
            if m_id in price_map and s_id in price_map[m_id]['runners']:
                data = price_map[m_id]['runners'][s_id]
                
                # Format Matched (Using 0 if None)
                val = data['total_matched'] if data['total_matched'] else 0
                runner_matched = f"£{int(val)}"
                
                # Format Back Depth
                if data['back']:
                    back_str = " | ".join(data['back'][:2]) 
                
                # Format Lay Depth
                if data['lay']:
                    lay_str = " | ".join(data['lay'][:2])

            print(f"   {name:<20} | {runner_matched:<9} | {back_str:<30} | {lay_str:<30}")
        
        print("\n" + "="*100 + "\n")

if __name__ == "__main__":
    main()
    