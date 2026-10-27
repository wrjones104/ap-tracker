"""
Keeps every test off a real database.

Each test module points DATABASE_URL at its own throwaway SQLite file before importing `app`,
and many of them drop and recreate every table in setUp. But `app` binds its engine once per
process, when it is first imported, and app/__init__.py loads backend/.env, whose DATABASE_URL
is the dev Postgres (and, in the server image, prod's). So when several test files ran in one
process and the first one imported did not set its own database, every later setUp dropped and
recreated the real tables. That emptied the dev database on 25 October 2026.

This package runs before any test module. Unless the environment already names a SQLite
database, or AP_TESTS_ALLOW_REAL_DB=1 asks for a real one on purpose, it points DATABASE_URL at
a throwaway SQLite file; load_dotenv leaves a variable that is already set alone. A test module
that names its own database still gets it.
"""
import os

if (not os.environ.get('DATABASE_URL', '').startswith('sqlite')
        and os.environ.get('AP_TESTS_ALLOW_REAL_DB') != '1'):
    os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', 'test_default.db'))
