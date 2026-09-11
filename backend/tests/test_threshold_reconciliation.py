"""Reconciliation contract for SlotItemCount.

These tests pin down a deliberate narrowing. reconcile_slot_item_counts used to
recompute counts from NotifiedItem in both directions, which was correct while
history was kept forever. It is not correct now that retention_service purges
NotifiedItem on a window and leaves SlotItemCount alone: an inflated count and a
correct count whose early history has aged out look identical from here, so
correcting downward would silently reset milestone progress on exactly the
long-running async multiworlds the counts exist to serve.

So the contract is now:

  * counts move up toward what history shows, never down
  * a count with no surviving history is left alone, not deleted
  * the premature-trigger audit reads SlotItemCount, the authority that survives
    a purge, rather than the history floor
"""
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

ROOM_UUID = "test-room-uuid-123"


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

    def _build_room(self, surviving_items, stored_count, requirement=60, is_triggered=True):
        """One room, one tracked slot, one threshold group requiring `requirement`.

        `surviving_items` is how many NotifiedItem rows still exist, standing in
        for whatever a retention purge left behind. `stored_count` is what
        SlotItemCount holds independently of them.
        """
        room = TrackedRoom(
            room_id=ROOM_UUID,
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

        for idx in range(surviving_items):
            self.session.add(NotifiedItem(
                room_id=ROOM_UUID,
                receiving_slot_id=1,
                sending_slot_id=2,
                item_id=100,
                location_id=1000 + idx,
                item_index=idx,
                timestamp=datetime.now(timezone.utc)
            ))

        self.session.add(SlotItemCount(
            room_id=ROOM_UUID, slot_id=1, item_id=100, count=stored_count
        ))
        self.session.add(DatapackageCache(
            game="Zelda", checksum="checksum123", entity_type="item",
            entity_id=100, entity_name="Emblem"
        ))

        group = ThresholdGroup(
            user_tracked_slot_id=slot.id, name=f"{requirement} Emblems", is_triggered=is_triggered
        )
        self.session.add(group)
        self.session.flush()
        self.session.add(ThresholdGroupItem(
            group_id=group.id, item_name="Emblem", quantity=requirement, is_group=False
        ))
        self.session.commit()
        return group

    def _run(self):
        from app.services.threshold_service import reconcile_slot_item_counts
        reconcile_slot_item_counts(session=self.session)

    def _count(self):
        return self.session.query(SlotItemCount).filter_by(
            room_id=ROOM_UUID, slot_id=1, item_id=100
        ).first()

    def test_repairs_undercount_from_history(self):
        """The drift the legacy item_index backfill actually causes."""
        group = self._build_room(surviving_items=58, stored_count=10, requirement=60)
        self._run()

        self.assertEqual(self._count().count, 58)
        self.session.refresh(group)
        # 58 is still short of 60, so the premature trigger is still reset.
        self.assertFalse(group.is_triggered)

    def test_does_not_lower_count_when_history_has_been_purged(self):
        """A count above surviving history is treated as the authority.

        This is the retention case: the player really did receive 108, and the
        first 50 rows aged out. Recomputing from history would drop the count to
        58 and un-trigger a milestone that legitimately fired.
        """
        group = self._build_room(surviving_items=58, stored_count=108, requirement=60)
        self._run()

        self.assertEqual(self._count().count, 108)
        self.session.refresh(group)
        self.assertTrue(group.is_triggered)

    def test_resets_trigger_when_authoritative_count_is_short(self):
        """The premature-trigger audit still fires, judged on the counts."""
        group = self._build_room(surviving_items=30, stored_count=30, requirement=60)
        self._run()

        self.assertEqual(self._count().count, 30)
        self.session.refresh(group)
        self.assertFalse(group.is_triggered)

    def test_keeps_counts_with_no_surviving_history(self):
        """A fully purged room keeps its counts rather than losing them."""
        group = self._build_room(surviving_items=0, stored_count=75, requirement=60)
        self._run()

        surviving = self._count()
        self.assertIsNotNone(surviving, "count row was deleted when its history aged out")
        self.assertEqual(surviving.count, 75)
        self.session.refresh(group)
        self.assertTrue(group.is_triggered)


if __name__ == '__main__':
    unittest.main()
