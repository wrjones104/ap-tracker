import os
import sys
import unittest
import json
from datetime import datetime, timezone

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_reconcile.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import Base, NotifiedItem, SlotItemCount, ThresholdGroup, ThresholdGroupItem, UserTrackedSlot, TrackedRoom, DatapackageCache, User, UserRoomSubscription


class TestThresholdReconciliation(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        # Start from a clean schema so a leftover DB file from an interrupted
        # prior run can't collide (e.g. UNIQUE constraint on tracked_rooms.room_id).
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.session = Session()

    def tearDown(self):
        self.session.close()
        Session.remove()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def test_reconcile_slot_item_counts_and_reset_triggered(self):
        room_uuid = "test-room-uuid-123"
        room = TrackedRoom(
            room_id=room_uuid,
            tracker_id="test_tracker",
            hostname="archipelago.gg",
            game_checksums_json=json.dumps({"Zelda": "checksum123"}),
            cached_players_json=json.dumps([{"slot_id": 1, "name": "Player1", "game": "Zelda"}])
        )
        self.session.add(room)
        self.session.flush()

        user = User(discord_id="12345", discord_username="testuser")
        self.session.add(user)
        self.session.flush()

        sub = UserRoomSubscription(user_id=user.id, room_id=room.id, alias="Test Room")
        self.session.add(sub)
        self.session.flush()

        slot = UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=1)
        self.session.add(slot)
        self.session.flush()

        # Add 58 NotifiedItems for item_id 100
        for idx in range(58):
            self.session.add(NotifiedItem(
                room_id=room_uuid,
                receiving_slot_id=1,
                sending_slot_id=2,
                item_id=100,
                location_id=1000 + idx,
                item_index=idx,
                timestamp=datetime.now(timezone.utc)
            ))

        # Intentionally create inflated SlotItemCount (108 instead of 58)
        inflated_count = SlotItemCount(room_id=room_uuid, slot_id=1, item_id=100, count=108)
        self.session.add(inflated_count)

        # Datapackage item name mapping
        dp = DatapackageCache(game="Zelda", checksum="checksum123", entity_type="item", entity_id=100, entity_name="Emblem")
        self.session.add(dp)

        # Threshold group requiring 60 Emblems, falsely marked as is_triggered = True
        group = ThresholdGroup(user_tracked_slot_id=slot.id, name="60 Emblems", is_triggered=True)
        self.session.add(group)
        self.session.flush()

        group_item = ThresholdGroupItem(group_id=group.id, item_name="Emblem", quantity=60, is_group=False)
        self.session.add(group_item)
        self.session.commit()

        # Run reconciliation
        from app.services.threshold_service import reconcile_slot_item_counts
        reconcile_slot_item_counts(session=self.session)

        # Verify SlotItemCount was corrected to 58
        updated_count = self.session.query(SlotItemCount).filter_by(room_id=room_uuid, slot_id=1, item_id=100).first()
        self.assertIsNotNone(updated_count)
        self.assertEqual(updated_count.count, 58)

        # Verify group is_triggered was reset to False since 58 < 60
        self.session.refresh(group)
        self.assertFalse(group.is_triggered)


if __name__ == '__main__':
    unittest.main()
