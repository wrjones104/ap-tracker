import logging
import json
from firebase_admin import messaging
from app import get_firebase_app

def compress_notifications(user_notifications, user_prefs, slot_prefs_map):
    """
    Combines notifications of the same type if 'combine_notifications' is enabled or >10 items.
    """
    if not user_notifications:
        return []

    should_combine = user_prefs.combine_notifications_default
    remove_emojis = user_prefs.remove_emojis_default

    item_notif_count = sum(1 for n in user_notifications if n.get('type', '').startswith('item_'))
    if item_notif_count >= 10:
        should_combine = True
    
    if not should_combine:
        return user_notifications

    items = []
    hints = []
    finishes = []
    others = []

    for n in user_notifications:
        t = n.get('type', '')
        if t.startswith('item_'):
            items.append(n)
        elif t == 'hint':
            hints.append(n)
        elif t == 'player_finish':
            finishes.append(n)
        else:
            others.append(n)

    compressed = []
    compressed.extend(others)

    def squash(notif_list, title_base):
        if not notif_list:
            return
        if len(notif_list) == 1:
            compressed.append(notif_list[0])
            return
        
        first_title = notif_list[0]['title']
        room_suffix = ""
        if " - [" in first_title:
            room_suffix = first_title.split(" - [")[-1]
            room_suffix = " - [" + room_suffix

        item_strings = []
        for n in notif_list:
            if n.get('type') == 'hint':
                item_strings.append(n['body'])
            elif 'item_context' in n:
                ctx = n['item_context']
                formatted = f"{ctx['item_name']} [{ctx['original']}]"
                item_strings.append(formatted)
            else:
                raw = n['title'].split(" - [")[0]
                clean = raw.replace("🏆 ", "").replace("✅ ", "").replace("💡 ", "").replace("💣 ", "").replace("📃 ", "")
                item_strings.append(clean)

        count = len(item_strings)
        VISIBLE_LIMIT = 5 
        display_names = item_strings[:VISIBLE_LIMIT]
        remainder = count - VISIBLE_LIMIT
        
        body_str = ", ".join(display_names)
        if remainder > 0:
            body_str += f", and {remainder} others"
        
        final_title = f"{title_base} ({count}){room_suffix}"
        
        compressed.append({
            'title': final_title,
            'body': body_str,
            'type': notif_list[0]['type'],
            'bundled_items': json.dumps(item_strings) 
        })

    t_items = "New Items" if remove_emojis else "📦 New Items"
    t_hints = "New Hints" if remove_emojis else "💡 New Hints"
    t_finish = "Finished" if remove_emojis else "🏁 Finished"

    squash(items, t_items)
    squash(hints, t_hints)
    squash(finishes, t_finish)

    return compressed

def send_fcm_notifications(tokens, notifications):
    """
    Dispatches FCM push notifications to a list of device tokens.
    """
    if not tokens or not notifications:
        return 0

    get_firebase_app()
    success_count = 0

    for token in tokens:
        for notif in notifications:
            try:
                data_payload = {}
                if 'bundled_items' in notif:
                    data_payload['bundled_items'] = notif['bundled_items']

                message = messaging.Message(
                    notification=messaging.Notification(
                        title=notif['title'],
                        body=notif['body']
                    ),
                    data=data_payload,
                    token=token
                )
                messaging.send(message)
                success_count += 1
            except Exception as e:
                logging.error(f"[FCM_ERROR] Failed to send push to token {token[:10]}...: {e}")

    return success_count
