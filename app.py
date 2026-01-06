import subprocess
import sys
import importlib.util
import os
import json
import datetime
import time
from datetime import timedelta, timezone

# --- PART 1: AUTO-INSTALLER ---
def check_and_install_requirements(requirements_file="requirements.txt"):
    if not os.path.exists(requirements_file): 
        with open(requirements_file, "w") as f:
            f.write("betfairlightweight\nflumine\npandas\nnumpy\nrequests")
        return

    lines = []
    for encoding in ['utf-8', 'utf-16', 'utf-16-le', 'cp1252']:
        try:
            with open(requirements_file, "r", encoding=encoding) as f:
                content = f.read()
                if '\x00' not in content: 
                    lines = content.splitlines()
                    break
        except UnicodeError:
            continue

    if not lines: return
    
    requirements = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    missing = []
    for req in requirements:
        clean_req = req.replace('\x00', '').replace('\ufeff', '')
        if not clean_req: continue
        pkg_name = clean_req.split("==")[0].split(">=")[0].split("<=")[0].lower()
        if importlib.util.find_spec(pkg_name) is None: missing.append(clean_req)

    if missing:
        print(f"⚙️  Installing missing packages: {', '.join(missing)}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        except subprocess.CalledProcessError:
            sys.exit(1)

check_and_install_requirements()

# --- PART 2: IMPORTS ---
import betfairlightweight
from betfairlightweight import filters
from betfairlightweight.exceptions import APIError

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
    trading = betfairlightweight.APIClient(username=username, password=password, app_key=app_key)

    # 3. Logins
    print("🔐 Logging in...")
    try:
        trading.login_interactive()
        trading.race_card.login()
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return

    # 4. Define Time Range (Next 3 Days)
    now = datetime.datetime.now(timezone.utc)
    end_time = now + timedelta(days=3)
    time_range = filters.time_range(from_=now.strftime("%Y-%m-%dT%H:%M:%SZ"), to=end_time.strftime("%Y-%m-%dT%H:%M:%SZ"))

    print(f"📅 Scanning for races (Next 3 Days)...")

    # 5. Find Markets (Source of Truth for Names)
    market_filter = filters.market_filter(
        event_type_ids=['7'], market_countries=['GB', 'IE'], 
        market_type_codes=['WIN'], market_start_time=time_range
    )

    market_catalogues = trading.betting.list_market_catalogue(
        filter=market_filter, max_results='30', sort='FIRST_TO_START',
        market_projection=['EVENT', 'MARKET_START_TIME', 'RUNNER_DESCRIPTION']
    )

    if not market_catalogues:
        print("❌ No upcoming races found.")
        return

    # Create a Master Map: Market ID -> Catalogue Data
    catalogue_map = {m.market_id: m for m in market_catalogues}
    market_ids = list(catalogue_map.keys())
    print(f"✅ Found {len(market_ids)} races. Fetching Data...")

    # 6. Fetch DATA (Adaptive Mode)
    race_cards = []
    market_books = []

    # A. Fetch Race Cards (Optional - fail silently if needed)
    print(f"\n📡 Fetching Race Cards...")
    for i in range(0, len(market_ids), 5):
        chunk = market_ids[i:i+5]
        try:
            batch = trading.race_card.get_race_card(market_ids=chunk)
            if batch: race_cards.extend(batch)
        except Exception: pass

    # B. Fetch Prices (Adaptive Detail Level)
    print(f"\n📡 Fetching Market Books (Adaptive Mode)...")
    
    # Levels of Detail
    filter_high = filters.price_projection(price_data=['EX_BEST_OFFERS', 'EX_TRADED'], ex_best_offers_overrides={'bestPricesDepth': 3})
    filter_med  = filters.price_projection(price_data=['EX_BEST_OFFERS', 'EX_TRADED'], ex_best_offers_overrides={'bestPricesDepth': 1})
    filter_low  = filters.price_projection(price_data=['EX_BEST_OFFERS'], ex_best_offers_overrides={'bestPricesDepth': 1})

    for i, m_id in enumerate(market_ids):
        print(f"   > Processing {i+1}/{len(market_ids)}...", end="\r")
        success = False
        
        # Attempt 1: High Detail
        try:
            book = trading.betting.list_market_book(market_ids=[m_id], price_projection=filter_high)
            if book:
                market_books.extend(book)
                success = True
        except APIError: pass

        # Attempt 2: Medium Detail
        if not success:
            try:
                book = trading.betting.list_market_book(market_ids=[m_id], price_projection=filter_med)
                if book:
                    market_books.extend(book)
                    success = True
            except APIError: pass

        # Attempt 3: Low Detail
        if not success:
            try:
                book = trading.betting.list_market_book(market_ids=[m_id], price_projection=filter_low)
                if book:
                    market_books.extend(book)
                    success = True
            except Exception: pass
        
        time.sleep(0.1) # Brief pause

    print(f"\n   ✅ Fetched {len(market_books)} Market Books total.\n")

    # 7. Process & Display
    # Map Prices
    price_map = {}
    for book in market_books:
        m_id = str(book.market_id)
        back_overround = 0.0
        lay_overround = 0.0
        
        for runner in book.runners:
            if runner.ex.available_to_back: back_overround += (1 / runner.ex.available_to_back[0].price) * 100
            if runner.ex.available_to_lay: lay_overround += (1 / runner.ex.available_to_lay[0].price) * 100

        price_map[m_id] = {
            'market_total': book.total_matched,
            'back_overround': back_overround,
            'lay_overround': lay_overround,
            'runners': {}
        }
        
        for runner in book.runners:
            s_id = str(runner.selection_id)
            best_back = runner.ex.available_to_back[0].price if runner.ex.available_to_back else 0.0
            best_lay = runner.ex.available_to_lay[0].price if runner.ex.available_to_lay else 0.0
            
            back_depth = [f"{p.price}" for p in runner.ex.available_to_back][:3]
            lay_depth = [f"{p.price}" for p in runner.ex.available_to_lay][:3]

            price_map[m_id]['runners'][s_id] = {
                'total_matched': runner.total_matched,
                'back': back_depth,
                'lay': lay_depth,
                'best_back': best_back,
                'best_lay': best_lay
            }

    # Map Race Cards (Optional)
    card_map = {card.race.race_id_exchange: card for card in race_cards if hasattr(card.race, 'race_id_exchange')}

    # --- DISPLAY LOOP (Using Catalogue as Base) ---
    for m_id in market_ids:
        # Use Catalogue for basic info (Guaranteed to exist)
        cat = catalogue_map[m_id]
        race_name = cat.event.name
        start_time = cat.market_start_time
        
        # Try to enrich with Race Card data if available
        course_name = "Unknown"
        if m_id in card_map:
            course_name = card_map[m_id].race.course.name

        # Get Price Data
        market_total = 0.0
        back_or = 0.0
        lay_or = 0.0
        if m_id in price_map:
            market_total = price_map[m_id]['market_total']
            back_or = price_map[m_id]['back_overround']
            lay_or = price_map[m_id]['lay_overround']

        back_or_str = f"{back_or:.1f}%"
        if back_or < 100: back_or_str = f"🚨 {back_or:.1f}%"

        print(f"🏆 {start_time} | {course_name} - {race_name}")
        print(f"   Vol: £{market_total:,.0f} | Back OR: {back_or_str} | Lay OR: {lay_or:.1f}%")
        print("-" * 100)

        # Loop through runners from the CATALOGUE (Guaranteed names)
        for runner in cat.runners:
            name = runner.runner_name
            s_id = str(runner.selection_id)

            matched = "£0"
            back_str = "-"
            lay_str = "-"
            arb_flag = ""
            
            if m_id in price_map and s_id in price_map[m_id]['runners']:
                data = price_map[m_id]['runners'][s_id]
                val = data['total_matched'] if data['total_matched'] else 0
                matched = f"£{int(val)}"
                
                if data['back']: back_str = " | ".join(data['back']) 
                if data['lay']: lay_str = " | ".join(data['lay'])
                
                bb = data['best_back']
                bl = data['best_lay']
                if bb > 0 and bl > 0 and bb > bl:
                    arb_flag = f"✅ {bb-bl:.2f} pts"

            print(f"   {name:<20} | {matched:<9} | {back_str:<25} | {lay_str:<25} | {arb_flag}")
        print("\n" + "="*100 + "\n")

if __name__ == "__main__":
    main()