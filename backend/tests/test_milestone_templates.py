import os
import sys
import unittest
import json

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_templates.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, Session, engine
from app.models import Base, User, MilestoneTemplate, MilestoneTemplateItem


def _make_token(app, user_id):
    """Generate a JWT for the given user_id matching the token_required format."""
    import jwt as pyjwt
    import uuid
    from datetime import datetime, timezone, timedelta
    payload = {
        'user_id': user_id,
        'jti': str(uuid.uuid4()),
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


class TestMilestoneTemplates(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = self.app.test_client()
        session = Session()
        try:
            self.user_a = User(discord_id='user_a', discord_username='UserA')
            self.user_b = User(discord_id='user_b', discord_username='UserB')
            session.add_all([self.user_a, self.user_b])
            session.commit()
            self.token_a = _make_token(self.app, self.user_a.id)
            self.token_b = _make_token(self.app, self.user_b.id)
        finally:
            Session.remove()

    def tearDown(self):
        Session.remove()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def _auth(self, token):
        return {'Authorization': f'Bearer {token}'}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_template(self, token, name='Standard Start', game='Mega Man 2', items=None):
        if items is None:
            items = [
                {'item_name': 'Items', 'quantity': 3, 'is_group': True},
                {'item_name': 'Bubble Lead', 'quantity': 1, 'is_group': False},
            ]
        return self.client.post(
            '/milestone-templates',
            json={'name': name, 'game_name': game, 'items': items},
            headers=self._auth(token),
        )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def test_create_template_success(self):
        r = self._create_template(self.token_a)
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertIn('id', data)

    def test_create_template_missing_name(self):
        r = self.client.post(
            '/milestone-templates',
            json={'game_name': 'Mega Man 2', 'items': [{'item_name': 'Items', 'quantity': 1}]},
            headers=self._auth(self.token_a),
        )
        self.assertEqual(r.status_code, 400)

    def test_create_template_missing_game(self):
        r = self.client.post(
            '/milestone-templates',
            json={'name': 'Test', 'items': [{'item_name': 'Items', 'quantity': 1}]},
            headers=self._auth(self.token_a),
        )
        self.assertEqual(r.status_code, 400)

    def test_create_template_no_items(self):
        r = self.client.post(
            '/milestone-templates',
            json={'name': 'Test', 'game_name': 'Mega Man 2', 'items': []},
            headers=self._auth(self.token_a),
        )
        self.assertEqual(r.status_code, 400)

    def test_create_template_item_quantity_zero_rejected(self):
        r = self.client.post(
            '/milestone-templates',
            json={
                'name': 'Test', 'game_name': 'Mega Man 2',
                'items': [{'item_name': 'Items', 'quantity': 0}],
            },
            headers=self._auth(self.token_a),
        )
        self.assertEqual(r.status_code, 400)

    def test_create_template_item_boolean_quantity_rejected(self):
        r = self.client.post(
            '/milestone-templates',
            json={
                'name': 'Test', 'game_name': 'Mega Man 2',
                'items': [{'item_name': 'Items', 'quantity': True}],
            },
            headers=self._auth(self.token_a),
        )
        self.assertEqual(r.status_code, 400)

    def test_create_template_non_dict_items_handled_safely(self):
        r = self.client.post(
            '/milestone-templates',
            json={
                'name': 'Test', 'game_name': 'Mega Man 2',
                'items': ['just_a_string', 123, None],
            },
            headers=self._auth(self.token_a),
        )
        self.assertEqual(r.status_code, 400)

    def test_create_template_duplicate_returns_409(self):
        self._create_template(self.token_a)
        r = self._create_template(self.token_a)
        self.assertEqual(r.status_code, 409)

    def test_duplicate_name_different_game_is_allowed(self):
        self._create_template(self.token_a, game='Mega Man 2')
        r = self._create_template(self.token_a, game='Mega Man 3')
        self.assertEqual(r.status_code, 201)

    def test_duplicate_name_different_user_is_allowed(self):
        self._create_template(self.token_a)
        r = self._create_template(self.token_b)
        self.assertEqual(r.status_code, 201)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def test_list_templates_empty(self):
        r = self.client.get('/milestone-templates', headers=self._auth(self.token_a))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), [])

    def test_list_templates_returns_own_only(self):
        self._create_template(self.token_a)
        self._create_template(self.token_b, name='Other')
        r = self.client.get('/milestone-templates', headers=self._auth(self.token_a))
        data = r.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], 'Standard Start')

    def test_list_templates_game_filter(self):
        self._create_template(self.token_a, name='MM2 Template', game='Mega Man 2')
        self._create_template(self.token_a, name='MM3 Template', game='Mega Man 3')
        r = self.client.get(
            '/milestone-templates?game=Mega+Man+2',
            headers=self._auth(self.token_a),
        )
        data = r.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], 'MM2 Template')

    def test_list_templates_game_filter_case_insensitive(self):
        self._create_template(self.token_a, game='Mega Man 2')
        r = self.client.get(
            '/milestone-templates?game=mega+man+2',
            headers=self._auth(self.token_a),
        )
        self.assertEqual(len(r.get_json()), 1)

    def test_list_templates_includes_items(self):
        self._create_template(self.token_a)
        r = self.client.get('/milestone-templates', headers=self._auth(self.token_a))
        items = r.get_json()[0]['items']
        self.assertEqual(len(items), 2)
        group_item = next(i for i in items if i['item_name'] == 'Items')
        self.assertTrue(group_item['is_group'])
        self.assertEqual(group_item['quantity'], 3)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def test_update_template_success(self):
        r = self._create_template(self.token_a)
        tid = r.get_json()['id']
        r2 = self.client.put(
            f'/milestone-templates/{tid}',
            json={
                'name': 'Updated',
                'game_name': 'Mega Man 2',
                'items': [{'item_name': 'Crash Bomber', 'quantity': 1, 'is_group': False}],
            },
            headers=self._auth(self.token_a),
        )
        self.assertEqual(r2.status_code, 200)
        r3 = self.client.get('/milestone-templates', headers=self._auth(self.token_a))
        data = r3.get_json()
        self.assertEqual(data[0]['name'], 'Updated')
        self.assertEqual(len(data[0]['items']), 1)
        self.assertEqual(data[0]['items'][0]['item_name'], 'Crash Bomber')

    def test_update_template_ownership_scoped(self):
        r = self._create_template(self.token_a)
        tid = r.get_json()['id']
        r2 = self.client.put(
            f'/milestone-templates/{tid}',
            json={
                'name': 'Hacked',
                'game_name': 'Mega Man 2',
                'items': [{'item_name': 'Items', 'quantity': 1}],
            },
            headers=self._auth(self.token_b),
        )
        self.assertEqual(r2.status_code, 404)

    def test_update_template_conflict_returns_409(self):
        self._create_template(self.token_a, name='A')
        r = self._create_template(self.token_a, name='B')
        tid = r.get_json()['id']
        r2 = self.client.put(
            f'/milestone-templates/{tid}',
            json={
                'name': 'A',
                'game_name': 'Mega Man 2',
                'items': [{'item_name': 'Items', 'quantity': 1}],
            },
            headers=self._auth(self.token_a),
        )
        self.assertEqual(r2.status_code, 409)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def test_delete_template_success(self):
        r = self._create_template(self.token_a)
        tid = r.get_json()['id']
        r2 = self.client.delete(f'/milestone-templates/{tid}', headers=self._auth(self.token_a))
        self.assertEqual(r2.status_code, 200)
        r3 = self.client.get('/milestone-templates', headers=self._auth(self.token_a))
        self.assertEqual(r3.get_json(), [])

    def test_delete_template_ownership_scoped(self):
        r = self._create_template(self.token_a)
        tid = r.get_json()['id']
        r2 = self.client.delete(f'/milestone-templates/{tid}', headers=self._auth(self.token_b))
        self.assertEqual(r2.status_code, 404)
        # Confirm it still exists for user A
        r3 = self.client.get('/milestone-templates', headers=self._auth(self.token_a))
        self.assertEqual(len(r3.get_json()), 1)

    def test_delete_cascades_to_items(self):
        r = self._create_template(self.token_a)
        tid = r.get_json()['id']
        self.client.delete(f'/milestone-templates/{tid}', headers=self._auth(self.token_a))
        session = Session()
        try:
            count = session.query(MilestoneTemplateItem).filter_by(template_id=tid).count()
            self.assertEqual(count, 0)
        finally:
            Session.remove()

    # ------------------------------------------------------------------
    # Auth guard
    # ------------------------------------------------------------------

    def test_requires_auth(self):
        r = self.client.get('/milestone-templates')
        self.assertIn(r.status_code, (401, 403))


if __name__ == '__main__':
    unittest.main()
