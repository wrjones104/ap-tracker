"""Deleting a user must take every row that belongs to them with it.

Regression cover for #331: milestone_templates had no collection on User, so
session.delete(user) raised ForeignKeyViolation on Postgres. That broke account
deletion outright, and rolled back the whole inactive-guest purge batch with it,
because the purge deletes every expired guest in one transaction.

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
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
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
