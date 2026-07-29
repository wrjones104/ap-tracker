import logging
import json
from sqlalchemy import exists
from sqlalchemy.orm import aliased
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app import Session, is_sqlite
from app.models import DatapackageCache
from app.services.redis_service import cache_get, cache_set

def db_get_missing_checksums(checksums_to_check):
    """
    Checks database cache for missing or outdated game checksums.
    """
    if not checksums_to_check:
        return set()
    session = Session()
    try:
        completed_old_checksums = [c[0] for c in session.query(DatapackageCache.checksum).filter(
            DatapackageCache.checksum.in_(checksums_to_check),
            DatapackageCache.entity_type == '_metadata',
            DatapackageCache.entity_name == '_completed'
        ).all()]
        
        completed_v2_checksums = [c[0] for c in session.query(DatapackageCache.checksum).filter(
            DatapackageCache.checksum.in_(checksums_to_check),
            DatapackageCache.entity_type == '_metadata',
            DatapackageCache.entity_name == '_completed_v2'
        ).all()]
        
        checksums_to_delete = set(completed_old_checksums)
        
        if completed_v2_checksums:
            D2 = aliased(DatapackageCache)
            checksums_without_data = [c[0] for c in session.query(DatapackageCache.checksum).filter(
                DatapackageCache.checksum.in_(completed_v2_checksums),
                DatapackageCache.entity_type == '_metadata',
                DatapackageCache.entity_name == '_completed_v2',
                ~exists().where(
                    (D2.checksum == DatapackageCache.checksum) &
                    D2.entity_type.in_(['item', 'location'])
                )
            ).all() if c and c[0]]
            
            for chk in checksums_without_data:
                checksums_to_delete.add(chk)

            has_groups = set(c[0] for c in session.query(DatapackageCache.checksum).filter(
                DatapackageCache.checksum.in_(completed_v2_checksums),
                DatapackageCache.entity_type == 'item_group'
            ).distinct().all() if c and c[0])
            
            has_json = set(c[0] for c in session.query(DatapackageCache.checksum).filter(
                DatapackageCache.checksum.in_(completed_v2_checksums),
                DatapackageCache.entity_type == 'item_name_groups_json'
            ).distinct().all() if c and c[0])
            
            bad_checksums = list(has_groups - has_json)
            for chk in bad_checksums:
                checksums_to_delete.add(chk)
                    
        if checksums_to_delete:
            for chk in checksums_to_delete:
                logging.info(f"[SELF_HEALING] Checksum {chk} is outdated. Clearing from cache.")
            session.query(DatapackageCache).filter(DatapackageCache.checksum.in_(list(checksums_to_delete))).delete(synchronize_session=False)
            session.commit()

        existing = set(c[0] for c in session.query(DatapackageCache.checksum).filter(
            DatapackageCache.checksum.in_(checksums_to_check),
            DatapackageCache.entity_type == '_metadata',
            DatapackageCache.entity_name.in_(['_completed_v2', '_empty_datapackage'])
        ).distinct())
        return set(checksums_to_check) - existing
    except Exception as e:
        logging.error(f"[POLLER_DB_ERROR] Failed to check missing checksums: {e}")
        return set()
    finally:
        Session.remove()

def db_cache_datapackage(entries):
    """
    Caches a game's datapackage entries in DB and syncs into Redis cache.
    """
    if not entries:
        return
    session = Session()
    try:
        checksum = entries[0].checksum
        session.query(DatapackageCache).filter_by(checksum=checksum).delete()
        
        insert_stmt = sqlite_insert if is_sqlite else pg_insert
        values = [
            {
                'game': e.game,
                'checksum': e.checksum,
                'entity_type': e.entity_type,
                'entity_id': e.entity_id,
                'entity_name': e.entity_name
            }
            for e in entries
        ]
        
        chunk_size = 500
        for i in range(0, len(values), chunk_size):
            chunk = values[i:i + chunk_size]
            stmt = insert_stmt(DatapackageCache).values(chunk)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['checksum', 'entity_type', 'entity_id']
            )
            session.execute(stmt)
            session.commit()
            
    except Exception as e:
        session.rollback()
        logging.error(f"[POLLER_DB_ERROR] Failed to save datapackage: {e}", exc_info=True)
        raise e
    finally:
        Session.remove()

def resolve_entity_name(checksum, entity_type, entity_id, fallback_name=None):
    """
    Resolves item/location name using Redis in-memory cache first,
    falling back to database lookup on cache miss.
    """
    cache_key = f"dp:{checksum}:{entity_type}:{entity_id}"
    cached_val = cache_get(cache_key)
    if cached_val is not None:
        return cached_val

    session = Session()
    try:
        entry = session.query(DatapackageCache.entity_name).filter_by(
            checksum=checksum,
            entity_type=entity_type,
            entity_id=entity_id
        ).first()
        if entry and entry[0]:
            cache_set(cache_key, entry[0], ttl_seconds=86400 * 7)
            return entry[0]
        return fallback_name or f"{entity_type.capitalize()} ID {entity_id}"
    finally:
        Session.remove()
