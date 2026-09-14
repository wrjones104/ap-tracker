"""The batch cache check says when something is wrong (#336).

On 2026-09-11 production held ~1,577 checksums the poller could never resolve,
each holding its room in a setup retry loop, and nothing in the logs said so.
The only way to see it was a database query. Malformed game_checksums_json was
worse: a bare except skipped the room without a word.

The count is zero today, so these tests pin the signal rather than a fix: an
unresolved checksum or an unreadable room must produce a warning, and a healthy
run must produce none.
"""
import os
import sys
import unittest
from types import SimpleNamespace

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_cache_check_logging.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.poller import collect_required_checksums, log_unresolved_checksums, room_checksums


def _room(room_id, checksums_json):
    return SimpleNamespace(id=room_id, game_checksums_json=checksums_json)


class TestRoomChecksums(unittest.TestCase):
    def test_reads_the_values(self):
        self.assertEqual(sorted(room_checksums('{"A": "c1", "B": "c2"}')), ["c1", "c2"])

    def test_empty_or_missing_is_no_checksums_not_an_error(self):
        self.assertEqual(room_checksums(None), [])
        self.assertEqual(room_checksums('{}'), [])

    def test_unreadable_shapes_return_none(self):
        """Each of these raised inside the old bare except."""
        for raw in ('{not json', '["c1"]', '{"A": {"nested": 1}}', '"c1"'):
            with self.subTest(raw=raw):
                self.assertIsNone(room_checksums(raw))

    def test_values_that_are_not_checksums_return_none(self):
        """These parsed without error under the old code and went straight into
        the missing-checksum query. A null or empty one can never be cached, so
        its room would retry setup forever while looking healthy."""
        for raw in ('{"A": null}', '{"A": 123}', '{"A": true}', '{"A": ""}',
                    '{"A": "   "}', '{"A": "c1", "B": null}'):
            with self.subTest(raw=raw):
                self.assertIsNone(room_checksums(raw))

    def test_absurdly_deep_nesting_is_unreadable_not_an_exception(self):
        """json.loads raises RecursionError here, which is not a ValueError.
        Escaping would end the supervisor tick for every room after this one."""
        self.assertIsNone(room_checksums('{"A": ' + '[' * 100000))


class TestCollectRequiredChecksums(unittest.TestCase):
    def test_malformed_rooms_are_named_and_the_rest_still_count(self):
        rooms = [
            _room(1, '{"A": "c1"}'),
            _room(2, '{not json'),
            _room(3, '{"B": "c2"}'),
            _room(4, '["c3"]'),
        ]

        with self.assertLogs(level='WARNING') as logs:
            required = collect_required_checksums(rooms)

        self.assertEqual(required, {"c1", "c2"})
        self.assertEqual(len(logs.records), 1)
        message = logs.records[0].getMessage()
        self.assertIn("2 room(s)", message)
        self.assertIn("[2, 4]", message)

    def test_healthy_rooms_log_nothing(self):
        rooms = [_room(1, '{"A": "c1"}'), _room(2, None), _room(3, '{}')]

        with self.assertNoLogs(level='WARNING'):
            required = collect_required_checksums(rooms)

        self.assertEqual(required, {"c1"})


class TestLogUnresolvedChecksums(unittest.TestCase):
    def test_unresolved_checksums_are_counted_with_the_rooms_they_hold(self):
        rooms = [
            _room(1, '{"A": "dead"}'),
            _room(2, '{"A": "dead", "B": "ok"}'),
            _room(3, '{"B": "ok"}'),
            _room(4, '{broken'),
        ]

        with self.assertLogs(level='WARNING') as logs:
            log_unresolved_checksums({"dead"}, {"dead", "ok"}, rooms)

        message = logs.records[0].getMessage()
        self.assertIn("1 of 2 checksums", message)
        self.assertIn("2 room(s)", message)
        self.assertIn("dead", message, "the warning should name what to look up")

    def test_nothing_unresolved_logs_nothing(self):
        """Today's production state. The warning must mean something when it appears."""
        with self.assertNoLogs(level='WARNING'):
            log_unresolved_checksums(set(), {"ok"}, [_room(1, '{"A": "ok"}')])


if __name__ == '__main__':
    unittest.main()
