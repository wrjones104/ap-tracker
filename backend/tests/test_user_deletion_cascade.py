"""Deleting a user must take every row that belongs to them with it.

Regression cover for #331: milestone_templates had no collection on User, so
session.delete(user) raised ForeignKeyViolation on Postgres. That broke account
deletion outright, and took the daily janitor down with it, because db_run_cleanup
deletes every stale guest and every orphaned room in one transaction.

Both guest purges are covered here. db_run_cleanup in poller.py is the one that
runs in production; purge_inactive_guest_accounts in retention_service has no
caller today, which is #334, so its tests guard the shape rather than live
behaviour.

These tests only mean anything with foreign keys enforced. SQLite leaves them
off by default, which is why the original suite passed while production failed,
so the app now issues PRAGMA foreign_keys=ON and one test here guards that.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_user_delete.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text

from app import create_app, Session, engine
from app.models import (
    Base,
    CheeseDismissedTracker,
    Device,
    MilestoneTemplate,
    MilestoneTemplateItem,
    ThresholdGroup,
    ThresholdGroupItem,
    TrackedRoom,
    User,
    UserIgnoreItem,
    UserRoomSubscription,
    UserTrackedSlot,
    UserWhitelistItem,
)
from app.services.retention_service import purge_inactive_guest_accounts


def _make_token(app, user_id):
    """A JWT matching the token_required format."""
    import jwt as pyjwt
    import uuid
    from datetime import timezone
    payload = {
        'user_id': user_id,
        'jti': str(uuid.uuid4()),
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


class TestUserDeletionCascade(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = self.app.test_client()

    def tearDown(self):
        Session.remove()
        # Windows will not unlink a file the pool still holds open, so without
        # this the removal below fails silently and leaves the database and its
        # write-ahead log behind.
        engine.dispose()
        for path in (TEST_DB_PATH, f'{TEST_DB_PATH}-wal', f'{TEST_DB_PATH}-shm'):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_user(self, session, discord_id, is_guest=False, last_activity=None):
        user = User(
            discord_id=discord_id,
            discord_username=discord_id,
            is_guest=is_guest,
            last_activity=last_activity or datetime.utcnow(),
        )
        session.add(user)
        session.flush()
        return user

    def _add_template(self, session, user, name='Progression'):
        """A milestone template with an item. The row that used to block deletion."""
        template = MilestoneTemplate(
            user_id=user.id,
            game_name='A Link to the Past',
            name=name,
        )
        session.add(template)
        session.flush()
        session.add(MilestoneTemplateItem(
            template_id=template.id,
            item_name='Progressive Sword',
            quantity=4,
        ))
        session.flush()
        return template

    def _add_full_library(self, session, user, room_id):
        """One of everything else a user owns, down to a threshold group item."""
        room = TrackedRoom(room_id=room_id)
        session.add(room)
        session.flush()

        session.add(UserRoomSubscription(
            user_id=user.id,
            room_id=room.id,
            alias='My Room',
        ))
        session.flush()

        slot = UserTrackedSlot(user_id=user.id, room_id=room.id, slot_id=1)
        session.add(slot)
        session.flush()

        group = ThresholdGroup(user_tracked_slot_id=slot.id, name='Swords')
        session.add(group)
        session.flush()
        session.add(ThresholdGroupItem(
            group_id=group.id,
            item_name='Progressive Sword',
            quantity=2,
        ))

        session.add(Device(fcm_token=f'token-{room_id}', user_id=user.id))
        session.add(UserIgnoreItem(user_id=user.id, item_name='Rupees'))
        session.add(UserWhitelistItem(user_id=user.id, item_name='Boss Key'))
        session.add(CheeseDismissedTracker(
            user_id=user.id,
            cheese_tracker_id=f'ct-{room_id}',
        ))
        session.flush()
        return room

    def _counts(self, session, user_id):
        return {
            'templates': session.query(MilestoneTemplate).filter_by(user_id=user_id).count(),
            'template_items': session.query(MilestoneTemplateItem).join(
                MilestoneTemplate,
                MilestoneTemplateItem.template_id == MilestoneTemplate.id,
            ).filter(MilestoneTemplate.user_id == user_id).count(),
            'subscriptions': session.query(UserRoomSubscription).filter_by(user_id=user_id).count(),
            'slots': session.query(UserTrackedSlot).filter_by(user_id=user_id).count(),
            'devices': session.query(Device).filter_by(user_id=user_id).count(),
            'ignores': session.query(UserIgnoreItem).filter_by(user_id=user_id).count(),
            'whitelists': session.query(UserWhitelistItem).filter_by(user_id=user_id).count(),
            'dismissed': session.query(CheeseDismissedTracker).filter_by(user_id=user_id).count(),
        }

    # ------------------------------------------------------------------
    # Structural guards. The behavioural tests below cannot tell the two
    # halves of the fix apart: SQLite builds its schema from models.py, so
    # the column-level cascade alone carries them even with the ORM
    # collection gone. These assert on each half directly.
    # ------------------------------------------------------------------

    def test_every_user_foreign_key_has_a_cascading_collection(self):
        """The assertion that would have caught #331 before it shipped."""
        from sqlalchemy import inspect as sa_inspect

        collected = {
            rel.mapper.class_.__tablename__
            for rel in sa_inspect(User).relationships
            if 'delete-orphan' in rel.cascade
        }

        # Reached through UserRoomSubscription.tracked_slots rather than from
        # User directly. See the comment on the collections in models.py.
        expected_indirect = {'user_tracked_slots'}

        missing = {
            table.name
            for table in Base.metadata.tables.values()
            for fk in table.foreign_keys
            if fk.column.table.name == 'users'
            and table.name not in collected
            and table.name not in expected_indirect
        }

        self.assertEqual(
            missing, set(),
            f"tables with a users.id foreign key and no delete-orphan collection "
            f"on User: {sorted(missing)}. Account deletion raises "
            f"ForeignKeyViolation on Postgres. See #331.",
        )

    def test_every_owned_foreign_key_cascades_in_the_schema(self):
        """The database-level backstop, asserted on the metadata rather than a delete."""
        # tracked_rooms is shared between everyone tracking a room, so those keys
        # stay NO ACTION on purpose and the room delete path remains ORM-only.
        owned_parents = {
            'users', 'user_room_subscriptions', 'threshold_groups', 'milestone_templates',
        }

        not_cascading = {
            f"{table.name}.{','.join(c.name for c in fk.constraint.columns)}"
            f" -> {fk.column.table.name}"
            for table in Base.metadata.tables.values()
            for fk in table.foreign_keys
            if fk.column.table.name in owned_parents
            and (fk.ondelete or '').upper() != 'CASCADE'
        }

        self.assertEqual(
            not_cascading, set(),
            f"foreign keys on the user-owned subtree without ON DELETE CASCADE: "
            f"{sorted(not_cascading)}. A raw DELETE stops here. See #331.",
        )

    # ------------------------------------------------------------------
    # The guard: these tests are worthless without it
    # ------------------------------------------------------------------

    def test_sqlite_enforces_foreign_keys(self):
        session = Session()
        try:
            enabled = session.execute(text('PRAGMA foreign_keys')).scalar()
            self.assertEqual(
                enabled, 1,
                "SQLite must enforce foreign keys or cascade gaps pass here and "
                "fail on Postgres. See #331.",
            )
        finally:
            Session.remove()

    # ------------------------------------------------------------------
    # ORM deletion
    # ------------------------------------------------------------------

    def test_delete_user_owning_a_milestone_template(self):
        session = Session()
        try:
            user = self._make_user(session, 'template_owner')
            self._add_template(session, user)
            session.commit()
            user_id = user.id

            session.delete(user)
            session.commit()

            self.assertIsNone(session.get(User, user_id))
            self.assertEqual(
                session.query(MilestoneTemplate).filter_by(user_id=user_id).count(), 0
            )
            self.assertEqual(session.query(MilestoneTemplateItem).count(), 0)
        finally:
            Session.remove()

    def test_delete_user_clears_every_owned_table(self):
        session = Session()
        try:
            user = self._make_user(session, 'full_library')
            self._add_template(session, user)
            self._add_full_library(session, user, 'room-full')
            session.commit()
            user_id = user.id

            populated = self._counts(session, user_id)
            self.assertTrue(
                all(v > 0 for v in populated.values()),
                f"fixture did not populate every table: {populated}",
            )

            session.delete(user)
            session.commit()

            remaining = self._counts(session, user_id)
            self.assertTrue(
                all(v == 0 for v in remaining.values()),
                f"rows survived the delete: {remaining}",
            )
            self.assertEqual(session.query(ThresholdGroup).count(), 0)
            self.assertEqual(session.query(ThresholdGroupItem).count(), 0)
            # The room itself is shared, so it stays.
            self.assertEqual(session.query(TrackedRoom).count(), 1)
        finally:
            Session.remove()

    def test_delete_user_leaves_another_users_rows_alone(self):
        session = Session()
        try:
            keeper = self._make_user(session, 'keeper')
            self._add_template(session, keeper)
            self._add_full_library(session, keeper, 'room-keeper')

            doomed = self._make_user(session, 'doomed')
            self._add_template(session, doomed)
            self._add_full_library(session, doomed, 'room-doomed')
            session.commit()
            keeper_id, doomed_id = keeper.id, doomed.id

            before = self._counts(session, keeper_id)
            session.delete(doomed)
            session.commit()

            self.assertIsNone(session.get(User, doomed_id))
            self.assertEqual(self._counts(session, keeper_id), before)
        finally:
            Session.remove()

    # ------------------------------------------------------------------
    # The account deletion endpoint
    # ------------------------------------------------------------------

    def test_delete_account_endpoint_succeeds_for_a_template_owner(self):
        session = Session()
        try:
            user = self._make_user(session, 'api_deleter')
            self._add_template(session, user)
            self._add_full_library(session, user, 'room-api')
            session.commit()
            user_id = user.id
        finally:
            Session.remove()

        token = _make_token(self.app, user_id)
        response = self.client.delete(
            '/users/me', headers={'Authorization': f'Bearer {token}'}
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

        session = Session()
        try:
            self.assertIsNone(session.get(User, user_id))
            self.assertEqual(
                session.query(MilestoneTemplate).filter_by(user_id=user_id).count(), 0
            )
        finally:
            Session.remove()

    # ------------------------------------------------------------------
    # The guest purge
    # ------------------------------------------------------------------

    def test_guest_purge_removes_a_template_owning_guest(self):
        stale = datetime.utcnow() - timedelta(days=200)
        session = Session()
        try:
            guest = self._make_user(session, 'stale_guest', is_guest=True, last_activity=stale)
            self._add_template(session, guest)
            session.commit()
        finally:
            Session.remove()

        result = purge_inactive_guest_accounts(inactivity_days=90)
        self.assertEqual(result['purged_guests'], 1)

        session = Session()
        try:
            self.assertEqual(session.query(User).count(), 0)
            self.assertEqual(session.query(MilestoneTemplate).count(), 0)
        finally:
            Session.remove()

    def test_janitor_cleanup_survives_a_template_owning_guest(self):
        """db_run_cleanup is the purge that actually runs, on the supervisor's daily tick.

        It deletes orphaned rooms and stale guests in one transaction and commits
        once, so a single blocked guest used to roll back the room cleanup too.
        """
        from app.poller import db_run_cleanup

        stale = datetime.utcnow() - timedelta(days=60)
        session = Session()
        try:
            owner = self._make_user(session, 'janitor_owner', is_guest=True, last_activity=stale)
            self._add_template(session, owner)
            self._add_full_library(session, owner, 'room-janitor')

            self._make_user(session, 'janitor_plain', is_guest=True, last_activity=stale)
            self._make_user(session, 'janitor_active', is_guest=True)

            # An orphaned room, cleaned up in the same transaction as the guests.
            session.add(TrackedRoom(room_id='room-orphan', last_successful_poll=stale))
            session.commit()
        finally:
            Session.remove()

        db_run_cleanup()

        session = Session()
        try:
            survivors = {u.discord_id for u in session.query(User).all()}
            self.assertEqual(survivors, {'janitor_active'})
            self.assertEqual(session.query(MilestoneTemplate).count(), 0)
            self.assertEqual(session.query(UserTrackedSlot).count(), 0)
            rooms = {r.room_id for r in session.query(TrackedRoom).all()}
            self.assertNotIn(
                'room-orphan', rooms,
                "the orphaned room survived, so the guest delete took the room "
                "cleanup down with it",
            )
        finally:
            Session.remove()

    def test_guest_purge_batch_is_not_lost_to_one_template_owner(self):
        """The batch commits once, so one blocked guest used to roll back the rest."""
        stale = datetime.utcnow() - timedelta(days=200)
        session = Session()
        try:
            owner = self._make_user(session, 'stale_owner', is_guest=True, last_activity=stale)
            self._add_template(session, owner)
            self._add_full_library(session, owner, 'room-owner')

            for i in range(3):
                self._make_user(session, f'stale_plain_{i}', is_guest=True, last_activity=stale)

            self._make_user(session, 'active_guest', is_guest=True)
            self._make_user(session, 'real_account', is_guest=False, last_activity=stale)
            session.commit()
        finally:
            Session.remove()

        result = purge_inactive_guest_accounts(inactivity_days=90)
        self.assertEqual(result['purged_guests'], 4)

        session = Session()
        try:
            survivors = {u.discord_id for u in session.query(User).all()}
            self.assertEqual(survivors, {'active_guest', 'real_account'})
            self.assertEqual(session.query(MilestoneTemplate).count(), 0)
            self.assertEqual(session.query(UserTrackedSlot).count(), 0)
        finally:
            Session.remove()


if __name__ == '__main__':
    unittest.main()
