import betfairlightweight
from betfairlightweight import filters
import pandas as pd
import numpy as np
import os
import datetime
import json

# --- CONFIGURATION ---
# Update this path to your actual credentials file location
credentials_json_path = r"credentials.json"

def main():
    # 1. Load Credentials
    try:
        with open(credentials_json_path) as f:
            cred = json.load(f)
            my_username = cred['username']
            my_password = cred['password']
            my_app_key = cred['app_key']
    except FileNotFoundError:
        print(f"Error: Could not find credentials file at {credentials_json_path}")
        return

    # 2. Initialize Client and Login
    trading = betfairlightweight.APIClient(
        username=my_username,
        password=my_password,
        app_key=my_app_key
    )
    
    print("Logging in...")
    trading.login_interactive()

    # 3. List Event Types (Sports)
    event_types = trading.betting.list_event_types()
    sport_ids = pd.DataFrame({
        'Sport': [e.event_type.name for e in event_types],
        'ID': [e.event_type.id for e in event_types]
    }).set_index('Sport').sort_index()
    
    print("\nAvailable Sports:")
    print(sport_ids)

    # 4. Search Live Soccer Matches
    print("\n📡 Searching for live soccer matches...")
    live_event_filter = filters.market_filter(in_play_only=True, event_type_ids=['1'])
    live_events = trading.betting.list_events(filter=live_event_filter)

    if live_events:
        live_matches_data = []
        for event_result in live_events:
            event = event_result.event
            live_matches_data.append({
                "Event ID": event.id,
                "Event Name": event.name,
                "Country": event.country_code,
                "Start Time (UTC)": event.open_date.strftime("%Y-%m-%d %H:%M:%S")
            })
        print(f"✅ Found {len(live_matches_data)} live matches.")
        print(pd.DataFrame(live_matches_data))
    else:
        print("❌ No live soccer matches found.")

    # 5. Fetch Upcoming Odds
    print("\n📡 Finding upcoming soccer match odds...")
    soccer_market_filter = filters.market_filter(
        event_type_ids=['1'], 
        market_type_codes=['MATCH_ODDS']
    )

    market_catalogues = trading.betting.list_market_catalogue(
        filter=soccer_market_filter,
        market_projection=['EVENT', 'MARKET_START_TIME', 'RUNNER_DESCRIPTION'],
        max_results='15',
        sort='FIRST_TO_START'
    )

    if market_catalogues:
        market_ids = [m.market_id for m in market_catalogues]
        market_books = trading.betting.list_market_book(
            market_ids=market_ids,
            price_projection=filters.price_projection(price_data=['EX_BEST_OFFERS'])
        )
        
        # Process and print odds (simplified for console display)
        for cat in market_catalogues:
            print(f"Match: {cat.event.name} | Start: {cat.market_start_time}")

if __name__ == "__main__":
    main()