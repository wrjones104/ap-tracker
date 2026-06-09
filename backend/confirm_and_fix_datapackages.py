import json
import sys
import os
from sqlalchemy import func

# Ensure we can import from the backend/app package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app import Session, engine
    from app.models import TrackedRoom, DatapackageCache
except ImportError as e:
    print(f"Error: Could not import app modules. Please make sure to run this script from the backend directory.")
    print(f"Details: {e}")
    sys.exit(1)

def print_separator():
    print("=" * 70)

def print_title(text):
    print(f"\n>>> {text} <<<")

def run_diagnostics():
    print_separator()
    print("      Archipelago Alerts - Datapackage Cache Diagnostic & Repair Tool")
    print_separator()

    session = Session()
    try:
        # Check if a room ID was passed as a command line argument
        target_room_id = sys.argv[1] if len(sys.argv) > 1 else None

        if target_room_id:
            room = session.query(TrackedRoom).filter_by(room_id=target_room_id).first()
            if not room:
                print(f"No tracked room found in the database with Room ID: {target_room_id}")
                return
            print(f"Bypassing menu. Found requested Room ID: {target_room_id}")
        else:
            # 1. Fetch all tracked rooms
            rooms = session.query(TrackedRoom).all()
            if not rooms:
                print("No tracked rooms found in the database.")
                return

            print_title("Available Tracked Rooms")
            for idx, r in enumerate(rooms):
                print(f"[{idx}] DB ID: {r.id} | Room ID: {r.room_id} | Host: {r.hostname} | Setup Complete: {r.is_setup}")

            # 2. Select room
            selection = input("\nSelect a room index to inspect (or press Enter to quit): ").strip()
            if not selection:
                print("Exiting.")
                return

            try:
                selected_idx = int(selection)
                if selected_idx < 0 or selected_idx >= len(rooms):
                    print("Invalid index.")
                    return
                room = rooms[selected_idx]
            except ValueError:
                print("Invalid input. Please enter a valid number.")
                return

        print_separator()
        print(f"Analyzing Room ID: {room.room_id}")
        print(f"Hostname: {room.hostname}")
        print(f"Current is_setup flag in DB: {room.is_setup}")
        print_separator()

        # 3. Parse game checksums
        try:
            checksums = json.loads(room.game_checksums_json or '{}')
        except Exception as e:
            print(f"Error parsing game_checksums_json: {e}")
            checksums = {}

        if not checksums:
            print("No game checksums found for this room. Has it completed its first poll setup?")
            return

        print_title("Game Checksums & Cache Integrity Analysis")
        
        # We will collect data to see if we should recommend a repair
        needs_repair = False
        checksums_to_purge = []

        for game, checksum in checksums.items():
            print(f"\nGame: {game}")
            print(f"Checksum: {checksum}")

            # Query entry counts grouped by entity_type
            counts = session.query(
                DatapackageCache.entity_type, 
                func.count(DatapackageCache.id)
            ).filter(
                DatapackageCache.checksum == checksum
            ).group_by(
                DatapackageCache.entity_type
            ).all()

            counts_dict = {etype: count for etype, count in counts}

            # Check for metadata entries (like completed or empty package)
            metadata_entries = session.query(
                DatapackageCache.entity_name
            ).filter(
                DatapackageCache.checksum == checksum,
                DatapackageCache.entity_type == '_metadata'
            ).all()
            metadata_names = [m[0] for m in metadata_entries]

            total_entries = sum(counts_dict.values())
            print(f" -> Total Cache Rows: {total_entries}")
            
            if counts_dict:
                for etype, count in counts_dict.items():
                    print(f"    - {etype}: {count} rows")
            else:
                print("    - (No cache rows found for this checksum!)")

            # Diagnostic logic
            has_marker = '_completed_v2' in metadata_names or '_empty_datapackage' in metadata_names
            is_empty_marker = '_empty_datapackage' in metadata_names
            
            if total_entries == 0:
                print("Verdict: [MISSING] - UNCACHED / MISSING DATAPACKAGE")
                needs_repair = True
                checksums_to_purge.append(checksum)
            elif not has_marker:
                print("Verdict: [WARNING] - INCOMPLETE / CORRUPTED CACHE (Missing completion marker!)")
                needs_repair = True
                checksums_to_purge.append(checksum)
            else:
                if is_empty_marker:
                    print("Verdict: [OK] - Valid empty datapackage")
                else:
                    print("Verdict: [OK] - Fully cached and verified")

        # 4. Prompt for repair
        print_separator()
        if needs_repair:
            print("\nWARNING: One or more game datapackages for this room are missing or corrupted.")
            print("This causes items and locations to render as raw IDs in the UI/history.")
            
            confirm = input("\nWould you like to repair this room's cache? (y/n): ").strip().lower()
            if confirm == 'y':
                print("\nStarting repair...")
                
                # Delete corrupted cache rows
                if checksums_to_purge:
                    deleted_rows = session.query(DatapackageCache).filter(
                        DatapackageCache.checksum.in_(checksums_to_purge)
                    ).delete(synchronize_session=False)
                    print(f"- Deleted {deleted_rows} corrupted cache entries.")
                
                # Reset is_setup to false so the background poller does a clean setup run
                room.is_setup = False
                session.commit()
                print("- Reset 'is_setup' flag to False on the room.")
                print("\nSUCCESS! Cache repaired successfully.")
                print("The background poller service will automatically rebuild the cache on its next poll tick.")
            else:
                print("Repair cancelled.")
        else:
            print("\nAll game datapackages for this room are valid and fully cached.")
            force_confirm = input("Would you like to FORCE rebuild the cache for this room anyway? (y/n): ").strip().lower()
            if force_confirm == 'y':
                print("\nStarting force rebuild...")
                all_checksums = list(checksums.values())
                deleted_rows = session.query(DatapackageCache).filter(
                    DatapackageCache.checksum.in_(all_checksums)
                ).delete(synchronize_session=False)
                room.is_setup = False
                session.commit()
                print(f"- Deleted {deleted_rows} cache entries.")
                print("- Reset 'is_setup' flag to False on the room.")
                print("\nSUCCESS! Rebuild triggered. The poller will rebuild the cache on next run.")
            else:
                print("No changes made.")

    except Exception as e:
        session.rollback()
        print(f"\nAn error occurred during diagnostics: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    run_diagnostics()