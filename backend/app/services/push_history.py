"""
New items carried inside the push itself, so the phone can store them without calling the
server back (#416).

Every push used to make every device sync: `GET /users/me/tracked-slots` plus at least one
`POST /history/sync`. The push already knew which items it announced, but only as display
text. This builds the rows the app would have downloaded, in a compact form, and attaches
them to the push as the `history` data field.

The phone stores them only when it can prove it is not skipping anything. Each slot carries
`after`: the highest item id the server held for that slot before this poll. The app's own
cursor for a slot is its highest stored id, so when the two match, these items are exactly
the next ones; when they do not, the app falls back to the ordinary sync. The payload is
therefore all-or-nothing per user: it lists every new item of every tracked slot of theirs in
the room, not just the ones that were announced, or none at all.

It is withheld, and the app syncs as before, whenever a sync would bring more than items:
- the room's hints changed this poll (the sync also carries hints),
- the user's batch holds anything but item pushes (finishes, hints, milestones),
- it would push the message over FCM's 4 KB limit.

Older apps ignore the field. Server first, additive.
"""
import json

from app.routes.common import format_iso_z
from app.services.filtering_service import evaluate_item_filter_status

HISTORY_PAYLOAD_VERSION = 1

# FCM refuses a message over 4096 bytes. This is the whole message as we count it (title,
# body, every data key and value), with room left for the envelope FCM adds.
FCM_MESSAGE_BUDGET_BYTES = 3600

# Notification types the payload can stand in for. A milestone also redraws the
# Milestones widget from the server, so it keeps the ordinary sync.
_ITEM_PUSH_TYPES = {'item_progression', 'item_useful', 'item_trap', 'item_filler'}

FILTER_IGNORED = 1
FILTER_WHITELISTED = 2


def history_push_users(notifications_by_user):
    """The users whose whole batch is item pushes, so the payload can replace their sync."""
    return {
        user_id for user_id, notifs in notifications_by_user.items()
        if notifs and all(n.get('type') in _ITEM_PUSH_TYPES for n in notifs)
    }


def _player_row(player, slot_id, checks_known):
    """[name, alias, game, finished, has_all_checks], as /history/sync names them."""
    if not player:
        return [f"Player {slot_id}", None, "Unknown", False, False if checks_known else None]
    has_all_checks = player.get('has_all_checks', False) if checks_known else None
    return [
        player.get('name', f"Player {slot_id}"),
        player.get('alias'),
        player.get('game'),
        bool(player.get('is_finished', False)),
        has_all_checks,
    ]


def build_history_payloads(user_ids, items, tracked_slots_by_user, prior_max_by_slot, room,
                           players, checks_known, game_checksums, name_lookup,
                           item_counts, users_by_id, group_members_lookup, icons_by_user):
    """
    The `history` field for each user, as a JSON string, keyed by user id.

    `items` are this poll's NotifiedItem rows as stored, ids and all. `prior_max_by_slot` is
    {slot_id: highest id stored before this poll}, absent for a slot that had none.
    `item_counts` is {(room_uuid, slot_id, item_id): total after this poll}, which is what
    /history/sync would report as receivedCount right now. `icons_by_user` is each user's
    icon for the room, which the app stores on every item.

    Field for field, each item matches what /history/sync would send for it, so a row stored
    from a push and the same row downloaded later are identical.
    """
    player_map = {p['slot_id']: p for p in players if isinstance(p, dict) and 'slot_id' in p}
    game_map = {slot_id: p.get('game') for slot_id, p in player_map.items()}
    payloads = {}

    for user_id in user_ids:
        tracked = tracked_slots_by_user.get(user_id) or set()
        user_items = sorted(
            (item for item in items if item.receiving_slot_id in tracked and item.id is not None),
            key=lambda item: item.id,
        )
        if not user_items:
            continue

        user = users_by_id.get(user_id)
        ignore_items = user.ignore_items if user else []
        whitelist_items = user.whitelist_items if user else []

        slot_ids = sorted({item.receiving_slot_id for item in user_items})
        referenced = set(slot_ids) | {item.sending_slot_id for item in user_items}

        rows = []
        for item in user_items:
            receiver_game = game_map.get(item.receiving_slot_id, "Unknown")
            sender_game = game_map.get(item.sending_slot_id, "Unknown")
            rec_checksum = game_checksums.get(receiver_game)
            snd_checksum = game_checksums.get(sender_game)

            item_name = (name_lookup.get((rec_checksum, 'item', item.item_id))
                         if receiver_game and rec_checksum else None) or f"Item ID {item.item_id}"
            location_name = (name_lookup.get((snd_checksum, 'location', item.location_id))
                             if sender_game and snd_checksum else None) or f"Location ID {item.location_id}"

            is_ignored, is_whitelisted, _, _ = evaluate_item_filter_status(
                item_name=item_name,
                game_name=receiver_game,
                game_checksum=rec_checksum,
                ignore_items=ignore_items,
                whitelist_items=whitelist_items,
                group_members_lookup=group_members_lookup,
            )
            filter_bits = (FILTER_IGNORED if is_ignored else 0) | (FILTER_WHITELISTED if is_whitelisted else 0)

            rows.append([
                item.id,
                item.receiving_slot_id,
                item.sending_slot_id,
                item_name,
                location_name,
                item.item_flags or 0,
                item_counts.get((item.room_id, item.receiving_slot_id, item.item_id), 0),
                filter_bits,
                format_iso_z(item.timestamp),
            ])

        payload = {
            'v': HISTORY_PAYLOAD_VERSION,
            'room': room.id,
            'tracker': room.tracker_id,
            'host': room.hostname,
            'icon': icons_by_user.get(user_id),
            'slots': [[slot_id, prior_max_by_slot.get(slot_id)] for slot_id in slot_ids],
            'players': {
                str(slot_id): _player_row(player_map.get(slot_id), slot_id, checks_known)
                for slot_id in sorted(s for s in referenced if s is not None)
            },
            'items': rows,
        }
        payloads[user_id] = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)

    return payloads


def message_size(title, body, data_payload):
    """The bytes FCM counts for a message, near enough: title, body, data keys and values."""
    total = len((title or '').encode('utf-8')) + len((body or '').encode('utf-8'))
    for key, value in (data_payload or {}).items():
        total += len(str(key).encode('utf-8')) + len(str(value).encode('utf-8'))
    return total


def fits_in_push(title, body, data_payload, history):
    """Whether adding `history` keeps the message inside the budget."""
    return message_size(title, body, data_payload) + len('history') + len(history.encode('utf-8')) \
        <= FCM_MESSAGE_BUDGET_BYTES
