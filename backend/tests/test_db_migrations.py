import os

# Before `app` is imported, which binds its engine once per process: whichever way these tests
# are loaded, they never reach the database backend/.env names (see backend/tests/__init__.py).
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'test_db_migrations.db'))

import logging
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

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
        # models.py only, which is the schema SQLite and any fresh database
        # build from. Production has no primary key on this table at all -- it
        # enforces the triple with _checksum_entity_uc, see b7f4e2c9a1d3 -- so
        # the real guard there is the covering-index check the migration runs
        # against the live catalog, exercised in
        # TestDropRedundantChecksumIndexMigration below.
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
        # By shape as well as by name, so that re-adding the same index under a
        # name of its own in __table_args__ does not slip past.
        columns = {tuple(c.name for c in i.columns)
                   for i in DatapackageCache.__table__.indexes}
        self.assertNotIn(('checksum',), columns)
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


class _FakeResult:
    def __init__(self, row=None, scalar_value=None):
        self._row = row
        self._scalar_value = scalar_value

    def first(self):
        return self._row

    def scalar(self):
        return self._scalar_value


class _FakePostgresBind:
    """Answers the two catalog queries c7a2e5b48f16 asks, and refuses others.

    index_state is what the catalog reports for the index: None absent, True
    valid, False present but invalid. covering is the name of an index leading
    with checksum, or None for a schema that has none.
    """

    def __init__(self, index_state, covering='_checksum_entity_uc'):
        self.dialect = SimpleNamespace(name='postgresql')
        self.index_state = index_state
        self.covering = covering

    def execute(self, clause, params=None):
        sql = ' '.join(str(clause).split())
        if 'SELECT i.indisvalid FROM pg_index' in sql:
            row = None if self.index_state is None else (self.index_state,)
            return _FakeResult(row=row)
        if sql.startswith('SELECT c.relname'):
            return _FakeResult(scalar_value=self.covering)
        raise AssertionError('unexpected catalog query: %s' % sql)


class TestDropRedundantChecksumIndexMigration(unittest.TestCase):
    """The branches of c7a2e5b48f16, which no other test reaches.

    Its whole body is Postgres-only, and the suite runs on SQLite, so the
    statements it would issue are captured against a fake bind rather than
    executed. That is enough to pin the decisions, which is where this migration
    went wrong on its first pass: it asked whether the index was *valid* when it
    needed to ask whether it was *present*, and so read an interrupted
    DROP INDEX CONCURRENTLY as a finished one.
    """

    INDEX = 'ix_datapackage_cache_checksum'

    def setUp(self):
        config = Config(_find_alembic_ini())
        script = ScriptDirectory.from_config(config)
        self.module = script.get_revision('c7a2e5b48f16').module

    def _run(self, fn, bind, fail_on=None):
        """Run upgrade/downgrade, returning [(statement, inside_autocommit)]."""
        statements = []
        depth = [0]

        @contextmanager
        def autocommit_block():
            depth[0] += 1
            try:
                yield
            finally:
                depth[0] -= 1

        def execute(sql):
            statements.append((str(sql), depth[0] > 0))
            if fail_on and fail_on in str(sql):
                raise RuntimeError('canceling statement due to lock timeout')

        fake_op = SimpleNamespace(
            get_bind=lambda: bind,
            get_context=lambda: SimpleNamespace(autocommit_block=autocommit_block),
            execute=execute,
        )
        with patch.object(self.module, 'op', fake_op):
            fn()
        return statements

    def _ddl(self, statements):
        return [s for s, _ in statements
                if not s.startswith(('SET ', 'RESET '))]

    # --- nothing to do ----------------------------------------------------
    def test_upgrade_does_nothing_on_sqlite(self):
        bind = SimpleNamespace(dialect=SimpleNamespace(name='sqlite'))
        self.assertEqual(self._run(self.module.upgrade, bind), [])

    def test_upgrade_does_nothing_when_the_index_is_absent(self):
        bind = _FakePostgresBind(index_state=None)
        self.assertEqual(self._run(self.module.upgrade, bind), [])

    # --- the drop ---------------------------------------------------------
    def test_upgrade_drops_concurrently_under_a_timeout(self):
        bind = _FakePostgresBind(index_state=True)
        statements = self._run(self.module.upgrade, bind)
        self.assertEqual(
            self._ddl(statements),
            ['DROP INDEX CONCURRENTLY IF EXISTS %s' % self.INDEX],
            "a plain DROP INDEX would take ACCESS EXCLUSIVE on a table the "
            "poller writes to throughout every room setup"
        )
        self.assertTrue(all(inside for _, inside in statements),
                        "CONCURRENTLY cannot run inside a transaction")
        kinds = [s.split()[0] for s, _ in statements]
        self.assertEqual(kinds[0], 'SET', "the drop waits on lockers unbounded")
        self.assertEqual(kinds[-1], 'RESET')

    def test_upgrade_finishes_a_drop_that_was_interrupted(self):
        # The regression this class exists for. An interrupted
        # DROP INDEX CONCURRENTLY leaves the index present and invalid, holding
        # all of its disk, with the revision unstamped -- so the retry has to
        # finish the job rather than read it as already done. No covering index
        # is offered here: an invalid index answers nothing, so finishing its
        # drop needs no such check.
        bind = _FakePostgresBind(index_state=False, covering=None)
        statements = self._run(self.module.upgrade, bind)
        self.assertEqual(
            self._ddl(statements),
            ['DROP INDEX CONCURRENTLY IF EXISTS %s' % self.INDEX]
        )

    def test_upgrade_refuses_when_nothing_else_leads_with_checksum(self):
        bind = _FakePostgresBind(index_state=True, covering=None)
        with self.assertLogs(level=logging.WARNING) as log:
            statements = self._run(self.module.upgrade, bind)
        self.assertEqual(statements, [])
        self.assertTrue(any(
            'No unique index leads with datapackage_cache.checksum' in m
            for m in log.output))

    def test_a_failed_drop_still_resets_the_timeout(self):
        bind = _FakePostgresBind(index_state=True)
        with self.assertRaises(RuntimeError):
            self._run(self.module.upgrade, bind, fail_on='DROP INDEX')
        # Re-run cleanly to read the statement list; the point above is only
        # that the exception propagated rather than being swallowed.
        statements = self._run(self.module.upgrade, bind)
        self.assertIn('RESET lock_timeout', [s for s, _ in statements])

    # --- the rebuild ------------------------------------------------------
    def test_downgrade_does_nothing_when_the_index_is_valid(self):
        bind = _FakePostgresBind(index_state=True)
        self.assertEqual(self._run(self.module.downgrade, bind), [])

    def test_downgrade_rebuilds_concurrently(self):
        bind = _FakePostgresBind(index_state=None)
        statements = self._run(self.module.downgrade, bind)
        self.assertEqual(
            self._ddl(statements),
            ['CREATE INDEX CONCURRENTLY %s ON datapackage_cache (checksum)'
             % self.INDEX]
        )
        self.assertTrue(all(inside for _, inside in statements))

    def test_downgrade_clears_an_invalid_index_concurrently_first(self):
        bind = _FakePostgresBind(index_state=False)
        statements = self._run(self.module.downgrade, bind)
        self.assertEqual(
            self._ddl(statements),
            [
                'DROP INDEX CONCURRENTLY IF EXISTS %s' % self.INDEX,
                'CREATE INDEX CONCURRENTLY %s ON datapackage_cache (checksum)'
                % self.INDEX,
            ],
            "the name is taken, and clearing it with a plain DROP INDEX would "
            "take the lock this migration avoids everywhere else"
        )


if __name__ == '__main__':
    unittest.main()
