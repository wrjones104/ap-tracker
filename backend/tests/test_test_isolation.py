"""
The tests must never reach a real database (see backend/tests/__init__.py).

On 25 October 2026 a run of several test files in one process emptied the dev Postgres: the
first file imported set no database of its own, so `app` bound to backend/.env's, and the next
file's setUp dropped every table. Each case runs in a fresh interpreter, because `app` binds
its engine once per process.
"""
import os
import re
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

    def test_discovery_inside_the_tests_folder_stays_off_the_real_one(self):
        # `discover -s backend/tests` imports modules by their bare names and never runs the
        # package's __init__, so each module has to name its own database.
        url = _run(
            'import unittest; '
            'unittest.defaultTestLoader.discover("backend/tests", pattern="test_hint_found_suppression.py"); '
            'import app; print(app.engine.url)',
            DATABASE_URL=REAL_DB,
        )
        self.assertTrue(url.startswith('sqlite:///'), url)

    def test_every_module_names_its_database_before_importing_app(self):
        # Whichever module a run imports first decides the database for all of them.
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        offenders = []
        for name in sorted(os.listdir(tests_dir)):
            if not (name.startswith('test_') and name.endswith('.py')):
                continue
            with open(os.path.join(tests_dir, name), encoding='utf-8') as f:
                lines = f.read().splitlines()
            first_app = next((i for i, line in enumerate(lines)
                              if re.match(r"(from app[ .]|import app\b)", line)), None)
            if first_app is None:
                continue
            named = next((i for i, line in enumerate(lines)
                          if re.match(r"os\.environ\['DATABASE_URL'\] *=", line)), None)
            if named is None or named > first_app:
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_a_real_database_can_be_asked_for_on_purpose(self):
        url = _run('import os, backend.tests; print(os.environ["DATABASE_URL"])',
                   DATABASE_URL=REAL_DB, AP_TESTS_ALLOW_REAL_DB='1')
        self.assertEqual(url, REAL_DB)


if __name__ == '__main__':
    unittest.main()
