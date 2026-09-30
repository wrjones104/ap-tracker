"""
A combined notification says which slot reached each milestone (#337).

The bundler lists each push by its `item_context` when it has one, and falls
back to the title otherwise. Milestone pushes had none, so a bundle of several
milestones read "Boss Keys, Boss Keys" with no slot names anywhere, and the
in-app bundle sheet showed the same list.
"""
import json
import os
import unittest
from types import SimpleNamespace

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_milestone_bundle.db'))
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ['FLASK_ENV'] = 'development'
os.environ['ENCRYPTION_KEY'] = 'gL1S6v-5D0_l3ZtIox0zVwXyZ3-4VbCdeFghIjklMno='

from app.poller import _milestone_notification, compress_notifications


def group(name, *items):
    return SimpleNamespace(
        id=7,
        name=name,
        items=[SimpleNamespace(item_name=i, quantity=1, is_group=False) for i in items],
    )


def prefs(combine=True, remove_emojis=False):
    return SimpleNamespace(combine_notifications_default=combine, remove_emojis_default=remove_emojis)


class TestMilestoneBundle(unittest.TestCase):
    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def test_a_bundle_names_the_slot_of_each_milestone(self):
        notifs = [
            _milestone_notification(group('Boss Keys', 'Big Key'), 'Weekly', 'Alice_OoT', 1, 1, False),
            _milestone_notification(group('Boss Keys', 'Big Key'), 'Weekly', 'Bob_ALttP', 1, 1, False),
            {'title': 'Hookshot - [Weekly]', 'body': '', 'type': 'item_progression',
             'item_context': {'item_name': 'Hookshot', 'alias': None, 'original': 'Alice_OoT'}},
        ]

        [bundle] = compress_notifications(notifs, prefs(), {})

        self.assertEqual(
            json.loads(bundle['bundled_items']),
            ['🚩 Boss Keys [Alice_OoT]', '🚩 Boss Keys [Bob_ALttP]', 'Hookshot [Alice_OoT]'],
        )
        self.assertIn('Boss Keys [Bob_ALttP]', bundle['body'])

    def test_a_single_milestone_push_is_unchanged(self):
        notif = _milestone_notification(group('Boss Keys', 'Big Key', 'Small Key'), 'Weekly', 'Alice_OoT', 1, 2, False)

        self.assertEqual(notif['title'], '🚩 Boss Keys - [Weekly]')
        self.assertEqual(notif['body'], 'Alice_OoT: 1× Big Key, 1× Small Key')
        self.assertEqual(notif['type'], 'item_milestone')
        self.assertEqual(notif['details'], (1, 2, 7))
        self.assertEqual(compress_notifications([notif], prefs(), {}), [notif])

    def test_an_unnamed_group_and_no_emojis(self):
        notif = _milestone_notification(group(None, 'Big Key', 'Small Key'), 'Weekly', 'Alice_OoT', 1, 1, True)

        self.assertEqual(notif['title'], 'Milestone Reached! Big Key + 1 others - [Weekly]')
        self.assertEqual(notif['item_context']['item_name'], 'Milestone Reached! Big Key + 1 others')


if __name__ == '__main__':
    unittest.main()
