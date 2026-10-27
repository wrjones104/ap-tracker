"""
New items and hint changes carried inside the push itself, so the phone can store them
without calling the server back (#416).

A push that reaches the app makes it sync: `GET /users/me/tracked-slots` plus at least one
`POST /history/sync`. This builds the rows that sync would have downloaded, in a compact form,
and attaches them to the push as the `history` data field.

**The proof the phone checks.** It stores the rows only when it can show nothing is missing
between what it has and what the push carries; otherwise it syncs as before.

- Items, per tracked slot: `after` is the item id the payload starts from. The phone's own
  position for a slot is its highest stored id; it stores the slot's items when that is at
  least `after` (or `after` is null: the slot's whole history is here).
- Hints, per room: `hints_after` is the hint change (`updated_at`) the payload starts from.
  The phone keeps its own hint coverage for the room, the later of its /history/sync hint
  cursor and the newest change a stored payload carried. It stores the hints when that
  coverage is at least `hints_after` (or `hints_after` is null). Only hints touching the
  user's tracked slots count: those are the only ones the app shows.

**Where a payload starts.** The server remembers what the last payload sent the user carried:
`UserTrackedSlot.push_item_cursor` and `UserRoomSubscription.push_hint_cursor`. The next
payload carries everything after them, including items that arrived with no notification of
their own (filler and traps, by default) and hint changes in polls that sent the user
nothing. Without that, those would sit between the phone and the next push, and the phone
would sync anyway. A null cursor (new slot, first payload since deploy, or reset) starts from
the poll before this one, which proves as much as a payload can on its own.

Every tracked slot is in the proof, not only those with new items: a slot left out could hide
items that arrived with no push. A carried payload that found a slot's whole history empty
stores 0 as its cursor (and `HINT_CURSOR_EPOCH` when no hint touched the user's slots), so the
next payload carries the slot's first items whole instead of starting after them.

**When it is withheld** the cursors are reset to null, because the phone will sync instead:
- the user's batch holds a finish or a milestone (`mixed_batch`);
- more items or hints than fit (`too_large`, here or when the message is assembled).

Older apps ignore the field. Server first, additive.
"""
import json
from datetime import datetime

from sqlalchemy import or_

from app.models import NotifiedItem, NotifiedHint
from app.routes.common import format_iso_z
from app.services.history_rows import serialize_history_rows

HISTORY_PAYLOAD_VERSION = 2

# FCM refuses a message over 4096 bytes. This is the whole message as we count it (title,
# body, every data key and value), with room left for the envelope FCM adds.
FCM_MESSAGE_BUDGET_BYTES = 3600

# More than this never fits the budget, so stop reading there.
MAX_PAYLOAD_ITEMS = 40
MAX_PAYLOAD_HINTS = 30

# Notification types the payload can stand in for: the items and hints it carries. A finish
# changes the room's roster and a milestone redraws the Milestones widget from the server, so
# both keep the ordinary sync.
_PAYLOAD_PUSH_TYPES = {'item_progression', 'item_useful', 'item_trap', 'item_filler', 'hint'}

FILTER_IGNORED = 1
FILTER_WHITELISTED = 2

# Stored as push_hint_cursor when a carried payload found no hint touching the user's slots:
# the next payload carries those hints from the start. Null would mean "unknown" instead, and
# start after them.
HINT_CURSOR_EPOCH = datetime(1970, 1, 1)


def item_start(cursor, prior_max):
    """
    Where a slot's block starts: after `cursor` when there is one (0: the slot's whole history,
    sent as null), else after `prior_max`, the slot's newest item before this poll.
    """
    if cursor is None:
        return prior_max
    return cursor or None


def hint_start(cursor, snapshot_newest):
    """Where the hints start: after `cursor` (the epoch: from the start), else after `snapshot_newest`."""
    if cursor is None:
        return snapshot_newest
    return None if cursor <= HINT_CURSOR_EPOCH else cursor


def history_push_users(notifications_by_user):
    """The users whose whole batch is item and hint pushes, so the payload can replace their sync."""
    return {
        user_id for user_id, notifs in notifications_by_user.items()
        if notifs and all(n.get('type') in _PAYLOAD_PUSH_TYPES for n in notifs)
    }


def newest_relevant_hint(hint_snapshot, tracked_slots):
    """
    The newest `updated_at` among `hint_snapshot` rows touching `tracked_slots`, or None.

    `hint_snapshot` is [(item_owner_id, location_owner_id, updated_at)] for the room's hints as
    they stood before this poll changed any, which is where a payload with no hint cursor
    starts.
    """
    times = [updated for owner, finder, updated in hint_snapshot
             if updated is not None and (owner in tracked_slots or finder in tracked_slots)]
    return max(times) if times else None


def _player_row(player, slot_id, checks_known):
    """[name, alias, game, finished, has_all_checks], as /history/sync derives them."""
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


def _bits(row):
    return (FILTER_IGNORED if row['isIgnored'] else 0) | (FILTER_WHITELISTED if row['isWhitelisted'] else 0)


def build_history_payload(session, user_id, room, sub, tracked_slots, item_after, hint_after,
                          players, checks_known):
    """
    One user's payload for one room, and the cursors it advances to.

    `item_after` is {slot_id: id the slot's block starts after, or None for its whole history},
    for every tracked slot (see item_start). A slot with a null start and nothing to carry has
    nothing to check, so it is left out of the payload. `hint_after` is the
    `updated_at` the hints start after, or None. `players` is the room's player list as stored
    (with this poll's finished flags), and `checks_known` whether it has check counts.

    Returns (payload JSON or None when too many rows, {slot_id: new item cursor}, new hint
    cursor). Rows are built by serialize_history_rows, the code /history/sync uses, so a row
    stored from a push is the row a later sync would send.
    """
    items = []
    for slot_id, after in sorted(item_after.items()):
        rows = session.query(NotifiedItem).filter(
            NotifiedItem.room_id == room.room_id,
            NotifiedItem.receiving_slot_id == slot_id,
            NotifiedItem.id > (after or 0),
        ).order_by(NotifiedItem.id).limit(MAX_PAYLOAD_ITEMS + 1).all()
        items.extend(rows)
        if len(items) > MAX_PAYLOAD_ITEMS:
            return None, {}, None

    tracked = list(tracked_slots)
    hint_query = session.query(NotifiedHint).filter(
        NotifiedHint.room_id == room.room_id,
        or_(NotifiedHint.item_owner_id.in_(tracked), NotifiedHint.location_owner_id.in_(tracked)),
    )
    if hint_after is not None:
        hint_query = hint_query.filter(NotifiedHint.updated_at > hint_after)
    hints = hint_query.order_by(NotifiedHint.updated_at, NotifiedHint.id).limit(MAX_PAYLOAD_HINTS + 1).all()
    if len(hints) > MAX_PAYLOAD_HINTS:
        return None, {}, None

    item_dicts, hint_dicts = serialize_history_rows(
        session, user_id, items, hints, {room.room_id: room}, {room.room_id: sub}
    )
    carried_by_slot = {}
    for item in items:
        carried_by_slot.setdefault(item.receiving_slot_id, []).append(item.id)
    item_dict_by_id = {d['id']: d for d in item_dicts}
    hint_dict_by_id = {d['id']: d for d in hint_dicts}

    player_map = {p['slot_id']: p for p in players if isinstance(p, dict) and 'slot_id' in p}
    referenced = {i.receiving_slot_id for i in items} | {i.sending_slot_id for i in items} \
        | {h.item_owner_id for h in hints} | {h.location_owner_id for h in hints}

    item_rows = []
    for item in items:
        d = item_dict_by_id[item.id]
        item_rows.append([item.id, item.receiving_slot_id, item.sending_slot_id, d['itemName'],
                          d['locationName'], d['itemFlags'], d['receivedCount'], _bits(d), d['timestamp']])
    hint_rows = []
    for hint in hints:
        d = hint_dict_by_id[hint.id]
        hint_rows.append([hint.id, hint.item_owner_id, hint.location_owner_id, d['item_name'],
                          d['location_name'], d['is_found'], d['item_flags'], _bits(d),
                          d['timestamp'], d['updated_at']])

    payload = {
        'v': HISTORY_PAYLOAD_VERSION,
        'room': room.id,
        'tracker': room.tracker_id,
        'host': room.hostname,
        'icon': sub.icon_name,
        'alias': sub.alias,
        # The user's tracked slots here: the app files each hint "for you" or "by you" by them,
        # as the sync does, and has no roster to hand when it stores a push.
        'tracked': sorted(tracked),
        'slots': [[slot_id, after] for slot_id, after in sorted(item_after.items())
                  if after is not None or slot_id in carried_by_slot],
        'hints_after': format_iso_z(hint_after),
        'players': {
            str(slot_id): _player_row(player_map.get(slot_id), slot_id, checks_known)
            for slot_id in sorted(s for s in referenced if s is not None)
        },
        'items': item_rows,
        'hints': hint_rows,
    }

    # A whole history that was empty is still known: 0, not null (see the module docstring).
    new_item_cursors = {
        slot_id: max(carried_by_slot[slot_id]) if slot_id in carried_by_slot else (after or 0)
        for slot_id, after in item_after.items()
    }
    new_hint_cursor = max((h.updated_at for h in hints), default=hint_after or HINT_CURSOR_EPOCH)

    return json.dumps(payload, separators=(',', ':'), ensure_ascii=False), new_item_cursors, new_hint_cursor


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
