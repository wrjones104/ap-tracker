"""
Milestone template application.

Two callers share the resolution logic here:

  * the bulk apply endpoint, which the app's "Apply Templates" sheet posts to when a user
    ticks several templates at once; and
  * the poller, which applies templates a user has marked auto_apply to slots they have
    newly started playing.

Both need the same thing: turn a template's stored item names into threshold group items
that actually exist in this seed's datapackage, dropping the ones that do not. A template
saved from a different seed of the same game routinely names items this one has never
heard of, and a group requirement that can never be satisfied is worse than absent -- it
silently pins the milestone open forever.
"""
import json
import logging

from app.models import (
    DatapackageCache,
    MilestoneTemplate,
    ThresholdGroup,
    ThresholdGroupItem,
)
from app.services.threshold_service import compute_requirement_progress
from app.utils import TRACK_MODE_PLAY, normalize_track_mode

# A single slot gaining more milestone groups than this is far more likely to be a mistake
# than an intent, and every group is evaluated on every poll.
MAX_GROUPS_PER_SLOT = 50


def load_valid_item_names(session, checksum):
    """
    The names a threshold group item may legally carry for one datapackage, as
    (item_names_lower_to_canonical, group_names_lower_to_canonical).

    Returns None when the datapackage is not cached for this checksum. That is deliberately
    distinct from "cached but empty": a caller applying templates automatically must defer
    rather than write requirements nothing has checked.
    """
    if not checksum:
        return None

    items = {}
    for (name,) in session.query(DatapackageCache.entity_name).filter(
        DatapackageCache.checksum == checksum,
        DatapackageCache.entity_type == 'item'
    ).all():
        if name:
            items[name.lower().strip()] = name

    groups_row = session.query(DatapackageCache.entity_name).filter(
        DatapackageCache.checksum == checksum,
        DatapackageCache.entity_type == 'item_name_groups_json'
    ).first()

    if not items and not groups_row:
        return None

    groups = {}
    if groups_row and groups_row[0]:
        try:
            parsed = json.loads(groups_row[0])
            if isinstance(parsed, dict):
                for g_name in parsed:
                    if isinstance(g_name, str) and g_name.strip():
                        groups[g_name.lower().strip()] = g_name
        except Exception as e:
            logging.warning(
                f"[MILESTONE_TEMPLATE] Bad item_name_groups_json for checksum {checksum}: {e}"
            )

    return items, groups


def resolve_items(template_items, valid_names):
    """
    Match stored template items against a seed's datapackage.

    template_items: an iterable of objects carrying .item_name, .quantity and .is_group, or of
    (item_name, quantity, is_group) tuples.
    valid_names: the pair returned by load_valid_item_names, or None to skip verification.

    Returns (resolved, missing_count). Resolved items carry the datapackage's own casing, so a
    template written as "bubble lead" lines up with the counts the poller records.
    """
    normalized = []
    for entry in template_items:
        if isinstance(entry, (tuple, list)):
            name, quantity, is_group = entry
        else:
            name, quantity, is_group = entry.item_name, entry.quantity, entry.is_group
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            quantity = 0
        normalized.append(((name or '').strip(), quantity, bool(is_group)))

    if valid_names is None:
        kept = [e for e in normalized if e[0] and e[1] >= 1]
        return kept, len(normalized) - len(kept)

    item_names, group_names = valid_names
    resolved = []
    missing = 0
    for name, quantity, is_group in normalized:
        if not name or quantity < 1:
            missing += 1
            continue
        lookup = group_names if is_group else item_names
        canonical = lookup.get(name.lower())
        if canonical is None:
            missing += 1
            continue
        resolved.append((canonical, quantity, is_group))
    return resolved, missing


def create_group(session, tracked_slot_id, name, items):
    """Adds one ThresholdGroup and its items to the session. The caller commits."""
    group = ThresholdGroup(
        user_tracked_slot_id=tracked_slot_id,
        name=(name or '').strip() or None,
        is_triggered=False,
    )
    session.add(group)
    session.flush()
    for item_name, quantity, is_group in items:
        session.add(ThresholdGroupItem(
            group_id=group.id,
            item_name=item_name,
            quantity=quantity,
            is_group=is_group,
        ))
    return group


def existing_group_names(session, tracked_slot_id):
    """Lowercased names of the groups already on a slot, for duplicate suppression."""
    return {
        (name or '').strip().lower()
        for (name,) in session.query(ThresholdGroup.name).filter(
            ThresholdGroup.user_tracked_slot_id == tracked_slot_id
        ).all()
        if name
    }


def count_groups(session, tracked_slot_id):
    return session.query(ThresholdGroup.id).filter(
        ThresholdGroup.user_tracked_slot_id == tracked_slot_id
    ).count()


def mark_already_satisfied(session, room, slot_id, groups):
    """
    Marks any of [groups] whose requirements the slot has already met as triggered, without
    notifying. Returns the number marked.

    A milestone group is evaluated against the slot's *cumulative* item counts, and the poller's
    backfill window only skips one poll -- it never sets is_triggered. So a group created on a
    slot that is already past it does not stay quietly satisfied: it fires a "milestone reached"
    push the moment the next unrelated item lands, for something the user finished hours ago.
    Deciding it here, at creation, is the only point where "already done before this group
    existed" and "reached it just now" can still be told apart.

    Silent by design: the user was not tracking this milestone when they passed it, so there is
    nothing to announce -- the group simply shows as met.
    """
    if room is None or not groups:
        return 0

    requirements = [item for group in groups for item in group.items]
    if not requirements:
        return 0

    try:
        progress = compute_requirement_progress(session, room, slot_id, requirements)
    except Exception as e:
        # Never worth failing an apply over: an unmarked group is the pre-existing behavior.
        logging.error(
            f"[MILESTONE_TEMPLATE] Could not check milestone progress for slot {slot_id}: {e}",
            exc_info=True
        )
        return 0

    if not progress:
        return 0

    marked = 0
    for group in groups:
        if not group.items:
            continue
        # A requirement missing from progress could not be resolved, so it cannot be called met.
        if all(progress.get(item.id, -1) >= item.quantity for item in group.items):
            group.is_triggered = True
            marked += 1
    return marked


def apply_auto_templates(session, tracked_slot, game_name, checksum, valid_names_cache=None):
    """
    Applies every auto_apply template the slot's owner holds for this game.

    Returns (handled, created_groups). `handled` is True when the slot has been dealt with and
    its auto_apply_pending flag should be cleared, False when the datapackage is not cached yet
    and a later poll should try again. A slot with no matching templates is "dealt with" --
    there is nothing to wait for.
    """
    if not game_name:
        return False, []

    templates = session.query(MilestoneTemplate).filter(
        MilestoneTemplate.user_id == tracked_slot.user_id,
        MilestoneTemplate.auto_apply.is_(True),
    ).all()

    game_lower = game_name.strip().lower()
    matching = [t for t in templates if (t.game_name or '').strip().lower() == game_lower]
    if not matching:
        return True, []

    if valid_names_cache is not None and checksum in valid_names_cache:
        valid_names = valid_names_cache[checksum]
    else:
        valid_names = load_valid_item_names(session, checksum)
        if valid_names_cache is not None:
            valid_names_cache[checksum] = valid_names

    if valid_names is None:
        # The game is known but its datapackage has not been cached yet. Applying now would
        # mean writing requirements nothing has verified, so wait for a later poll instead.
        return False, []

    taken = existing_group_names(session, tracked_slot.id)
    already = count_groups(session, tracked_slot.id)

    created = []
    for template in sorted(matching, key=lambda t: (t.name or '').lower()):
        if already + len(created) >= MAX_GROUPS_PER_SLOT:
            logging.warning(
                f"[MILESTONE_TEMPLATE] Slot {tracked_slot.id} hit the {MAX_GROUPS_PER_SLOT}-group "
                f"cap; skipping the rest of its auto-apply templates."
            )
            break
        if (template.name or '').strip().lower() in taken:
            continue
        items, _missing = resolve_items(template.items, valid_names)
        if not items:
            logging.info(
                f"[MILESTONE_TEMPLATE] Template '{template.name}' has no items present in "
                f"'{game_name}' for slot {tracked_slot.id}; skipped."
            )
            continue
        created.append(create_group(session, tracked_slot.id, template.name, items))
        taken.add((template.name or '').strip().lower())

    if created:
        logging.info(
            f"[MILESTONE_TEMPLATE] Auto-applied {len(created)} template(s) to slot "
            f"{tracked_slot.slot_id} ({game_name}) for user {tracked_slot.user_id}."
        )
    return True, created


def apply_pending_for_room(session, room, players, game_checksums, tracked_slots):
    """
    Poller entry point. Applies auto-apply templates to every slot in this room still flagged
    auto_apply_pending, clearing the flag for the ones it could resolve.

    Never raises, and never leaves the caller's session unusable: each slot's writes go through
    their own SAVEPOINT, so a failed flush rolls back that slot alone. Without one, a swallowed
    flush error would mark the session as needing rollback and every later statement in the poll
    would raise PendingRollbackError -- costing the whole room its poll, for every user in it,
    which is the exact opposite of what this being non-fatal is meant to buy.

    Must run after this poll's SlotItemCount updates: mark_already_satisfied reads those counts
    to tell a milestone the slot has long since passed from one it is about to reach.
    """
    play_pending = [
        s for s in tracked_slots
        if getattr(s, 'auto_apply_pending', False)
        and normalize_track_mode(getattr(s, 'track_mode', None)) == TRACK_MODE_PLAY
    ]
    if not play_pending:
        return 0

    try:
        game_by_slot = {
            p.get('slot_id'): p.get('game')
            for p in players
            if isinstance(p, dict) and p.get('slot_id') is not None
        }
        checksums_lower = {
            k.strip().lower(): v
            for k, v in (game_checksums or {}).items()
            if isinstance(k, str)
        }
    except Exception as e:
        logging.error(f"[MILESTONE_TEMPLATE] Unreadable room cache: {e}", exc_info=True)
        return 0

    # One datapackage lookup per checksum, not per slot: a room where several slots play the
    # same game is the common case, not the exception.
    valid_names_cache = {}

    handled = 0
    for slot in play_pending:
        game = game_by_slot.get(slot.slot_id)
        if not game:
            continue
        checksum = checksums_lower.get(game.strip().lower())
        try:
            with session.begin_nested():
                dealt_with, created = apply_auto_templates(
                    session, slot, game, checksum, valid_names_cache
                )
                if created:
                    session.flush()
                    mark_already_satisfied(session, room, slot.slot_id, created)
                if dealt_with:
                    slot.auto_apply_pending = False
                    handled += 1
        except Exception as e:
            logging.error(
                f"[MILESTONE_TEMPLATE] Failed applying templates to slot {slot.id}: {e}",
                exc_info=True
            )
    return handled
