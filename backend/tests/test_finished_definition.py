import importlib.util
import io
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.utils import (
    evaluate_finished,
    resolve_finished_definition,
    parse_cached_checks,
    serialize_cached_checks,
    VALID_FINISHED_DEFINITIONS,
    DEFAULT_FINISHED_DEFINITION,
)
from app.poller import (
    _check_player_completion,
    _parse_player_checks_done,
    _slot_is_finished_for_user,
    _room_is_complete,
)


def _load_revival_migration():
    """
    Load the one-off revival migration as a module.

    Alembic versions are not an importable package, so this goes through the
    file path. Pinning the revision id here means renaming or dropping the
    migration fails loudly instead of silently skipping these tests.
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'alembic', 'versions',
        'b2e75c4a19d8_revive_rooms_completed_while_undrained.py',
    )
    spec = importlib.util.spec_from_file_location('revival_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def user(definition='goal', notify_finished_default=True, global_snooze_until=None):
    return SimpleNamespace(
        finished_definition_default=definition,
        notify_finished_default=notify_finished_default,
        use_condensed_messages_default=False,
        remove_emojis_default=True,
        global_snooze_until=global_snooze_until,
    )


def slot(definition=None, notify_finished=None, snooze_until=None):
    return SimpleNamespace(
        finished_definition=definition,
        notify_finished=notify_finished,
        use_condensed_messages=None,
        remove_emojis=None,
        snooze_until=snooze_until,
    )


def tracker(statuses=None, checks=None):
    """Minimal /api/tracker payload."""
    data = {'player_status': statuses if statuses is not None else {}}
    if checks is not None:
        data['player_checks_done'] = [
            {'team': 0, 'player': slot_id, 'locations': list(range(count))}
            for slot_id, count in checks.items()
        ]
    return data


def run_completion(tracker_data, players, users_by_id, prefs_by_user_slot, tracked_slots_by_user,
                   backfill_check_set=None, prior_checks_known=False):
    name_map = {p['slot_id']: p.get('name', f"Player {p['slot_id']}") for p in players}
    return _check_player_completion(
        tracker_data,
        players,
        1,
        users_by_id,
        prefs_by_user_slot,
        tracked_slots_by_user,
        backfill_check_set or set(),
        name_map,
        name_map,
        {uid: 'Test Room' for uid in users_by_id},
        prior_checks_known,
    )


class TestEvaluateFinished(unittest.TestCase):
    """The full truth table: 4 definitions x 4 fact combinations."""

    CASES = {
        'goal':       {(False, False): False, (True, False): True,  (False, True): False, (True, True): True},
        'all_checks': {(False, False): False, (True, False): False, (False, True): True,  (True, True): True},
        'both':       {(False, False): False, (True, False): False, (False, True): False, (True, True): True},
        'either':     {(False, False): False, (True, False): True,  (False, True): True,  (True, True): True},
    }

    def test_truth_table(self):
        for definition, expectations in self.CASES.items():
            for (goaled, all_checks), expected in expectations.items():
                with self.subTest(definition=definition, goaled=goaled, all_checks=all_checks):
                    self.assertEqual(evaluate_finished(goaled, all_checks, definition), expected)

    def test_all_definitions_are_covered_by_the_valid_set(self):
        self.assertEqual(set(self.CASES), VALID_FINISHED_DEFINITIONS)

    def test_unknown_definition_falls_back_to_goal(self):
        # Includes values a newer server might write that this process predates.
        for bogus in [None, '', 'GOAL', 'released', 'done', 42]:
            with self.subTest(definition=bogus):
                self.assertTrue(evaluate_finished(True, False, bogus))
                self.assertFalse(evaluate_finished(False, True, bogus))

    def test_unknown_checks_degrade_every_definition_to_goal_only(self):
        # has_all_checks=None means "never fetched counts for this room", which
        # must not un-finish a slot that goal alone would have marked finished.
        for definition in VALID_FINISHED_DEFINITIONS:
            with self.subTest(definition=definition):
                self.assertTrue(evaluate_finished(True, None, definition))
                self.assertFalse(evaluate_finished(False, None, definition))

    def test_unknown_is_distinct_from_false(self):
        # The whole point of the tri-state: under 'both', a goaled slot reads as
        # unfinished when we know they still have checks out, but stays finished
        # when we simply have not looked.
        self.assertFalse(evaluate_finished(True, False, 'both'))
        self.assertTrue(evaluate_finished(True, None, 'both'))


class TestResolveFinishedDefinition(unittest.TestCase):

    def test_slot_override_wins(self):
        self.assertEqual(resolve_finished_definition(user('goal'), slot('both')), 'both')

    def test_falls_back_to_user_default(self):
        self.assertEqual(resolve_finished_definition(user('either'), slot(None)), 'either')

    def test_invalid_values_are_ignored_at_each_level(self):
        self.assertEqual(resolve_finished_definition(user('either'), slot('nonsense')), 'either')
        self.assertEqual(resolve_finished_definition(user('nonsense'), slot(None)), DEFAULT_FINISHED_DEFINITION)
        self.assertEqual(resolve_finished_definition(None, None), DEFAULT_FINISHED_DEFINITION)


class TestParsePlayerChecksDone(unittest.TestCase):

    def test_counts_locations_per_slot(self):
        counts, present = _parse_player_checks_done(tracker(checks={1: 5, 2: 12}))
        self.assertTrue(present)
        self.assertEqual(counts, {1: 5, 2: 12})

    def test_missing_payload_reports_absent(self):
        counts, present = _parse_player_checks_done({})
        self.assertEqual(counts, {})
        self.assertFalse(present)

    def test_non_zero_teams_are_ignored(self):
        data = {'player_checks_done': [
            {'team': 0, 'player': 1, 'locations': [1, 2, 3]},
            {'team': 1, 'player': 1, 'locations': [1, 2, 3, 4, 5, 6, 7]},
        ]}
        counts, present = _parse_player_checks_done(data)
        self.assertTrue(present)
        self.assertEqual(counts, {1: 3})

    def test_malformed_entries_are_skipped_not_fatal(self):
        data = {'player_checks_done': [
            'not a dict',
            {'team': 0, 'player': None, 'locations': [1]},
            {'team': 0, 'player': 2, 'locations': 'nope'},
            {'team': 0, 'player': 3, 'locations': [1, 2]},
        ]}
        counts, _ = _parse_player_checks_done(data)
        self.assertEqual(counts, {3: 2})


class TestCompletionFacts(unittest.TestCase):

    def test_zero_total_locations_never_reads_as_all_checks(self):
        # total_locations == 0 is the sentinel for a failed static-tracker fetch.
        players = [{'slot_id': 1, 'name': 'A', 'total_locations': 0,
                    'is_finished': False, 'has_all_checks': False}]

        _, _, all_checks_ids, _, _, _ = run_completion(
            tracker(statuses={'1': 20}, checks={1: 0}), players, {}, {}, {}
        )

        self.assertEqual(all_checks_ids, set())
        self.assertFalse(players[0]['has_all_checks'])

    def test_goal_and_all_checks_are_tracked_independently(self):
        players = [{'slot_id': 1, 'name': 'A', 'total_locations': 10,
                    'is_finished': False, 'has_all_checks': False}]

        _, goaled_ids, all_checks_ids, counts, _, updated = run_completion(
            tracker(statuses={'1': 30}, checks={1: 4}), players, {}, {}, {}
        )

        self.assertEqual(goaled_ids, {1})
        self.assertEqual(all_checks_ids, set())
        self.assertEqual(counts, {1: 4})
        self.assertTrue(updated)

    def test_all_checks_set_when_count_reaches_total(self):
        players = [{'slot_id': 1, 'name': 'A', 'total_locations': 10,
                    'is_finished': False, 'has_all_checks': False}]

        _, goaled_ids, all_checks_ids, _, _, _ = run_completion(
            tracker(statuses={'1': 20}, checks={1: 10}), players, {}, {}, {}
        )

        self.assertEqual(goaled_ids, set())
        self.assertEqual(all_checks_ids, {1})

    def test_missing_checks_payload_holds_previous_value(self):
        players = [{'slot_id': 1, 'name': 'A', 'total_locations': 10,
                    'is_finished': False, 'has_all_checks': True}]

        _, _, all_checks_ids, _, _, updated = run_completion(
            tracker(statuses={'1': 20}), players, {}, {}, {}
        )

        self.assertEqual(all_checks_ids, {1})
        self.assertFalse(updated)

    def test_goal_revert_still_works(self):
        players = [{'slot_id': 1, 'name': 'A', 'total_locations': 10,
                    'is_finished': True, 'has_all_checks': False}]

        _, goaled_ids, _, _, _, updated = run_completion(
            tracker(statuses={'1': 20}, checks={1: 1}), players, {}, {}, {}
        )

        self.assertEqual(goaled_ids, set())
        self.assertFalse(players[0]['is_finished'])
        self.assertTrue(updated)

    def test_legacy_cache_without_has_all_checks_is_backfilled(self):
        players = [{'slot_id': 1, 'name': 'A', 'total_locations': 10, 'is_finished': False}]

        _, _, _, _, _, updated = run_completion(
            tracker(statuses={'1': 20}), players, {}, {}, {}
        )

        self.assertIn('has_all_checks', players[0])
        self.assertTrue(updated)


class TestFinishNotificationTransitions(unittest.TestCase):
    """
    The highest-risk behavior: 'just became finished' is per-user, so two users
    tracking the same slot must be notified on different polls.
    """

    def setUp(self):
        # User 1 -> 'goal', User 2 -> 'both'.
        self.users_by_id = {1: user('goal'), 2: user('both')}
        self.prefs_by_user_slot = {1: {5: slot()}, 2: {5: slot()}}
        self.tracked_slots_by_user = {1: {5}, 2: {5}}
        self.players = [{'slot_id': 5, 'name': 'Chroma', 'total_locations': 100,
                         'is_finished': False, 'has_all_checks': False}]

    def _poll(self, status, checks_done):
        notifs, _, _, _, _, _ = run_completion(
            tracker(statuses={'5': status}, checks={5: checks_done}),
            self.players,
            self.users_by_id,
            self.prefs_by_user_slot,
            self.tracked_slots_by_user,
        )
        return notifs

    def test_goal_user_notified_on_goal_both_user_is_not(self):
        notifs = self._poll(status=30, checks_done=40)

        self.assertIn(1, notifs)
        self.assertNotIn(2, notifs)

    def test_both_user_notified_only_once_checks_complete(self):
        self._poll(status=30, checks_done=40)          # goal only
        notifs = self._poll(status=30, checks_done=100)  # now drained too

        self.assertIn(2, notifs)
        # User 1 was already finished last poll; the edge has passed.
        self.assertNotIn(1, notifs)

    def test_nobody_is_notified_twice(self):
        self._poll(status=30, checks_done=100)  # both users cross the edge here
        notifs = self._poll(status=30, checks_done=100)

        self.assertEqual(notifs, {})

    def test_release_off_slot_never_finishes_for_both_user(self):
        # Goals, keeps playing, never drains: the exact reported scenario.
        for checks in (40, 55, 70, 99):
            notifs = self._poll(status=30, checks_done=checks)
            self.assertNotIn(2, notifs)

    def test_notify_finished_disabled_still_announces_the_finish(self):
        # notify_finished governs the item/hint stream *after* a slot finishes, not
        # the one-off announcement. Gating the announcement on it meant users who
        # turned it off to stop the ongoing noise never learned a slot was done.
        self.prefs_by_user_slot[1][5] = slot(notify_finished=False)

        notifs = self._poll(status=30, checks_done=100)

        self.assertIn(1, notifs)
        self.assertIn(2, notifs)

    def test_finish_announcement_ignores_the_user_level_default_too(self):
        # Same rule at the global level, not just the per-slot override.
        self.users_by_id[1] = user('goal', notify_finished_default=False)

        notifs = self._poll(status=30, checks_done=100)

        self.assertIn(1, notifs)

    def test_slot_snooze_suppresses_the_finish_announcement(self):
        # notify_finished no longer silences this, so snooze is the only way left to
        # stay quiet. It has to work, or a snoozed slot still pings.
        self.prefs_by_user_slot[1][5] = slot(
            snooze_until=datetime.now(timezone.utc) + timedelta(hours=1)
        )

        notifs = self._poll(status=30, checks_done=100)

        self.assertNotIn(1, notifs)
        self.assertIn(2, notifs)

    def test_global_snooze_suppresses_the_finish_announcement(self):
        self.users_by_id[1] = user(
            'goal', global_snooze_until=datetime.now(timezone.utc) + timedelta(hours=1)
        )

        notifs = self._poll(status=30, checks_done=100)

        self.assertNotIn(1, notifs)

    def test_expired_snooze_does_not_suppress(self):
        self.prefs_by_user_slot[1][5] = slot(
            snooze_until=datetime.now(timezone.utc) - timedelta(hours=1)
        )

        notifs = self._poll(status=30, checks_done=100)

        self.assertIn(1, notifs)

    def test_finish_announcement_still_fires_once_only(self):
        # Removing the gate must not turn the transition edge into a repeat.
        self.prefs_by_user_slot[1][5] = slot(notify_finished=False)

        first = self._poll(status=30, checks_done=100)
        second = self._poll(status=30, checks_done=100)

        self.assertIn(1, first)
        self.assertNotIn(1, second)

    def test_backfilling_slot_is_suppressed(self):
        notifs, _, _, _, _, _ = run_completion(
            tracker(statuses={'5': 30}, checks={5: 100}),
            self.players,
            self.users_by_id,
            self.prefs_by_user_slot,
            self.tracked_slots_by_user,
            backfill_check_set={(1, 5), (2, 5)},
        )

        self.assertEqual(notifs, {})

    def test_slot_override_beats_user_default(self):
        # User 1 defaults to 'goal' but overrides this slot to 'both'.
        self.prefs_by_user_slot[1][5] = slot(definition='both')

        notifs = self._poll(status=30, checks_done=40)

        self.assertEqual(notifs, {})


class TestCachedChecksSerialization(unittest.TestCase):

    def test_round_trips_string_keys_to_ints(self):
        self.assertEqual(parse_cached_checks('{"1": 5, "2": 12}'), {1: 5, 2: 12})

    def test_bad_input_yields_empty_dict(self):
        for bad in [None, '', 'not json', '[]', '{"a": "b"}']:
            with self.subTest(value=bad):
                self.assertEqual(parse_cached_checks(bad), {})

    def test_round_trip_preserves_counts(self):
        counts = {1: 0, 2: 47, 3: 512}
        self.assertEqual(parse_cached_checks(serialize_cached_checks(counts)), counts)

    def test_encoding_is_stable_across_insertion_order(self):
        # The poller decides whether to write by comparing serialized forms, so an
        # unstable encoding would rewrite the column on every poll -- exactly the
        # write amplification this column exists to avoid.
        a = serialize_cached_checks({3: 30, 1: 10, 2: 20})
        b = serialize_cached_checks({1: 10, 2: 20, 3: 30})
        self.assertEqual(a, b)

    def test_encoding_changes_when_a_count_changes(self):
        self.assertNotEqual(
            serialize_cached_checks({1: 10}),
            serialize_cached_checks({1: 11}),
        )



class TestUnknownChecksInPoller(unittest.TestCase):
    """
    A room whose check counts have never been fetched must behave exactly as it
    did before this feature existed -- goal-only -- rather than reporting every
    goaled slot as unfinished.
    """

    def setUp(self):
        self.users_by_id = {1: user('both')}
        self.prefs_by_user_slot = {1: {5: slot()}}
        self.tracked_slots_by_user = {1: {5}}

    def test_goal_notifies_a_both_user_when_checks_are_unknown(self):
        # No player_checks_done in the payload and no prior counts: 'both'
        # degrades to goal-only, so this user is still told the slot finished.
        players = [{'slot_id': 5, 'name': 'Chroma', 'total_locations': 100,
                    'is_finished': False, 'has_all_checks': False}]

        notifs, _, _, _, checks_known, _ = run_completion(
            tracker(statuses={'5': 30}), players,
            self.users_by_id, self.prefs_by_user_slot, self.tracked_slots_by_user,
        )

        self.assertFalse(checks_known)
        self.assertIn(1, notifs)

    def test_goal_does_not_notify_a_both_user_once_checks_are_known(self):
        # Same goal event, but now we have counts and they are still sending.
        players = [{'slot_id': 5, 'name': 'Chroma', 'total_locations': 100,
                    'is_finished': False, 'has_all_checks': False}]

        notifs, _, _, _, checks_known, _ = run_completion(
            tracker(statuses={'5': 30}, checks={5: 40}), players,
            self.users_by_id, self.prefs_by_user_slot, self.tracked_slots_by_user,
        )

        self.assertTrue(checks_known)
        self.assertNotIn(1, notifs)

    def test_prior_counts_make_checks_known_without_a_fresh_payload(self):
        # Host stopped serving player_checks_done, but we read counts before:
        # keep trusting the stored facts rather than reverting to unknown.
        players = [{'slot_id': 5, 'name': 'Chroma', 'total_locations': 100,
                    'is_finished': False, 'has_all_checks': False}]

        _, _, _, _, checks_known, _ = run_completion(
            tracker(statuses={'5': 30}), players,
            self.users_by_id, self.prefs_by_user_slot, self.tracked_slots_by_user,
            prior_checks_known=True,
        )

        self.assertTrue(checks_known)


class TestSlotIsFinishedForUser(unittest.TestCase):

    def test_unknown_checks_fall_back_to_goal(self):
        u, s = user('both'), slot()
        self.assertTrue(_slot_is_finished_for_user(5, {5}, set(), u, s, checks_known=False))
        self.assertFalse(_slot_is_finished_for_user(5, {5}, set(), u, s, checks_known=True))

    def test_known_checks_are_honored(self):
        u, s = user('both'), slot()
        self.assertTrue(_slot_is_finished_for_user(5, {5}, {5}, u, s, checks_known=True))

    def test_missing_slot_prefs_still_resolves(self):
        # The hint suppression path can pass slot_prefs=None.
        self.assertTrue(_slot_is_finished_for_user(5, {5}, set(), user('goal'), None, checks_known=True))


class TestCompletionFactMarker(unittest.TestCase):
    """
    The gatekeeper decides whether a room has ever been processed by searching
    cached_players_json for the literal '"has_all_checks":'. If the field is
    ever renamed without updating that marker, the forced catch-up poll silently
    stops firing and rooms keep unknown check counts forever.
    """

    MARKER = '"has_all_checks":'

    def test_processed_players_json_contains_the_marker(self):
        players = [{'slot_id': 1, 'name': 'A', 'total_locations': 10, 'is_finished': False}]
        run_completion(tracker(statuses={'1': 20}, checks={1: 3}), players, {}, {}, {})

        self.assertIn(self.MARKER, json.dumps(players))

    def test_marker_absent_before_processing(self):
        legacy = [{'slot_id': 1, 'name': 'A', 'total_locations': 10, 'is_finished': True}]

        self.assertNotIn(self.MARKER, json.dumps(legacy))

    def test_marker_appears_even_without_check_data(self):
        # Hosts that never serve player_checks_done must still clear the forced
        # poll, or the gate would refetch that room on every cycle forever.
        players = [{'slot_id': 1, 'name': 'A', 'total_locations': 10, 'is_finished': True}]
        run_completion(tracker(statuses={'1': 30}), players, {}, {}, {})

        self.assertIn(self.MARKER, json.dumps(players))


class TestRoomIsComplete(unittest.TestCase):
    """
    is_complete stops a room from ever being polled again and is never reset, so
    the cost of firing it early is total and silent (issue #263).
    """

    def test_all_goaled_and_all_drained_completes(self):
        self.assertTrue(_room_is_complete(3, {1, 2, 3}, {1, 2, 3}, checks_known=True))

    def test_all_goaled_but_still_sending_does_not_complete(self):
        # The release-off case: everyone goaled, one player still holds locations.
        self.assertFalse(_room_is_complete(3, {1, 2, 3}, {1, 2}, checks_known=True))

    def test_all_drained_but_not_all_goaled_does_not_complete(self):
        self.assertFalse(_room_is_complete(3, {1, 2}, {1, 2, 3}, checks_known=True))

    def test_unknown_checks_fall_back_to_goal_only(self):
        # A host that never serves player_checks_done must behave as it always
        # has, rather than polling until the 30-day stale sweep suspends it.
        self.assertTrue(_room_is_complete(3, {1, 2, 3}, set(), checks_known=False))

    def test_unknown_checks_still_require_all_goaled(self):
        self.assertFalse(_room_is_complete(3, {1, 2}, set(), checks_known=False))

    def test_unknown_totals_fall_back_to_goal_only(self):
        # has_all_checks is checks_done >= total_locations, so a slot with no
        # total_locations can never register as drained. Requiring it anyway would
        # pin the room open permanently even though its checks are well known.
        self.assertTrue(
            _room_is_complete(3, {1, 2, 3}, set(), checks_known=True, totals_known=False)
        )

    def test_unknown_totals_still_require_all_goaled(self):
        self.assertFalse(
            _room_is_complete(3, {1, 2}, set(), checks_known=True, totals_known=False)
        )

    def test_known_totals_are_the_default(self):
        # The parameter is opt-out; callers without total_locations trouble behave
        # exactly as before it existed.
        self.assertFalse(_room_is_complete(3, {1, 2, 3}, {1, 2}, checks_known=True))

    def test_empty_room_never_completes(self):
        # total_players 0 is the failed-setup sentinel, not an instantly-done room.
        self.assertFalse(_room_is_complete(0, set(), set(), checks_known=True))
        self.assertFalse(_room_is_complete(0, set(), set(), checks_known=False))

    def test_extra_goaled_ids_do_not_break_the_comparison(self):
        # goaled_ids is built from the tracker payload and can outrun the cached
        # player list after a re-setup; >= keeps that from stalling completion.
        self.assertTrue(_room_is_complete(2, {1, 2, 3}, {1, 2, 3}, checks_known=True))


class TestUndrainedRoomRevival(unittest.TestCase):
    """
    The one-off reconciliation in b2e75c4a19d8 decides which stuck rooms to
    revive by reading cached_players_json. Rooms already stuck are unreachable
    any other way -- nothing will ever poll them again on its own.
    """

    def setUp(self):
        self.is_drained = _load_revival_migration()._is_drained

    def test_fully_drained_room_stays_complete(self):
        self.assertTrue(self.is_drained(json.dumps([
            {'slot_id': 1, 'has_all_checks': True},
            {'slot_id': 2, 'has_all_checks': True},
        ])))

    def test_room_with_one_slot_still_sending_is_revived(self):
        self.assertFalse(self.is_drained(json.dumps([
            {'slot_id': 1, 'has_all_checks': True},
            {'slot_id': 2, 'has_all_checks': False},
        ])))

    def test_room_cached_before_completion_facts_existed_is_revived(self):
        # No has_all_checks key at all: unknown, not drained. One poll computes
        # the facts and re-completes the room if it really was done.
        self.assertFalse(self.is_drained(json.dumps([
            {'slot_id': 1, 'is_finished': True},
        ])))

    def test_partially_backfilled_cache_is_revived(self):
        self.assertFalse(self.is_drained(json.dumps([
            {'slot_id': 1, 'has_all_checks': True},
            {'slot_id': 2, 'is_finished': True},
        ])))

    def test_malformed_or_empty_cache_is_revived_not_fatal(self):
        for payload in ('', None, '[]', 'not json', '{}', '[null]'):
            with self.subTest(payload=payload):
                self.assertFalse(self.is_drained(payload))

class TestHistoryUnknownChecksContract(unittest.TestCase):
    """
    History rows must serialize has_all_checks as null when a room's counts were
    never fetched, exactly as the players and tracked-slot endpoints do.

    Emitting False there is the original complaint inverted: the client would read
    "still has checks out" and, under 'both' or 'all_checks', show every goaled slot
    in that room as unfinished -- flooding filtered views with slots that finished
    weeks ago.
    """

    def _derive(self, receiver_obj, checks_known):
        # Mirrors the derivation in history_routes.py.
        return (receiver_obj.get('has_all_checks', False) if receiver_obj else False)             if checks_known else None

    def test_unknown_counts_yield_none(self):
        self.assertIsNone(self._derive({'has_all_checks': True}, checks_known=False))
        self.assertIsNone(self._derive({'has_all_checks': False}, checks_known=False))
        self.assertIsNone(self._derive(None, checks_known=False))

    def test_known_counts_yield_the_fact(self):
        self.assertTrue(self._derive({'has_all_checks': True}, checks_known=True))
        self.assertFalse(self._derive({'has_all_checks': False}, checks_known=True))

    def test_none_and_false_diverge_under_strict_definitions(self):
        # Why the distinction earns its keep.
        for definition in ('both', 'all_checks'):
            self.assertFalse(evaluate_finished(True, False, definition))
            self.assertTrue(evaluate_finished(True, None, definition))

    def test_all_three_history_sites_use_checks_known(self):
        # Three derivation sites; a new one added without the guard would regress.
        source = io.open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'app', 'routes', 'history_routes.py',
            ),
            encoding='utf-8',
        ).read()

        self.assertEqual(3, source.count("has_all_checks = (receiver_obj.get("))
        self.assertNotIn("has_all_checks = receiver_obj.get('has_all_checks', False)", source)

    def test_passthroughs_do_not_default_to_false(self):
        source = io.open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'app', 'routes', 'history_routes.py',
            ),
            encoding='utf-8',
        ).read()

        self.assertNotIn("temp_item.get(\"playerHasAllChecks\", False)", source)
        self.assertNotIn("temp_item.get('playerHasAllChecks', False)", source)

if __name__ == '__main__':
    unittest.main()
