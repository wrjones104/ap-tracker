import asyncio
import logging
import sys
import sqlite3
from app import create_app
from app.poller import run_room_poll

# Set up logging to stdout
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
    stream=sys.stdout
)

async def test_poll():
    app = create_app()
    # Construct room_info dictionary
    room_info = {
        'db_id': 3,
        'hostname': 'archipelago.gg',
        'room_uuid': 'Y5DBdR_6Qq-VkwsnNwpgiA',
        'cheese_tracker_id': None,
        'cheese_updated_at': None
    }
    loop = asyncio.get_event_loop()
    print("Starting manual run_room_poll with increased timeout...")
    await run_room_poll(room_info, loop)
    print("Done run_room_poll.")

    # Check database counts
    db_path = r"c:\Projects\ap-tracker\backend\ap_tracker.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM notified_items WHERE room_id = 'Y5DBdR_6Qq-VkwsnNwpgiA'")
    count = cursor.fetchone()[0]
    print(f"Number of notified items in DB for Room 3: {count}")
    
    cursor.execute("SELECT needs_backfill FROM user_tracked_slots WHERE room_id = 3 AND slot_id = 2908")
    needs_backfill = cursor.fetchone()[0]
    print(f"Needs backfill status for slot 2908: {needs_backfill}")
    
    conn.close()

if __name__ == "__main__":
    asyncio.run(test_poll())
