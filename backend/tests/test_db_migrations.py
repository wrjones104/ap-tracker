import unittest
from alembic.config import Config
from sqlalchemy import create_engine, text

from backend.app.db_migrations import _find_alembic_ini, _reconcile_overlapping_heads


class TestDbMigrationsReconciliation(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.ini_path = _find_alembic_ini()
        self.assertIsNotNone(self.ini_path, "alembic.ini must be resolvable")
        self.config = Config(self.ini_path)

    def test_reconcile_overlapping_heads_prunes_ancestor(self):
        with self.engine.connect() as conn:
            # Create simulated alembic_version table
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            # Insert both descendant and ancestor revisions
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('a1c7e9f4b2d0'), ('a3f8c91d2e47')")
            )
            conn.commit()

            # Run reconciliation
            _reconcile_overlapping_heads(conn, self.config)
            conn.commit()

            remaining = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            self.assertEqual(remaining, ['a3f8c91d2e47'])

    def test_reconcile_single_head_is_noop(self):
        with self.engine.connect() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('a3f8c91d2e47')"))
            conn.commit()

            _reconcile_overlapping_heads(conn, self.config)
            conn.commit()

            remaining = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            self.assertEqual(remaining, ['a3f8c91d2e47'])

    def test_reconcile_missing_table_handles_gracefully(self):
        with self.engine.connect() as conn:
            # Table does not exist
            # Should not raise exception
            _reconcile_overlapping_heads(conn, self.config)


if __name__ == '__main__':
    unittest.main()
