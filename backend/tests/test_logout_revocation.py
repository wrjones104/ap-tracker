"""Both `/logout` and `/auth/logout` revoke the token (#519).

The route has always been `/logout`, with no prefix, while the Android app
(`ApiService.kt`) and `backend/iOS_DEVELOPER_GUIDE.md` both call `/auth/logout` --
which answered 404. So a user-requested logout never reached `JWTBlocklist`: the token
stayed valid for its full 90 days (Discord) or 730 (guest) while the app cleared its
local session and reported success, and a copied token outlived "Log out".

Nothing covered this route at all, which is how a 404 on the path every client uses
went unnoticed. These tests pin both paths.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_logout_revocation.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import Base, JWTBlocklist, User

# The unprefixed path the route was registered at, and the prefixed one every client
# actually calls. Both must revoke; dropping either would break a shipped client.
PATHS = ['/logout', '/auth/logout']


def _make_token(app, user_id):
    """A token in the shape token_required expects, with its jti."""
    import jwt as pyjwt
    jti = str(uuid.uuid4())
    payload = {
        'user_id': user_id,
        'jti': jti,
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256'), jti


class TestLogoutRevokesTheToken(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = self.app.test_client()
        session = Session()
        try:
            user = User(discord_id='user_a', discord_username='UserA')
            session.add(user)
            session.commit()
            self.user_id = user.id
        finally:
            Session.remove()

    def tearDown(self):
        Session.remove()
        engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = f"{TEST_DB_PATH}{suffix}"
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _blocklisted(self):
        session = Session()
        try:
            return {row.jti for row in session.query(JWTBlocklist).all()}
        finally:
            Session.remove()

    def test_both_paths_blocklist_the_jti(self):
        for path in PATHS:
            with self.subTest(path=path):
                token, jti = _make_token(self.app, self.user_id)
                response = self.client.post(path, headers={'Authorization': f'Bearer {token}'})
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                self.assertIn(
                    jti, self._blocklisted(),
                    "a logout that does not reach the blocklist leaves the token usable"
                )

    def test_a_revoked_token_is_refused_afterwards(self):
        # What the blocklist is for: the app clearing its own storage does nothing to a
        # token someone else has a copy of.
        for path in PATHS:
            with self.subTest(path=path):
                token, _ = _make_token(self.app, self.user_id)
                headers = {'Authorization': f'Bearer {token}'}
                self.assertEqual(self.client.post(path, headers=headers).status_code, 200)
                again = self.client.post(path, headers=headers)
                self.assertEqual(again.status_code, 401)
                self.assertEqual(again.get_json().get('error'), 'Token has been revoked')

    def test_neither_path_answers_404(self):
        # The symptom this issue was found by: no token gives 401 from a route that
        # exists, and 404 from one that does not.
        for path in PATHS:
            with self.subTest(path=path):
                response = self.client.post(path)
                self.assertEqual(response.status_code, 401, response.get_data(as_text=True))

    def test_a_token_without_a_jti_is_not_accepted(self):
        # Nothing could be blocklisted for it, so it must not come back 200 as if
        # something had been.
        import jwt as pyjwt
        token = pyjwt.encode(
            {'user_id': self.user_id, 'exp': datetime.now(timezone.utc) + timedelta(hours=1)},
            self.app.config['SECRET_KEY'], algorithm='HS256'
        )
        for path in PATHS:
            with self.subTest(path=path):
                response = self.client.post(path, headers={'Authorization': f'Bearer {token}'})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(self._blocklisted(), set())


if __name__ == '__main__':
    unittest.main()
