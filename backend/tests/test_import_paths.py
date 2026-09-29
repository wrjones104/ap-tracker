"""
Guard: test modules import the app through `app.*`, never `backend.app.*`.

The routes import `app`, so a test that imports `backend.app` loads the package
a second time and gets a second engine. On Linux that engine keeps reading the
previous test's deleted SQLite file, so route tests silently run against stale
data, while the same tests pass on Windows. See #375 and the note in
test_slot_track_mode.py.

Importing any submodule counts: `backend.app.db_migrations` runs
`backend/app/__init__.py` first, which creates the second engine. So there are
no exceptions.

Checked on the syntax tree rather than the text, so every import form is caught
(`from backend import app`, `import os, backend.app`, string targets such as
`patch('backend.app...')` or `importlib.import_module('backend.app')`) and a
docstring that merely mentions the old form is not.
"""
import ast
import os
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
# This file has to spell the pattern out, so it is the one file not scanned.
THIS_FILE = os.path.basename(__file__)


def _is_backend_app(name):
    return name == 'backend.app' or name.startswith('backend.app.')


def backend_app_refs(source):
    """Every `backend.app` reference in imports and string call args (patch targets)."""
    refs = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            refs += [a.name for a in node.names if _is_backend_app(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if _is_backend_app(node.module):
                refs.append(node.module)
            elif node.module == 'backend':
                refs += [f'backend.{a.name}' for a in node.names if a.name == 'app']
        elif isinstance(node, ast.Call):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _is_backend_app(arg.value):
                    refs.append(arg.value)
    return refs


class TestImportPaths(unittest.TestCase):
    def test_no_test_module_imports_backend_app(self):
        offenders = []
        for name in sorted(os.listdir(TESTS_DIR)):
            if not (name.startswith('test_') and name.endswith('.py')) or name == THIS_FILE:
                continue
            with open(os.path.join(TESTS_DIR, name), encoding='utf-8') as f:
                refs = backend_app_refs(f.read())
            if refs:
                offenders.append(f"{name}: {', '.join(sorted(set(refs)))}")
        self.assertEqual(
            offenders, [],
            "Import through `app.*`, not `backend.app.*` (patch targets too); see #375.",
        )

    def test_the_guard_catches_every_import_form(self):
        caught = [
            "from backend.app import create_app",
            "from backend.app.models import User",
            "from backend import app",
            "import os, backend.app",
            "import backend.app.poller as poller",
            "patch('backend.app.auth.requests.post')",
            "importlib.import_module('backend.app')",
        ]
        ignored = [
            '"""\nfrom backend.app import x is the old form.\n"""',
            "# from backend.app import x",
            "from app import create_app",
            "from backend import tests",
            "patch('app.auth.requests.post')",
        ]
        for source in caught:
            self.assertTrue(backend_app_refs(source), source)
        for source in ignored:
            self.assertEqual(backend_app_refs(source), [], source)


if __name__ == '__main__':
    unittest.main()
