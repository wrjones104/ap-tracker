"""
Tests for upgrading a guest account to a Discord account.

The contract the client depends on: presenting the guest's own JWT on
/auth/callback upgrades that account in place, so the rooms, slots and history
hanging off it survive the upgrade. Without that header the endpoint has no way
to know a guest is involved and signs the user into a separate Discord account,
which is how a guest's rooms end up stranded. See #324.
"""
import os
import unittest
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import jwt as pyjwt

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_guest_upgrade.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='  # Valid Fernet key

from backend.app import create_app, Session, engine
from backend.app.models import Base, User, TrackedRoom, UserRoomSubscription

REDIRECT_URI = 'com.jones.aptracker:/oauth2redirect'
DISCORD_ID = '999'


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class GuestUpgradeTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['DISCORD_REDIRECT_URI'] = REDIRECT_URI
        self.app.config['DISCORD_TOKEN_URL'] = 'https://discord.test/token'
        self.app.config['DISCORD_CLIENT_ID'] = 'cid'
        self.app.config['DISCORD_CLIENT_SECRET'] = 'secret'
        self.app.config['DISCORD_API_BASE_URL'] = 'https://discord.test/api'
        self.app_context = self.app.app_context()
        self.app_context.push()

        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

        self.session = Session()

    def tearDown(self):
        self.session.close()
        Session.remove()
        engine.dispose()
        self.app_context.pop()
        _remove_test_db()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        _remove_test_db()

    def make_guest_with_a_room(self):
        """A guest who has been using the app: one room, one subscription."""
        guest = User(is_guest=True, guest_uuid=str(uuid_lib.uuid4()))
        self.session.add(guest)
        self.session.flush()

        room = TrackedRoom(room_id='guest_room_uuid', hostname='archipelago.gg')
        self.session.add(room)
        self.session.flush()

        self.session.add(UserRoomSubscription(
            user_id=guest.id, room_id=room.id, alias='Room I Added As A Guest'
        ))
        self.session.commit()
        return guest.id

    def token_for(self, user_id):
        return pyjwt.encode(
            {
                'user_id': user_id,
                'iat': datetime.now(timezone.utc),
                'exp': datetime.now(timezone.utc) + timedelta(days=1),
                'jti': str(uuid_lib.uuid4()),
                'type': 'access',
            },
            self.app.config['SECRET_KEY'],
            algorithm='HS256',
        )

    def callback(self, guest_token=None, discord_id=DISCORD_ID):
        """POST /auth/callback with Discord's two calls mocked out."""
        headers = {}
        if guest_token is not None:
            headers['Authorization'] = f'Bearer {guest_token}'

        token_resp = MagicMock(ok=True)
        token_resp.json.return_value = {'access_token': 'discord_access'}
        me_resp = MagicMock(ok=True)
        me_resp.json.return_value = {'id': discord_id, 'username': 'realuser', 'avatar': None}

        with patch('backend.app.auth.requests.post', return_value=token_resp), \
             patch('backend.app.auth.requests.get', return_value=me_resp):
            return self.app.test_client().post(
                '/auth/callback',
                json={'code': 'c', 'redirect_uri': REDIRECT_URI, 'code_verifier': 'v'},
                headers=headers,
            )


class TestGuestUpgrade(GuestUpgradeTestBase):

    def test_guest_token_upgrades_in_place_and_keeps_the_rooms(self):
        guest_id = self.make_guest_with_a_room()

        resp = self.callback(guest_token=self.token_for(guest_id))
        self.assertEqual(resp.status_code, 200)

        fresh = Session()
        try:
            upgraded = fresh.query(User).get(guest_id)
            self.assertFalse(upgraded.is_guest, "the guest row itself becomes the Discord user")
            self.assertEqual(upgraded.discord_id, DISCORD_ID)

            self.assertEqual(
                fresh.query(UserRoomSubscription).filter_by(user_id=guest_id).count(), 1,
                "the room the user added as a guest comes with them",
            )
            self.assertEqual(
                fresh.query(User).count(), 1,
                "no second account is created",
            )
        finally:
            fresh.close()

    def test_the_returned_token_addresses_the_upgraded_account(self):
        """The client swaps its guest token for this one, so it has to be the same user."""
        guest_id = self.make_guest_with_a_room()

        resp = self.callback(guest_token=self.token_for(guest_id))
        payload = pyjwt.decode(
            resp.get_json()['token'], self.app.config['SECRET_KEY'], algorithms=['HS256']
        )
        self.assertEqual(payload['user_id'], guest_id)

    def test_conflict_leaves_the_guest_account_alone(self):
        """
        The Discord account already belongs to somebody. Nothing merges two
        populated accounts, so the guest must come through untouched -- the app
        restores its stashed token and carries on.
        """
        existing = User(discord_id=DISCORD_ID, discord_username='realuser', is_guest=False)
        self.session.add(existing)
        self.session.commit()
        guest_id = self.make_guest_with_a_room()

        resp = self.callback(guest_token=self.token_for(guest_id))

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()['error'], 'account_conflict')

        fresh = Session()
        try:
            guest = fresh.query(User).get(guest_id)
            self.assertTrue(guest.is_guest)
            self.assertIsNone(guest.discord_id)
            self.assertEqual(
                fresh.query(UserRoomSubscription).filter_by(user_id=guest_id).count(), 1
            )
        finally:
            fresh.close()

    def test_without_the_guest_token_the_rooms_are_left_behind(self):
        """
        Documents why the header matters. With no guest token the endpoint cannot
        know a guest is involved: it signs the user into a separate Discord
        account, and the guest's rooms stay on an account nothing can reach --
        `guest_uuid` is written at creation and read nowhere. This is exactly the
        shape the client must not send on an upgrade.
        """
        guest_id = self.make_guest_with_a_room()

        resp = self.callback(guest_token=None)
        self.assertEqual(resp.status_code, 200)

        fresh = Session()
        try:
            guest = fresh.query(User).get(guest_id)
            self.assertTrue(guest.is_guest)

            discord_user = fresh.query(User).filter_by(discord_id=DISCORD_ID).first()
            self.assertIsNotNone(discord_user)
            self.assertNotEqual(discord_user.id, guest_id)
            self.assertEqual(
                fresh.query(UserRoomSubscription).filter_by(user_id=discord_user.id).count(), 0
            )
        finally:
            fresh.close()

    def test_a_non_guest_token_never_takes_over_another_account(self):
        """
        Only a guest can be upgraded. A real account's token presented here must
        not be repointed at a different Discord identity.
        """
        real = User(discord_id='111', discord_username='someone_else', is_guest=False)
        self.session.add(real)
        self.session.commit()
        real_id = real.id

        resp = self.callback(guest_token=self.token_for(real_id))
        self.assertEqual(resp.status_code, 200)

        fresh = Session()
        try:
            untouched = fresh.query(User).get(real_id)
            self.assertEqual(untouched.discord_id, '111')
            self.assertIsNotNone(fresh.query(User).filter_by(discord_id=DISCORD_ID).first())
        finally:
            fresh.close()


if __name__ == '__main__':
    unittest.main()
