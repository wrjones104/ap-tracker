"""
Schema migration on startup, for the Postgres deployments.

Local SQLite dev builds its schema straight from the models (see create_app). Postgres cannot:
it is migrated by Alembic, and until this module existed nothing ran that migration except a
person typing `alembic upgrade heads` into a shell. A database that missed the step served every
authenticated request as a 500 on a missing table, which reads from the client side as "the
backend is down" rather than "the schema is behind".
"""
import logging
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import text

# Arbitrary, but every process racing to migrate the same database must choose the same key.
_MIGRATION_LOCK_KEY = 8093124412001


def _find_alembic_ini():
    """
    Locate alembic.ini across the two layouts this package runs in.

    In the container, backend/ is copied to /app, so the package sits at /app/app and the ini is
    one level up at /app/alembic.ini. In a checkout the package is at <root>/backend/app and the
    ini is two levels up at <root>/alembic.ini.
    """
    package_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(package_dir, os.pardir, 'alembic.ini'),
        os.path.join(package_dir, os.pardir, os.pardir, 'alembic.ini'),
        os.path.join(os.getcwd(), 'alembic.ini'),
    ]
    for candidate in candidates:
        resolved = os.path.realpath(candidate)
        if os.path.isfile(resolved):
            return resolved
    return None


def upgrade_to_head(engine):
    """
    Bring the database up to the newest revision(s) before the process serves anything.

    The API and the poller boot against the same database at the same time, so the upgrade runs
    under a Postgres advisory lock. Whichever process arrives first migrates; the other blocks on
    the lock and then finds nothing left to do. Without it the two can race inside the same DDL.

    Raises on failure rather than continuing: a process serving on a schema it does not understand
    fails later, further away, and much more confusingly than one that refuses to start.
    """
    ini_path = _find_alembic_ini()
    if not ini_path:
        raise RuntimeError(
            "alembic.ini not found -- cannot verify the database schema. Looked next to the app "
            "package, one level above it, and in the working directory."
        )

    config = Config(ini_path)
    # alembic/env.py calls fileConfig() on this ini, which would otherwise tear down the logging
    # configuration the app has already installed. Honoured by the guard in env.py.
    config.attributes['configure_logger'] = False

    logging.info(f"[MIGRATE] Verifying database schema with {ini_path}...")

    # AUTOCOMMIT because an advisory lock taken this way is session-scoped: a rollback would not
    # release it, and the connection would carry the lock back into the pool still held.
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        conn.execute(text('SELECT pg_advisory_lock(:key)'), {'key': _MIGRATION_LOCK_KEY})
        try:
            command.upgrade(config, 'heads')
        finally:
            conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': _MIGRATION_LOCK_KEY})

    logging.info("[MIGRATE] Database schema is up to date.")
