import logging
from datetime import datetime, timedelta
from sqlalchemy import or_

from app import Session
from app.models import NotifiedItem, NotifiedHint, User, JWTBlocklist

def purge_expired_notification_events(retention_days=90):
    """
    Purges NotifiedItem and NotifiedHint records older than retention_days (default: 90 days).
    This keeps the database size lean and queries fast for active multiworld sessions.
    """
    session = Session()
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        # 1. Delete items older than cutoff
        deleted_items = session.query(NotifiedItem).filter(
            NotifiedItem.timestamp < cutoff_date
        ).delete(synchronize_session=False)

        # 2. Delete hints older than cutoff
        deleted_hints = session.query(NotifiedHint).filter(
            NotifiedHint.timestamp < cutoff_date
        ).delete(synchronize_session=False)

        session.commit()
        logging.info(f"[RETENTION] Purged {deleted_items} items and {deleted_hints} hints older than {retention_days} days.")
        return {'purged_items': deleted_items, 'purged_hints': deleted_hints}
    except Exception as e:
        session.rollback()
        logging.error(f"[RETENTION_ERROR] Failed to purge notification events: {e}", exc_info=True)
        return {'purged_items': 0, 'purged_hints': 0}
    finally:
        Session.remove()

def purge_inactive_guest_accounts(inactivity_days=90):
    """
    Purges guest accounts (is_guest == True) with no activity for >inactivity_days.
    Cascading deletes remove associated subscriptions, slots, devices, ignore lists, etc.
    """
    session = Session()
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=inactivity_days)
        
        inactive_guests = session.query(User).filter(
            User.is_guest == True,
            or_(User.last_activity < cutoff_date, User.last_activity == None)
        ).all()

        deleted_count = len(inactive_guests)
        for user in inactive_guests:
            session.delete(user)

        session.commit()
        logging.info(f"[RETENTION] Purged {deleted_count} inactive guest accounts (inactive for >{inactivity_days} days).")
        return {'purged_guests': deleted_count}
    except Exception as e:
        session.rollback()
        logging.error(f"[RETENTION_ERROR] Failed to purge guest accounts: {e}", exc_info=True)
        return {'purged_guests': 0}
    finally:
        Session.remove()

def purge_expired_jwt_blocklist():
    """
    Purges JWT tokens from the blocklist whose expiration date has passed.
    """
    session = Session()
    try:
        now = datetime.utcnow()
        deleted = session.query(JWTBlocklist).filter(
            JWTBlocklist.expires_at < now
        ).delete(synchronize_session=False)

        session.commit()
        if deleted > 0:
            logging.info(f"[RETENTION] Purged {deleted} expired JWT blocklist entries.")
        return {'purged_jwts': deleted}
    except Exception as e:
        session.rollback()
        logging.error(f"[RETENTION_ERROR] Failed to purge JWT blocklist: {e}", exc_info=True)
        return {'purged_jwts': 0}
    finally:
        Session.remove()

def run_all_retention_tasks(retention_days=90):
    """Runs all retention cleanup operations."""
    res_events = purge_expired_notification_events(retention_days=retention_days)
    res_guests = purge_inactive_guest_accounts(inactivity_days=retention_days)
    res_jwts = purge_expired_jwt_blocklist()
    return {**res_events, **res_guests, **res_jwts}
