"""The dedup floor that has to outlive the retention purge.

The poller decided what was new by comparing the Archipelago feed against
surviving rows in notified_items. That is only sound while notified_items is kept
forever. The feed is cumulative and re-enumerated from index zero on every poll,
so once retention deletes a row, the index it held is indistinguishable from one
the slot has never received.

Without a floor, the failure is:

    full history    -> added 0  notifications 0
    after 90d purge -> added 3  notifications 3

Three consequences, worst first. SlotItemCount is incremented once per re-added
row and is never recomputed downward, so the count stays inflated and milestone
groups fire early and stay fired. A push notification goes out for every purged
item on every actively polled room. And the re-inserted rows get fresh ids, so
the client history cursor replays months of history into the app.

TrackedRoom.item_index_watermark_json is the floor. These tests pin it.
"""
import os
import sys
import unittest

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_watermark.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.poller import _process_received_items
from app.utils import serialize_index_watermarks, parse_index_watermarks

ROOM = 'room-1'
GAME_MAP = {1: 'Zelda', 2: 'Metroid'}
CHECKSUMS = {'Zelda': 'c1', 'Metroid': 'c2'}
TRACKED = {7: {1}}


def feed(n):
    """An Archipelago feed where slot 1 has received n items, indices 0..n-1."""
    return {'player_items_received': [
        {'player': 1, 'items': [(100 + i, 200 + i, 2, 0) for i in range(n)]}
    ]}


def history(indices):
    """Surviving notified_items rows for slot 1 at the given indices."""
    return {(1, i, 100 + i, 200 + i) for i in indices}


def run(tracker, existing, floor):
    items, notifs, _keys, _count = _process_received_items(
        tracker, ROOM, 1, existing, TRACKED, GAME_MAP, CHECKSUMS, True, floor
    )
    return [i.item_index for i in items], len(notifs)


class TestItemIndexWatermark(unittest.TestCase):
    def test_without_a_floor_a_purge_replays_history(self):
        """The bug, pinned so it cannot come back quietly."""
        added, notifs = run(feed(5), history([3, 4]), None)
        self.assertEqual(added, [0, 1, 2])
        self.assertEqual(notifs, 3)

    def test_floor_suppresses_purged_indices(self):
        added, notifs = run(feed(5), history([3, 4]), {1: 4})
        self.assertEqual(added, [])
        self.assertEqual(notifs, 0)

    def test_floor_holds_when_the_slot_is_purged_entirely(self):
        """The case a floor derived from surviving rows cannot cover.

        A slot with no rows left has no maximum to read, so the watermark has to
        be persisted rather than recomputed.
        """
        added, notifs = run(feed(5), set(), {1: 4})
        self.assertEqual(added, [])
        self.assertEqual(notifs, 0)

    def test_genuinely_new_items_still_arrive(self):
        """The floor must not become a ceiling."""
        added, notifs = run(feed(7), set(), {1: 4})
        self.assertEqual(added, [5, 6])
        self.assertEqual(notifs, 2)

    def test_absent_floor_falls_back_to_the_history_set(self):
        """A room with no watermark behaves exactly as it did before retention."""
        added, notifs = run(feed(5), history([0, 1, 2, 3, 4]), {})
        self.assertEqual(added, [])
        self.assertEqual(notifs, 0)

    def test_floor_is_per_slot(self):
        """One slot's watermark must not suppress another's items."""
        tracker = {'player_items_received': [
            {'player': 1, 'items': [(100 + i, 200 + i, 2, 0) for i in range(3)]},
            {'player': 2, 'items': [(300 + i, 400 + i, 1, 0) for i in range(3)]},
        ]}
        items, _notifs, _k, _c = _process_received_items(
            tracker, ROOM, 1, set(), {7: {1, 2}}, GAME_MAP, CHECKSUMS, True, {1: 2}
        )
        # Slot 1 is fully covered by its floor; slot 2 has none and is untouched.
        self.assertEqual([(i.receiving_slot_id, i.item_index) for i in items],
                         [(2, 0), (2, 1), (2, 2)])


class TestWatermarkEncoding(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(parse_index_watermarks(serialize_index_watermarks({1: 4, 2: 9})),
                         {1: 4, 2: 9})

    def test_byte_stable_regardless_of_insertion_order(self):
        """The poller compares the encoded form to decide whether to write."""
        self.assertEqual(serialize_index_watermarks({2: 9, 1: 4}),
                         serialize_index_watermarks({1: 4, 2: 9}))

    def test_bad_data_means_no_floor_rather_than_an_exception(self):
        for junk in (None, '', 'not json', '[]', '{"a": "b"}'):
            self.assertEqual(parse_index_watermarks(junk), {},
                             f"expected no floor from {junk!r}")


if __name__ == '__main__':
    unittest.main()
