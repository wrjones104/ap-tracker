import json
import sys
import os
import time
import argparse

# Ensure we can import from the backend/app package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app import Session
    from app.models import TrackedRoom, DatapackageCache
except ImportError as e:
    print("Error: Could not import app modules. Please run this script from the backend directory.")
    print(f"Details: {e}")
    sys.exit(1)

def heal_all_datapackages(limit, delay):
    print("=" * 80)
    print("             AP Tracker - Datapackage Cache Bulk Healing Tool")
    print("=" * 80)
    
    session = Session()
    try:
        # Get all unique games that are currently cached
        games = session.query(DatapackageCache.game).distinct().all()
        game_names = [g[0] for g in games if g[0]]
        
        if not game_names:
            print("No cached games found in the DatapackageCache.")
            return

        print(f"Found {len(game_names)} cached game(s). Checking for outdated structures...")
        
        outdated_games = []
        for game_name in game_names:
            # Check if this game is cached using the old completion marker '_completed'
            # (which means it doesn't have the updated groups structure)
            has_old = session.query(DatapackageCache.id).filter_by(
                game=game_name,
                entity_type='_metadata',
                entity_name='_completed'
            ).limit(1).scalar() is not None
            
            if has_old:
                outdated_games.append(game_name)
            else:
                # Also check if it has groups but lacks group members
                has_groups = session.query(DatapackageCache.id).filter_by(
                    game=game_name, 
                    entity_type='item_group'
                ).limit(1).scalar() is not None
                
                if has_groups:
                    has_members = session.query(DatapackageCache.id).filter_by(
                        game=game_name, 
                        entity_type='item_group_member'
                    ).limit(1).scalar() is not None
                    
                    if not has_members:
                        outdated_games.append(game_name)

        if not outdated_games:
            print("\nNo action required. All game caches are up to date.")
            return

        print(f"\nFound {len(outdated_games)} game(s) with outdated cache schemas.")
        
        # Apply limit if specified
        if limit and len(outdated_games) > limit:
            print(f"Limiting this run to the first {limit} game(s) as requested.")
            outdated_games = outdated_games[:limit]

        healed_count = 0
        had_room_failures = False
        
        for idx, game_name in enumerate(outdated_games):
            if idx > 0 and delay > 0:
                print(f"Staggering... sleeping for {delay} seconds before next game.")
                time.sleep(delay)

            print(f"\n[{idx+1}/{len(outdated_games)}] Healing game '{game_name}'...")
            
            # Fetch checksums to delete
            checksums = [
                c[0] for c in session.query(DatapackageCache.checksum).filter_by(game=game_name).distinct().all()
            ]
            
            if checksums:
                # Delete entries
                deleted_rows = session.query(DatapackageCache).filter(
                    DatapackageCache.checksum.in_(checksums)
                ).delete(synchronize_session=False)
                print(f"  - Deleted {deleted_rows} cache entries for checksums: {', '.join(checksums)}")
                
                # Reset is_setup on rooms using these checksums
                rooms = session.query(TrackedRoom.id, TrackedRoom.game_checksums_json).all()
                reset_room_ids = []
                for r_id, game_checksums_json in rooms:
                    try:
                        r_checksums = json.loads(game_checksums_json or '{}').values()
                        if any(c in checksums for c in r_checksums):
                            reset_room_ids.append(r_id)
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        print(f"  - Error: Failed to parse game_checksums_json for room ID {r_id}: {e}")
                        had_room_failures = True
                        reset_room_ids.append(r_id)
                
                rooms_to_reset = 0
                if reset_room_ids:
                    session.query(TrackedRoom).filter(TrackedRoom.id.in_(reset_room_ids)).update(
                        {TrackedRoom.is_setup: False}, synchronize_session=False
                    )
                    rooms_to_reset = len(reset_room_ids)
                
                if rooms_to_reset > 0:
                    print(f"  - Reset 'is_setup' to False for {rooms_to_reset} room(s) to trigger auto-rebuild.")
                
                session.commit()
                healed_count += 1
        
        print("\n" + "=" * 80)
        if healed_count > 0 and not had_room_failures:
            print(f"SUCCESS: Healed {healed_count} game cache(s) successfully.")
            print("The background poller service will automatically rebuild the cache for these games on its next poll tick.")
            if len(outdated_games) == limit:
                print("\nNOTE: There are still outdated games remaining. Run this script again to heal the next batch.")
        else:
            if had_room_failures:
                print("FAILURE: Some room checksums could not be read. Overall success was not achieved.")
            else:
                print("No action taken.")
        print("=" * 80)
        
    except Exception as e:
        session.rollback()
        print(f"\nAn error occurred during healing: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bulk heal outdated datapackages.")
    parser.add_argument(
        "--limit", "-l", 
        type=int, 
        default=None, 
        help="Maximum number of games to heal in this run (use to control database/network spikes)."
    )
    parser.add_argument(
        "--delay", "-d", 
        type=float, 
        default=2.0, 
        help="Delay in seconds between healing distinct games (default: 2.0s)."
    )
    args = parser.parse_args()
    heal_all_datapackages(args.limit, args.delay)
