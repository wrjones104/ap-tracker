import json
import unittest
from types import SimpleNamespace

from app.utils import (
    evaluate_finished,
    resolve_finished_definition,
    parse_cached_checks,
    serialize_cached_checks,
    VALID_FINISHED_DEFINITIONS,
    DEFAULT_FINISHED_DEFINITION,
)
from app.poller import _check_player_completion, _parse_player_checks_done, _slot_is_finished_for_user


def user(definition='goal', notify_finished_default=True):
    return SimpleNamespace(
        finished_definition_default=definition,
        notify_finished_default=notify_finished_default,
        use_condensed_messages_default=False,
        remove_emojis_default=True,
    )


def slot(definition=None, notify_finished=None):
    return SimpleNamespace(
        finished_definition=definition,
        notify_finished=notify_finished,
        use_condensed_messages=None,
        remove_emojis=None,
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

    def test_notify_finished_disabled_suppresses_the_notification(self):
        self.prefs_by_user_slot[1][5] = slot(notify_finished=False)

        notifs = self._poll(status=30, checks_done=100)

        self.assertNotIn(1, notifs)
        self.assertIn(2, notifs)

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


if __name__ == '__main__':
    unittest.main()
