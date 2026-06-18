"""
Migration script: slot_item_thresholds -> threshold_groups + threshold_group_items

Migrates existing single-item thresholds into the new threshold group system.
Each old threshold becomes a group with one item, named after the item.

Usage: python migrate_threshold_groups.py
Run from the backend/ directory.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.models import Base
from app import engine, Session


def migrate():
    session = Session()
    try:
        # 1. Create new tables if they don't exist
        print("[MIGRATE] Creating new tables (threshold_groups, threshold_group_items)...")
        Base.metadata.create_all(engine, tables=[
            Base.metadata.tables.get('threshold_groups'),
            Base.metadata.tables.get('threshold_group_items'),
        ])
        print("[MIGRATE] Tables created.")

        # 2. Check if old table exists
        try:
            old_rows = session.execute(text("SELECT id, user_tracked_slot_id, item_name, threshold FROM slot_item_thresholds")).fetchall()
        except Exception:
            print("[MIGRATE] Old table 'slot_item_thresholds' not found. Nothing to migrate.")
            return

        if not old_rows:
            print("[MIGRATE] No existing thresholds to migrate.")
        else:
            print(f"[MIGRATE] Migrating {len(old_rows)} existing threshold(s)...")
            
            # Group old thresholds by (user_tracked_slot_id, item_name) since
            # the old system allowed multiple thresholds for the same item (e.g., notify at 1 AND at 3).
            # Each unique (slot, item, threshold) becomes its own group with one item.
            for old_id, slot_db_id, item_name, threshold_count in old_rows:
                # Create a group named after the item
                group_name = item_name.strip()
                
                session.execute(text(
                    "INSERT INTO threshold_groups (user_tracked_slot_id, name, is_triggered) VALUES (:slot_id, :name, 0)"
                ), {"slot_id": slot_db_id, "name": group_name})
                
                # Get the ID of the group we just inserted
                group_id = session.execute(text("SELECT last_insert_rowid()")).scalar()
                
                session.execute(text(
                    "INSERT INTO threshold_group_items (group_id, item_name, quantity, is_group) VALUES (:gid, :item, :qty, 0)"
                ), {"gid": group_id, "item": item_name.strip(), "qty": threshold_count})
            
            session.commit()
            print(f"[MIGRATE] Successfully migrated {len(old_rows)} threshold(s) into groups.")

        # 3. Drop old table
        print("[MIGRATE] Dropping old 'slot_item_thresholds' table...")
        session.execute(text("DROP TABLE IF EXISTS slot_item_thresholds"))
        session.commit()
        print("[MIGRATE] Old table dropped.")

        print("[MIGRATE] Migration complete!")
        
    except Exception as e:
        session.rollback()
        print(f"[MIGRATE] ERROR: {e}")
        raise
    finally:
        Session.remove()


if __name__ == "__main__":
    migrate()
