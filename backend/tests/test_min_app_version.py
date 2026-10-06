"""
Tests for GET /config's min_app_version coming from MIN_APP_VERSION.

The floor used to be hardcoded, so raising it before a breaking server change
needed a release. It is now read from the environment, with the old value as
the default. See #343.
"""
import os
import unittest
from unittest.mock import patch

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_min_app_version.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='  # Valid Fernet key

# Import through `app.*` only, never `backend.app.*` -- see the note in
# test_slot_track_mode.py.
from app import create_app, Session, engine
from app.routes.auth_routes import DEFAULT_MIN_APP_VERSION, _parse_min_app_version


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class MinAppVersionTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        _parse_min_app_version.cache_clear()
        self.addCleanup(_parse_min_app_version.cache_clear)

    def tearDown(self):
        Session.remove()
        engine.dispose()
        self.app_context.pop()
        _remove_test_db()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        _remove_test_db()

    def min_version(self, env_value=None):
        env = {} if env_value is None else {'MIN_APP_VERSION': env_value}
        with patch.dict(os.environ, env):
            if env_value is None:
                os.environ.pop('MIN_APP_VERSION', None)
            resp = self.app.test_client().get('/config')
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return resp.get_json()['min_app_version']

    def test_unset_keeps_the_old_floor(self):
        self.assertEqual(DEFAULT_MIN_APP_VERSION, 9)
        self.assertEqual(self.min_version(), 9)

    def test_blank_keeps_the_old_floor(self):
        self.assertEqual(self.min_version('  '), 9)

    def test_the_environment_raises_the_floor(self):
        self.assertEqual(self.min_version('78'), 78)

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(self.min_version(' 78\n'), 78)

    def test_a_typo_falls_back_instead_of_failing(self):
        for bad in ('seventy-eight', '78.0', '0', '-5'):
            with self.subTest(value=bad), self.assertLogs(level='ERROR'):
                self.assertEqual(self.min_version(bad), 9)

    def test_a_typo_is_logged_once_not_on_every_launch(self):
        with self.assertLogs(level='INFO') as logs:
            for _ in range(5):
                self.assertEqual(self.min_version('seventy-eight'), 9)
        errors = [r for r in logs.records if 'CONFIG_ERROR' in r.getMessage()]
        self.assertEqual(len(errors), 1)

    def test_the_floor_in_effect_is_logged(self):
        with self.assertLogs(level='INFO') as logs:
            self.min_version('78')
        self.assertTrue(any('min_app_version is 78' in r.getMessage() for r in logs.records))


if __name__ == '__main__':
    unittest.main()
