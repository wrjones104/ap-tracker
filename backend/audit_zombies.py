import os
import json
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Load environment variables
load_dotenv()
database_url = os.environ.get('DATABASE_URL')

if not database_url:
    print("Error: DATABASE_URL not found in environment.")
    exit(1)

# Set up SQLAlchemy
engine = create_engine(database_url)
Session = sessionmaker(bind=engine)
session = Session()

def run_audit():
    print("--- Starting AP Tracker Room Audit ---")
    
    # Fetch all rooms currently marked as setup
    query = text("""
        SELECT id, room_id, cached_players_json, game_checksums_json 
        FROM tracked_room 
        WHERE is_setup = true AND is_complete = false
    """)
    
    rooms = session.execute(query).fetchall()
    affected_rooms = []

    for room in rooms:
        room_db_id = room[0]
        room_uuid = room[1]
        players_json_str = room[2]
        checksums_json_str = room[3]

        if not players_json_str or not checksums_json_str:
            continue

        try:
            players_data = json.loads(players_json_str)
            checksums_data = json.loads(checksums_json_str)
            
            # Extract games from HTTP player cache
            expected_games = set(p.get('game') for p in players_data if p.get('game'))
            # Extract games from the stored checksums
            stored_checksum_games = set(checksums_data.keys())

            # If there's a mismatch, flag it
            if expected_games != stored_checksum_games:
                affected_rooms.append({
                    'id': room_db_id,
                    'uuid': room_uuid,
                    'expected': expected_games,
                    'stored': stored_checksum_games
                })
        except json.JSONDecodeError:
            print(f"Warning: Could not parse JSON for Room DB ID {room_db_id}")

    # Report findings
    if not affected_rooms:
        print("Audit Complete: No mismatched rooms found! Your data is clean.")
        return

    print(f"\n[!] Found {len(affected_rooms)} room(s) with mismatched checksums:\n")
    for r in affected_rooms:
        print(f"Room DB ID: {r['id']} (UUID: {r['uuid']})")
        print(f"  -> Expected Games : {r['expected']}")
        print(f"  -> Stored Games   : {r['stored']}")
        print("-" * 40)

    # Prompt for repair
    confirm = input(f"Do you want to flag these {len(affected_rooms)} rooms for re-setup? (y/n): ").strip().lower()
    
    if confirm == 'y':
        ids_to_fix = [r['id'] for r in affected_rooms]
        # Using parameterized query for security against SQL injection
        update_query = text("UPDATE tracked_room SET is_setup = false WHERE id = ANY(:ids)")
        session.execute(update_query, {'ids': ids_to_fix})
        session.commit()
        print(f"Success: {len(affected_rooms)} rooms have been queued for re-setup by the poller.")
    else:
        print("Aborted. No changes were made to the database.")

if __name__ == "__main__":
    try:
        run_audit()
    finally:
        session.close()