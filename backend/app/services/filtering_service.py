import json
import logging
import fnmatch

from app.models import DatapackageCache


def fetch_group_members_lookup(session, checksums):
    """
    Builds a set of (checksum, (group_name_lower, item_name_lower)) tuples describing
    item-group membership for the given datapackage checksums. Used to resolve
    game-specific item-group ignore/whitelist rules against the specific version
    (checksum) an item was actually received under.
    """
    group_members_lookup = set()
    checksums = {c for c in checksums if c}
    if not checksums:
        return group_members_lookup

    try:
        member_results = session.query(
            DatapackageCache.checksum, DatapackageCache.entity_name
        ).filter(
            DatapackageCache.checksum.in_(checksums),
            DatapackageCache.entity_type == 'item_name_groups_json'
        ).all()
        for chk, name_groups_str in member_results:
            try:
                parsed_data = json.loads(name_groups_str)
                if isinstance(parsed_data, dict):
                    for g_name, items in parsed_data.items():
                        if isinstance(items, list):
                            g_name_lower = g_name.lower().strip()
                            for item in items:
                                group_members_lookup.add((chk, (g_name_lower, item.lower().strip())))
            except Exception:
                pass
    except Exception as e:
        logging.error(f"[FILTER_DB_ERROR] Failed to fetch group members: {e}")

    return group_members_lookup


def evaluate_item_filter_status(item_name, game_name, game_checksum, ignore_items, whitelist_items, group_members_lookup):
    """
    Determines whether a single item is ignored and/or whitelisted for a user, given
    the item's name, the game it belongs to, and the datapackage checksum in effect
    when it was received (item groups are version-specific, so the checksum matters).

    Single-item rules match by name (optionally wildcarded) and are version-tolerant.
    Group rules require a game and are resolved against group_members_lookup for the
    specific checksum, since group membership can differ between versions of a game.

    Returns (is_ignored, is_whitelisted, matched_ignore_rule, matched_whitelist_rule).
    """
    normalized_item_name = (item_name or '').lower().strip()
    normalized_game_name = (game_name or '').lower().strip()

    is_whitelisted = False
    matched_whitelist_rule = None
    for rule in (whitelist_items or []):
        rule_pattern = rule.item_name.lower().strip()
        if getattr(rule, 'is_group', False):
            if rule.game_name and rule.game_name.lower().strip() == normalized_game_name:
                lookup_key = (game_checksum, (rule_pattern, normalized_item_name))
                if lookup_key in group_members_lookup:
                    is_whitelisted = True
                    matched_whitelist_rule = rule
                    break
        else:
            if fnmatch.fnmatch(normalized_item_name, rule_pattern):
                if not rule.game_name:
                    is_whitelisted = True
                    matched_whitelist_rule = rule
                    break
                elif rule.game_name.lower().strip() == normalized_game_name:
                    is_whitelisted = True
                    matched_whitelist_rule = rule
                    break

    is_ignored = False
    matched_ignore_rule = None
    if not is_whitelisted:
        for rule in (ignore_items or []):
            rule_pattern = rule.item_name.lower().strip()
            if getattr(rule, 'is_group', False):
                if rule.game_name and rule.game_name.lower().strip() == normalized_game_name:
                    lookup_key = (game_checksum, (rule_pattern, normalized_item_name))
                    if lookup_key in group_members_lookup:
                        is_ignored = True
                        matched_ignore_rule = rule
                        break
            else:
                if fnmatch.fnmatch(normalized_item_name, rule_pattern):
                    if not rule.game_name:
                        is_ignored = True
                        matched_ignore_rule = rule
                        break
                    elif rule.game_name.lower().strip() == normalized_game_name:
                        is_ignored = True
                        matched_ignore_rule = rule
                        break

    return is_ignored, is_whitelisted, matched_ignore_rule, matched_whitelist_rule
