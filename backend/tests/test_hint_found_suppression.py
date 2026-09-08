import unittest
from types import SimpleNamespace

from app.poller import _process_hints


ROOM_UUID = "room-abc"
ROOM_DB_ID = 1

GAME_MAP = {1: "Alpha Game", 2: "Beta Game"}
GAME_CHECKSUMS = {"Alpha Game": "chk-alpha", "Beta Game": "chk-beta"}


def _hint(io_id, lo_id, loc_id, item_id, found, flags=1):
    """One hint row in the static tracker's positional format."""
    return [io_id, lo_id, loc_id, item_id, found, "", flags]


def _tracker(hints):
    return {'hints': [{'hints': hints}]}


def _run(hints, existing_hints_map=None, has_hint_history=True):
    return _process_hints(
        _tracker(hints),
        ROOM_UUID,
        ROOM_DB_ID,
        existing_hints_map or {},
        GAME_MAP,
        GAME_CHECKSUMS,
        has_hint_history,
    )


class TestHintFoundSuppression(unittest.TestCase):
    """
    A hint that is already found the first time the poller sees it is not
    actionable: the location was checked before the poll, so the item has
    already been sent. It is stored but never announced.
    """

    def test_unfound_hint_notifies(self):
        to_add, notify, cache_keys, found_pairs = _run([_hint(1, 2, 500, 900, False)])

        self.assertEqual(len(to_add), 1)
        self.assertFalse(to_add[0].is_found)
        self.assertEqual(len(notify), 1)
        self.assertEqual(notify[0]['item_id'], 900)
        self.assertEqual(found_pairs, set())
        # Names are resolved only for hints that will be announced.
        self.assertIn(("chk-alpha", 'item', 900), cache_keys)
        self.assertIn(("chk-beta", 'location', 500), cache_keys)

    def test_already_found_hint_is_stored_but_not_notified(self):
        to_add, notify, cache_keys, found_pairs = _run([_hint(1, 2, 500, 900, True)])

        # Still recorded, so hint history stays complete.
        self.assertEqual(len(to_add), 1)
        self.assertTrue(to_add[0].is_found)
        self.assertEqual(to_add[0].item_id, 900)
        # But no "New Hint!" of its own.
        self.assertEqual(notify, [])
        self.assertEqual(cache_keys, set())
        # The pair survives, so an item delivered in the same poll still gets
        # its bulb prefix.
        self.assertEqual(found_pairs, {(500, 900)})

    def test_mixed_batch_notifies_only_the_unfound_hint(self):
        _, notify, _, found_pairs = _run([
            _hint(1, 2, 500, 900, True),
            _hint(2, 1, 501, 901, False),
        ])

        self.assertEqual([h['item_id'] for h in notify], [901])
        self.assertEqual(found_pairs, {(500, 900)})

    def test_existing_hint_flipping_to_found_still_notifies_nothing(self):
        existing = SimpleNamespace(is_found=False, timestamp=None, updated_at=None)
        to_add, notify, _, found_pairs = _run(
            [_hint(1, 2, 500, 900, True)],
            existing_hints_map={(1, 2, 900, 500): existing},
        )

        self.assertEqual(to_add, [])
        self.assertEqual(notify, [])
        self.assertTrue(existing.is_found)
        self.assertEqual(found_pairs, {(500, 900)})

    def test_backfill_suppresses_unfound_hints_too(self):
        to_add, notify, _, found_pairs = _run(
            [_hint(1, 2, 500, 900, False)],
            has_hint_history=False,
        )

        self.assertEqual(len(to_add), 1)
        self.assertEqual(notify, [])
        self.assertEqual(found_pairs, set())


if __name__ == '__main__':
    unittest.main()
