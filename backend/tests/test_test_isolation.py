"""
The tests must never reach a real database (see backend/tests/__init__.py).

On 25 October 2026 a run of several test files in one process emptied the dev Postgres: the
first file imported set no database of its own, so `app` bound to backend/.env's, and the next
file's setUp dropped every table. Each case runs in a fresh interpreter, because `app` binds
its engine once per process.
"""
import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
REAL_DB = 'postgresql://user:secret@localhost:5432/ap_tracker_real'


def _run(code, **env):
    full_env = dict(os.environ)
    full_env.pop('AP_TESTS_ALLOW_REAL_DB', None)
    full_env['PYTHONPATH'] = os.pathsep.join([os.path.join(REPO_ROOT, 'backend'), REPO_ROOT])
    full_env.update(env)
    result = subprocess.run([sys.executable, '-c', code], cwd=REPO_ROOT, env=full_env,
                            capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(result.stderr[-2000:])
    return result.stdout.strip().splitlines()[-1]


class TestTestsNeverTouchARealDatabase(unittest.TestCase):

    def test_a_real_database_in_the_environment_is_replaced(self):
        url = _run('import os, backend.tests; print(os.environ["DATABASE_URL"])', DATABASE_URL=REAL_DB)
        self.assertTrue(url.startswith('sqlite:///'), url)

    def test_a_first_import_without_its_own_database_stays_off_the_real_one(self):
        # What emptied the dev database: this module sets no database, then another's setUp
        # drops every table on whatever `app` bound to.
        url = _run('import backend.tests.test_push_message, app; print(app.engine.url)', DATABASE_URL=REAL_DB)
        self.assertTrue(url.startswith('sqlite:///'), url)

    def test_a_module_that_names_its_database_gets_it(self):
        url = _run('import backend.tests.test_push_history, app; print(app.engine.url)', DATABASE_URL=REAL_DB)
        self.assertTrue(url.endswith('test_push_history.db'), url)

    def test_a_real_database_can_be_asked_for_on_purpose(self):
        url = _run('import os, backend.tests; print(os.environ["DATABASE_URL"])',
                   DATABASE_URL=REAL_DB, AP_TESTS_ALLOW_REAL_DB='1')
        self.assertEqual(url, REAL_DB)


if __name__ == '__main__':
    unittest.main()
