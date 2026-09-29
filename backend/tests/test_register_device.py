"""
Tests for POST /devices moving a push token between rows.

A push token is unique across every device row. When a phone's token is
already held by another row -- another account logged in on the same phone, or
this account's row for an old device ID after a phone transfer -- registering
has to remove that row and give the token to this one. The removal must reach
the database before the insert or update, or the unique constraint fails and
the device silently never registers. See #365.
"""
import os
import unittest
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone

import time
from unittest.mock import patch

import jwt as pyjwt
from firebase_admin import messaging

# Set up test DB and config before importing the app
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_register_device.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='  # Valid Fernet key

# Import through `app.*` only, never `backend.app.*` -- see the note in
# test_slot_track_mode.py. The routes import `app`, so `backend.app` would give
# this test a second engine that CI's Linux runner leaves on a deleted file.
from app import create_app, Session, engine
from app.models import Base, User, Device
from app.routes import user_routes

TOKEN = 'fcm-token-shared'


def _remove_test_db():
    for suffix in ('', '-wal', '-shm'):
        path = f"{TEST_DB_PATH}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class RegisterDeviceTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()

        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

        self.session = Session()
        self.alice = self.make_user()
        self.bob = self.make_user()

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

    def make_user(self):
        user = User(is_guest=True, guest_uuid=str(uuid_lib.uuid4()))
        self.session.add(user)
        self.session.commit()
        return user.id

    def add_device(self, user_id, fcm_token, android_id):
        self.session.add(Device(fcm_token=fcm_token, user_id=user_id, android_id=android_id, platform='android'))
        self.session.commit()

    def auth(self, user_id):
        token = pyjwt.encode(
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
        return {'Authorization': f'Bearer {token}'}

    def register(self, user_id, fcm_token, android_id=None):
        body = {'fcm_token': fcm_token, 'platform': 'android'}
        if android_id is not None:
            body['device_id'] = android_id
        return self.app.test_client().post(
            '/devices', json=body, headers=self.auth(user_id)
        )

    def devices(self):
        self.session.expire_all()
        return [
            (d.user_id, d.fcm_token, d.android_id)
            for d in self.session.query(Device).order_by(Device.id).all()
        ]



class RegisterDeviceTest(RegisterDeviceTestBase):
    def test_token_moves_to_a_new_account_on_the_same_phone(self):
        self.add_device(self.alice, TOKEN, 'phone-1')

        resp = self.register(self.bob, TOKEN, 'phone-1')

        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(self.devices(), [(self.bob, TOKEN, 'phone-1')])

    def test_token_moves_onto_an_existing_row_for_the_new_account(self):
        # Bob used this phone before under an older token, so he already has a
        # row for it. The update branch must also wait for Alice's row to go.
        self.add_device(self.alice, TOKEN, 'phone-1')
        self.add_device(self.bob, 'bob-old-token', 'phone-1')

        resp = self.register(self.bob, TOKEN, 'phone-1')

        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(self.devices(), [(self.bob, TOKEN, 'phone-1')])

    def test_token_moves_to_a_new_device_id_on_the_same_account(self):
        # A phone transfer copies the token to a phone with a new device ID.
        self.add_device(self.alice, TOKEN, 'old-phone')

        resp = self.register(self.alice, TOKEN, 'new-phone')

        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(self.devices(), [(self.alice, TOKEN, 'new-phone')])

    def test_legacy_register_without_a_device_id_moves_the_token(self):
        self.add_device(self.alice, TOKEN, 'phone-1')

        resp = self.register(self.bob, TOKEN)

        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(self.devices(), [(self.bob, TOKEN, None)])

    def test_re_registering_the_same_token_changes_nothing(self):
        self.add_device(self.alice, TOKEN, 'phone-1')

        resp = self.register(self.alice, TOKEN, 'phone-1')

        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(self.devices(), [(self.alice, TOKEN, 'phone-1')])

    def test_a_refreshed_token_updates_the_row_and_leaves_others_alone(self):
        self.add_device(self.alice, 'alice-old-token', 'phone-1')
        self.add_device(self.bob, 'bob-token', 'phone-2')

        resp = self.register(self.alice, 'alice-new-token', 'phone-1')

        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(self.devices(), [
            (self.alice, 'alice-new-token', 'phone-1'),
            (self.bob, 'bob-token', 'phone-2'),
        ])


def _unregistered():
    return messaging.UnregisteredError('Requested entity was not found.')


@patch('app.routes.user_routes.get_firebase_app', return_value=object())
class DeadTokenTest(RegisterDeviceTestBase):
    """A token FCM has retired is refused so the app can fetch a fresh one (#364)."""

    def test_a_dead_token_is_refused_and_not_stored(self, _app):
        with patch.object(user_routes.messaging, 'send', side_effect=_unregistered()) as send:
            resp = self.register(self.alice, TOKEN, 'phone-1')

        self.assertEqual(resp.status_code, 410, resp.get_json())
        self.assertEqual(resp.get_json()['error'], 'fcm_token_unregistered')
        self.assertEqual(self.devices(), [])
        self.assertTrue(send.call_args.kwargs['dry_run'])

    def test_a_dead_token_is_removed_from_rows_that_still_hold_it(self, _app):
        # The old phone's row, carried over by a transfer.
        self.add_device(self.alice, TOKEN, 'old-phone')
        self.add_device(self.bob, 'bob-token', 'phone-2')

        with patch.object(user_routes.messaging, 'send', side_effect=_unregistered()):
            resp = self.register(self.alice, TOKEN, 'new-phone')

        self.assertEqual(resp.status_code, 410, resp.get_json())
        self.assertEqual(self.devices(), [(self.bob, 'bob-token', 'phone-2')])

    def test_a_live_token_is_stored(self, _app):
        with patch.object(user_routes.messaging, 'send', return_value='projects/x/messages/1'):
            resp = self.register(self.alice, TOKEN, 'phone-1')

        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(self.devices(), [(self.alice, TOKEN, 'phone-1')])

    def test_an_fcm_error_fails_open(self, _app):
        with patch.object(user_routes.messaging, 'send', side_effect=ConnectionError('FCM down')):
            resp = self.register(self.alice, TOKEN, 'phone-1')

        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(self.devices(), [(self.alice, TOKEN, 'phone-1')])

    def test_a_slow_fcm_fails_open(self, _app):
        with patch.object(user_routes, '_TOKEN_CHECK_TIMEOUT_SECONDS', 0.05), \
             patch.object(user_routes.messaging, 'send', side_effect=lambda *a, **k: time.sleep(0.5)):
            started = time.monotonic()
            resp = self.register(self.alice, TOKEN, 'phone-1')
            elapsed = time.monotonic() - started
            time.sleep(0.6)  # let the stalled check finish and free its slot

        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertLess(elapsed, 0.4)
        self.assertEqual(self.devices(), [(self.alice, TOKEN, 'phone-1')])

    def test_the_check_is_skipped_while_earlier_checks_are_stuck(self, _app):
        # Every slot held, as if FCM had stopped answering.
        held = 0
        while user_routes._token_check_slots.acquire(blocking=False):
            held += 1
        try:
            with patch.object(user_routes.messaging, 'send', side_effect=_unregistered()) as send:
                resp = self.register(self.alice, TOKEN, 'phone-1')
        finally:
            for _ in range(held):
                user_routes._token_check_slots.release()

        self.assertEqual(resp.status_code, 201, resp.get_json())
        send.assert_not_called()
        self.assertEqual(self.devices(), [(self.alice, TOKEN, 'phone-1')])

    def test_the_test_push_prunes_a_dead_token_and_says_so(self, _app):
        self.add_device(self.alice, 'dead-token', 'old-phone')
        self.add_device(self.alice, 'live-token', 'new-phone')

        def send(message, *args, **kwargs):
            if message.token == 'dead-token':
                raise _unregistered()
            return 'projects/x/messages/1'

        with patch.object(user_routes.messaging, 'send', side_effect=send):
            resp = self.app.test_client().post(
                '/users/me/test-notification', headers=self.auth(self.alice))

        body = resp.get_json()
        self.assertEqual(resp.status_code, 200, body)
        self.assertEqual((body['sent'], body['failed'], body['removed']), (1, 1, 1))
        self.assertEqual(self.devices(), [(self.alice, 'live-token', 'new-phone')])


if __name__ == '__main__':
    unittest.main()
