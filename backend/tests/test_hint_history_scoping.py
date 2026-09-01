import os
import sys
import unittest
import json
import tempfile
from datetime import datetime, timezone

# Create a unique temporary DB for this test process
temp_db_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
TEST_DB_PATH = temp_db_file.name
temp_db_file.close()

os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import (
    Base, NotifiedHint, UserTrackedSlot, TrackedRoom, DatapackageCache,
    User, UserRoomSubscription
)
from app.routes.history_routes import (
    process_hints_for_user, fetch_datapackage_names, DATAPACKAGE_LOOKUP_CHUNK_SIZE
)


class TestHintHistoryScoping(unittest.TestCase):
    """
    Regression coverage for the hint history query.

    process_hints_for_user used to fetch every hint in every room the user had
    any tracked slot in, then discard the untracked ones in Python. On busy
    accounts that produced a datapackage name lookup with thousands of tuples in
    a single IN clause, which failed in production and dumped the entire bind
    parameter list into the logs. The tracked-slot filter now runs in SQL, and
    the name lookup is chunked below Postgres' 65535 bind parameter ceiling.

    These tests pin the visible behaviour: scoping and routing must stay
    identical to the old Python-side filter.
    """

    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.session = Session()

    def tearDown(self):
        self.session.close()
        Session.remove()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def _make_room(self, uuid, checksum="checksumH", slot_ids=(1, 2, 3, 4)):
        room = TrackedRoom(
            room_id=uuid,
            tracker_id="test_tracker",
            hostname="archipelago.gg",
            game_checksums_json=json.dumps({"Zelda": checksum}),
            cached_players_json=json.dumps([
                {"slot_id": s, "name": f"Player{s}", "game": "Zelda"} for s in slot_ids
            ])
        )
        self.session.add(room)
        self.session.flush()
        return room

    def _make_user(self, discord_id="77777"):
        user = User(discord_id=discord_id, discord_username="hintscopeuser")
        self.session.add(user)
        self.session.flush()
        return user

    def _track(self, user, room, slot_id):
        self.session.add(UserRoomSubscription(user_id=user.id, room_id=room.id, alias="Room"))
        self.session.add(UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=slot_id))
        self.session.flush()

    def _add_hint(self, room, hint_id, item_owner_id, location_owner_id, is_found=False):
        self.session.add(NotifiedHint(
            id=hint_id,
            room_id=room.room_id,
            item_owner_id=item_owner_id,
            location_owner_id=location_owner_id,
            item_id=500 + hint_id,
            location_id=9000 + hint_id,
            is_found=is_found,
            timestamp=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        ))
        self.session.flush()

    def test_only_hints_touching_a_tracked_slot_are_returned(self):
        room = self._make_room("hint-scope-room")
        user = self._make_user()
        self._track(user, room, slot_id=1)

        self._add_hint(room, hint_id=1, item_owner_id=1, location_owner_id=2)   # for you
        self._add_hint(room, hint_id=2, item_owner_id=2, location_owner_id=1)   # by you
        self._add_hint(room, hint_id=3, item_owner_id=3, location_owner_id=4)   # untracked
        self.session.commit()

        result = process_hints_for_user(self.session, user.id)
        returned = {h['id'] for h in result['hints_for_you']} | {h['id'] for h in result['hints_by_you']}

        self.assertEqual(returned, {1, 2}, "Hints not touching a tracked slot must not be returned")
        self.assertEqual([h['id'] for h in result['hints_for_you']], [1])
        self.assertEqual([h['id'] for h in result['hints_by_you']], [2])

    def test_slots_are_scoped_per_room_not_across_rooms(self):
        """Tracking slot 1 in room A must not pull slot 1 hints out of room B."""
        room_a = self._make_room("hint-scope-room-a")
        room_b = self._make_room("hint-scope-room-b")
        user = self._make_user()
        self._track(user, room_a, slot_id=1)
        self._track(user, room_b, slot_id=2)

        self._add_hint(room_a, hint_id=10, item_owner_id=1, location_owner_id=3)  # tracked in A
        self._add_hint(room_a, hint_id=11, item_owner_id=2, location_owner_id=3)  # slot 2 untracked in A
        self._add_hint(room_b, hint_id=12, item_owner_id=2, location_owner_id=3)  # tracked in B
        self._add_hint(room_b, hint_id=13, item_owner_id=1, location_owner_id=3)  # slot 1 untracked in B
        self.session.commit()

        result = process_hints_for_user(self.session, user.id)
        returned = {h['id'] for h in result['hints_for_you']} | {h['id'] for h in result['hints_by_you']}

        self.assertEqual(returned, {10, 12})

    def test_found_hints_excluded_unless_requested(self):
        room = self._make_room("hint-scope-room-found")
        user = self._make_user()
        self._track(user, room, slot_id=1)

        self._add_hint(room, hint_id=20, item_owner_id=1, location_owner_id=2, is_found=False)
        self._add_hint(room, hint_id=21, item_owner_id=1, location_owner_id=2, is_found=True)
        self.session.commit()

        open_only = process_hints_for_user(self.session, user.id)
        self.assertEqual([h['id'] for h in open_only['hints_for_you']], [20])

        with_found = process_hints_for_user(self.session, user.id, include_found=True)
        self.assertEqual({h['id'] for h in with_found['hints_for_you']}, {20, 21})

    def test_room_scoped_call_ignores_other_rooms(self):
        room_a = self._make_room("hint-scope-only-a")
        room_b = self._make_room("hint-scope-only-b")
        user = self._make_user()
        self._track(user, room_a, slot_id=1)
        self._track(user, room_b, slot_id=1)

        self._add_hint(room_a, hint_id=30, item_owner_id=1, location_owner_id=2)
        self._add_hint(room_b, hint_id=31, item_owner_id=1, location_owner_id=2)
        self.session.commit()

        result = process_hints_for_user(self.session, user.id, room_db_id=room_a.id)
        self.assertEqual([h['id'] for h in result['hints_for_you']], [30])

    def test_untracked_user_gets_empty_result(self):
        self._make_room("hint-scope-room-empty")
        user = self._make_user()
        self.session.commit()

        result = process_hints_for_user(self.session, user.id)
        self.assertEqual(result, {"hints_for_you": [], "hints_by_you": []})

    def test_datapackage_lookup_resolves_across_chunk_boundaries(self):
        """More keys than the chunk size must still all resolve."""
        key_count = DATAPACKAGE_LOOKUP_CHUNK_SIZE * 2 + 7
        for i in range(key_count):
            self.session.add(DatapackageCache(
                game="Zelda", checksum="chunkcs", entity_type='item',
                entity_id=i, entity_name=f"Item {i}"
            ))
        self.session.commit()

        keys = {("chunkcs", 'item', i) for i in range(key_count)}
        resolved = fetch_datapackage_names(self.session, keys)

        self.assertEqual(len(resolved), key_count)
        self.assertEqual(resolved[("chunkcs", 'item', 0)], "Item 0")
        self.assertEqual(resolved[("chunkcs", 'item', key_count - 1)], f"Item {key_count - 1}")

    def test_datapackage_lookup_handles_empty_key_set(self):
        self.assertEqual(fetch_datapackage_names(self.session, set()), {})


if __name__ == '__main__':
    unittest.main()
