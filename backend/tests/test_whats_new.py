import os
import sys
import unittest
import json
from unittest.mock import patch

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_whats_new.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app

# These tests provide their own known changelog data (by patching the route's
# loader) so they exercise the endpoints against fixed content rather than the
# real, evolving backend/app/data/changelog.json. The fixture mirrors the
# enriched payload shape that app.changelog.enrich() produces at runtime.
FIXTURE_CHANGELOG = {
    "latest_version": "1.6.18",
    "app_latest_version": "1.6.18",
    "server_latest_version": "1.6.18",
    "app_releases": [
        {"version": "1.6.18", "component": "app", "title": "App Release", "highlights": [], "categories": {}}
    ],
    "server_releases": [
        {"version": "1.6.18", "component": "server", "title": "Server Release", "highlights": [], "categories": {}}
    ],
    "releases": [
        {"version": "1.6.18", "component": "app", "title": "App Release"},
        {"version": "1.6.18", "component": "server", "title": "Server Release"},
    ],
}


class TestWhatsNewRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        # Inject known changelog data so the tests are hermetic and don't depend
        # on the gitignored changelog.json being present on disk.
        self._changelog_patcher = patch(
            'app.routes.whats_new_routes._load_changelog_data',
            return_value=FIXTURE_CHANGELOG,
        )
        self._changelog_patcher.start()
        self.addCleanup(self._changelog_patcher.stop)

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def test_get_whats_new_all(self):
        response = self.client.get('/api/whats_new')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('latest_version', data)
        self.assertIn('app_latest_version', data)
        self.assertIn('server_latest_version', data)
        self.assertIn('releases', data)
        self.assertTrue(len(data['releases']) > 0)

    def test_get_whats_new_app_target(self):
        response = self.client.get('/api/whats_new?target=app')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertEqual(data.get('target'), 'app')
        self.assertEqual(data.get('latest_version'), data.get('app_latest_version'))
        for rel in data.get('releases', []):
            self.assertEqual(rel.get('component'), 'app')

    def test_get_whats_new_server_target(self):
        response = self.client.get('/api/whats_new?target=server')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertEqual(data.get('target'), 'server')
        self.assertEqual(data.get('latest_version'), data.get('server_latest_version'))
        for rel in data.get('releases', []):
            self.assertEqual(rel.get('component'), 'server')

    def test_get_whats_new_latest(self):
        response = self.client.get('/api/whats_new/latest')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('release', data)
        release = data['release']
        self.assertIn('version', release)
        self.assertEqual(release.get('component'), 'app')

    def test_get_whats_new_specific_version(self):
        response = self.client.get('/api/whats_new/latest?version=1.6.18&target=app')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertEqual(data['release']['version'], '1.6.18')

    def test_get_whats_new_invalid_version(self):
        response = self.client.get('/api/whats_new/latest?version=99.99.99')
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'error')
