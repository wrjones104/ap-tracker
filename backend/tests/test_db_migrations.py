import os

# Before `app` is imported, which binds its engine once per process: whichever way these tests
# are loaded, they never reach the database backend/.env names (see backend/tests/__init__.py).
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'test_db_migrations.db'))

import logging
import unittest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.db_migrations import _find_alembic_ini, _reconcile_overlapping_heads
from app.models import DatapackageCache, NotifiedHint, NotifiedItem


class TestDbMigrationsReconciliation(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.ini_path = _find_alembic_ini()
        self.assertIsNotNone(self.ini_path, "alembic.ini must be resolvable")
        self.config = Config(self.ini_path)
        self.script = ScriptDirectory.from_config(self.config)

    def test_reconcile_overlapping_heads_prunes_ancestor(self):
        # Resolve head and immediate parent dynamically from the migration script graph
        head_rev = self.script.get_heads()[0]
        parent_rev = self.script.get_revision(head_rev).down_revision
        self.assertIsInstance(parent_rev, str)

        with self.engine.connect() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:parent), (:head)"),
                {"parent": parent_rev, "head": head_rev},
            )
            conn.commit()

            _reconcile_overlapping_heads(conn, self.config)
            conn.commit()

            remaining = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            self.assertEqual(remaining, [head_rev])

    def test_reconcile_with_unresolvable_orphan_row(self):
        # Even with an unresolvable revision present, valid overlapping ancestors must still be pruned
        head_rev = self.script.get_heads()[0]
        parent_rev = self.script.get_revision(head_rev).down_revision

        with self.engine.connect() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:parent), (:head), ('deadbeefcafe')"),
                {"parent": parent_rev, "head": head_rev},
            )
            conn.commit()

            with self.assertLogs(level=logging.WARNING) as log:
                _reconcile_overlapping_heads(conn, self.config)
                conn.commit()

            self.assertTrue(any("Cannot resolve applied revision deadbeefcafe" in msg for msg in log.output))

            remaining = set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all())
            self.assertEqual(remaining, {head_rev, 'deadbeefcafe'})

    def test_reconcile_sibling_heads_preserves_both(self):
        # Legitimate sibling heads sharing a common ancestor but not in linear descent must survive untouched
        # 6aa084c2474f (ios platform) and a971160f9c05 (filler trap) both branched from fdb86a1c81bc
        sibling_a = '6aa084c2474f'
        sibling_b = 'a971160f9c05'

        with self.engine.connect() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:a), (:b)"),
                {"a": sibling_a, "b": sibling_b},
            )
            conn.commit()

            _reconcile_overlapping_heads(conn, self.config)
            conn.commit()

            remaining = set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all())
            self.assertEqual(remaining, {sibling_a, sibling_b})

    def test_reconcile_single_head_is_noop(self):
        head_rev = self.script.get_heads()[0]
        with self.engine.connect() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:head)"), {"head": head_rev})
            conn.commit()

            _reconcile_overlapping_heads(conn, self.config)
            conn.commit()

            remaining = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            self.assertEqual(remaining, [head_rev])

    def test_reconcile_missing_table_handles_gracefully(self):
        with self.engine.connect() as conn:
            # Table does not exist - verify debug log emitted
            with self.assertLogs(level=logging.DEBUG) as log:
                _reconcile_overlapping_heads(conn, self.config)

            self.assertTrue(any("No alembic_version table to reconcile" in msg for msg in log.output))


class TestIndexInvariants(unittest.TestCase):
    """Schema facts the index migrations rest on.

    c7a2e5b48f16 dropped ix_datapackage_cache_checksum because the covering
    index leads with checksum, so a lookup on checksum alone is served without
    it. That is a property of column order, not of the drop, and nothing else
    would notice if a later change broke it -- the index would simply stop being
    used and every checksum lookup would fall back to a sequential scan of a
    2 GB table.

    The room_id assertions guard the opposite decision: both are redundant in
    the same structural sense and both were deliberately kept, because the
    janitor reads SELECT DISTINCT room_id off each of them every run. See #534.
    """

    def test_checksum_leads_the_covering_index(self):
        pk = [c.name for c in DatapackageCache.__table__.primary_key.columns]
        self.assertEqual(
            pk[0], 'checksum',
            "c7a2e5b48f16 dropped the standalone checksum index on the strength "
            "of checksum leading the composite identity; reordering these "
            "columns silently un-indexes every checksum lookup"
        )

    def test_checksum_has_no_standalone_index(self):
        names = {i.name for i in DatapackageCache.__table__.indexes}
        self.assertNotIn('ix_datapackage_cache_checksum', names)
        # game keeps its own: nothing else leads with game.
        self.assertIn('ix_datapackage_cache_game', names)

    def test_history_tables_keep_their_room_id_index(self):
        for model, table in ((NotifiedItem, 'notified_items'),
                             (NotifiedHint, 'notified_hints')):
            with self.subTest(table=table):
                self.assertIn(
                    'ix_%s_room_id' % table,
                    {i.name for i in model.__table__.indexes},
                    "purge_orphaned_room_events scans this narrow index for "
                    "DISTINCT room_id; the wider indexes that also lead with "
                    "room_id answer it for twice the pages (#534)"
                )


if __name__ == '__main__':
    unittest.main()
