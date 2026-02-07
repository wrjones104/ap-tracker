import logging
from datetime import timezone

def is_snoozed(user_prefs, slot_prefs, now_utc, user_id, slot_id, context_label="item"):
    """
    Checks if a notification should be suppressed due to Global or Slot snooze.
    Handles timezone normalization (naive -> UTC aware).
    """
    # 1. Check Global Snooze
    global_snooze = user_prefs.global_snooze_until
    if global_snooze:
        # If DB returned naive time, force it to be UTC aware
        if global_snooze.tzinfo is None:
            global_snooze = global_snooze.replace(tzinfo=timezone.utc)
        
        if global_snooze > now_utc:
            logging.debug(f"[NOTIFY_SNOOZE] User {user_id} is globally snoozed. Suppressing {context_label}.")
            return True

    # 2. Check Slot Snooze
    if slot_prefs:
        slot_snooze = slot_prefs.snooze_until
        if slot_snooze:
            # If DB returned naive time, force it to be UTC aware
            if slot_snooze.tzinfo is None:
                slot_snooze = slot_snooze.replace(tzinfo=timezone.utc)

            if slot_snooze > now_utc:
                logging.debug(f"[NOTIFY_SNOOZE] User {user_id} has snoozed Slot {slot_id} ({context_label}).")
                return True
                
    return False