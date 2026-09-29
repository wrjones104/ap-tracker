"""
Guard: test modules import the app through `app.*`, never `backend.app.*`.

The routes import `app`, so a test that imports `backend.app` loads the package
a second time and gets a second engine. On Linux that engine keeps reading the
previous test's deleted SQLite file, so route tests silently run against stale
data, while the same tests pass on Windows. See #375 and the note in
test_slot_track_mode.py.
"""
import os
import re
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# test_db_migrations.py imports only a pure helper that opens no engine.
ALLOWED = {'test_db_migrations.py'}

BACKEND_APP_IMPORT = re.compile(r"^\s*(from\s+backend\.app\b|import\s+backend\.app\b)|['\"]backend\.app\.", re.MULTILINE)


class TestImportPaths(unittest.TestCase):
    def test_no_test_module_imports_backend_app(self):
        offenders = []
        for name in sorted(os.listdir(TESTS_DIR)):
            if not (name.startswith('test_') and name.endswith('.py')) or name in ALLOWED:
                continue
            with open(os.path.join(TESTS_DIR, name), encoding='utf-8') as f:
                source = f.read()
            if BACKEND_APP_IMPORT.search(source):
                offenders.append(name)
        self.assertEqual(
            offenders, [],
            "Import through `app.*`, not `backend.app.*` (patch targets too); see #375.",
        )


if __name__ == '__main__':
    unittest.main()
