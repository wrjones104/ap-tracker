import uuid

from sqlalchemy import (
    create_engine, func, Column, Integer, String, ForeignKey, DateTime, 
    UniqueConstraint, Boolean, ForeignKeyConstraint, BigInteger,
    Index, false as sa_false
)
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, nullable=True, unique=True, index=True)
    discord_username = Column(String, nullable=True)
    discord_avatar_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    cheese_api_key = Column(String, nullable=True)
    cheese_user_id = Column(Integer, nullable=True)
    cheese_last_sync = Column(DateTime, nullable=True)
    # How many slots the most recent Cheese sync demoted from play to watch
    # because Cheese did not confirm them as this user's. Surfaced by the app
    # as a post-sync summary; the client decides when it has been seen by
    # comparing against cheese_last_sync.
    cheese_last_sync_demoted = Column(Integer, nullable=False, default=0, server_default='0')
    # How many linked rooms the most recent sync found missing from the user's
    # Cheese dashboard. Nothing is removed on the strength of it; the app shows
    # the affected rooms so the user can decide.
    cheese_last_sync_unlisted = Column(Integer, nullable=False, default=0, server_default='0')
    is_syncing_cheese = Column(Boolean, nullable=False, default=False, server_default='f')
    cheese_sync_started_at = Column(DateTime, nullable=True)
    # Default Cheese Tracker ping preference applied at claim time. Null = leave
    # whatever value the game already has on Cheese untouched. One of:
    # liberally | sparingly | hints | see_notes | never
    cheese_default_ping = Column(String, nullable=True)
    # Default for the "Also create this on Cheese Tracker" choice in the add-room
    # dialog. A default for a per-room decision, not a sync mode: it only seeds
    # the checkbox, and the room's own cheese_link is what actually authorises a
    # push. Defaults to true, which is what every connected user had before the
    # choice existed.
    cheese_publish_new_rooms = Column(Boolean, nullable=False, default=True, server_default='t')
    is_guest = Column(Boolean, nullable=False, default=True, server_default='t')
    guest_uuid = Column(String, nullable=True, unique=True, index=True)
    subscriptions = relationship("UserRoomSubscription", back_populates="user", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
    notify_progression_default = Column(Boolean, default=True, nullable=False)
    notify_useful_default = Column(Boolean, default=True, nullable=False)
    notify_hints_default = Column(Boolean, default=True, nullable=False)
    notify_finished_default = Column(Boolean, default=False, nullable=False)
    notify_hints_remote_items_default = Column(Boolean, default=True, nullable=False)
    combine_notifications_default = Column(Boolean, default=False, nullable=False)
    suppress_own_events_default = Column(Boolean, default=True, nullable=False)
    remove_emojis_default = Column(Boolean, default=False, nullable=False)
    suppress_self_found_default = Column(Boolean, default=True, nullable=False)
    use_condensed_messages_default = Column(Boolean, default=False, nullable=False)
    suppress_connected_default = Column(Boolean, default=False, nullable=False)
    ui_show_finished_default = Column(Boolean, default=True, nullable=False)
    ui_show_found_hints_default = Column(Boolean, default=False, nullable=False)
    ui_show_progression_default = Column(Boolean, default=True, nullable=False)
    ui_show_useful_default = Column(Boolean, default=True, nullable=False)
    notify_filler_default = Column(Boolean, default=False, nullable=False)
    notify_trap_default = Column(Boolean, default=False, nullable=False)
    ui_show_filler_default = Column(Boolean, default=True, nullable=False)
    ui_show_trap_default = Column(Boolean, default=True, nullable=False)
    # What counts as a "finished" slot for visibility filters and notification
    # suppression. One of: goal | all_checks | both | either. Anything else is
    # treated as 'goal'. Does NOT affect TrackedRoom.is_complete, which is
    # always goal-only. See evaluate_finished() in app/utils.py.
    finished_definition_default = Column(String(16), default='goal', nullable=False, server_default='goal')
    global_snooze_until = Column(DateTime, nullable=True)
    ignore_items = relationship("UserIgnoreItem", back_populates="user", cascade="all, delete-orphan")
    whitelist_items = relationship("UserWhitelistItem", back_populates="user", cascade="all, delete-orphan")

class Device(Base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    fcm_token = Column(String, nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    android_id = Column(String, nullable=True, index=True)
    platform = Column(String, nullable=False, default='android', server_default='android')
    user = relationship("User", back_populates="devices")
    __table_args__ = (
        UniqueConstraint('user_id', 'android_id', 'platform', name='_user_android_id_uc'),
    )

class TrackedRoom(Base):
    __tablename__ = 'tracked_rooms'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, unique=True, index=True)
    hostname = Column(String, default="archipelago.gg")
    tracker_id = Column(String)
    cheese_tracker_id = Column(String, unique=True, nullable=True)
    cached_cheese_json = Column(String, nullable=True)
    cheese_updated_at = Column(DateTime, nullable=True)
    game_checksums_json = Column(String, default='{}')
    is_complete = Column(Boolean, default=False, nullable=False)
    is_suspended = Column(Boolean, default=False, nullable=False)
    last_successful_poll = Column(DateTime)
    failed_poll_count = Column(Integer, default=0, nullable=False)
    cached_full_address = Column(String, default="archipelago.gg")
    cached_total_slots = Column(Integer, default=0)
    last_api_check = Column(DateTime)
    cached_players_json = Column(String, default='[]')
    # {slot_id: checks_done_count}. Deliberately kept out of cached_players_json:
    # that column is TOASTed for any room past ~15 slots and is only rewritten
    # when a finished flag flips, so folding a per-poll counter into it would
    # rewrite the whole TOAST value every poll. This one stays small enough to
    # live inline. Only assigned when a count actually changed.
    cached_checks_json = Column(String, default='{}', server_default='{}')
    is_setup = Column(Boolean, default=False, nullable=False)
    last_remote_activity = Column(DateTime, nullable=True)
    last_revive_attempt = Column(DateTime, nullable=True)
    needs_immediate_poll = Column(Boolean, default=False, nullable=False)
    subscriptions = relationship("UserRoomSubscription", back_populates="room", cascade="all, delete-orphan")

class UserRoomSubscription(Base):
    __tablename__ = 'user_room_subscriptions'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    room_id = Column(Integer, ForeignKey('tracked_rooms.id'), primary_key=True)
    alias = Column(String, nullable=False)
    icon_name = Column(String, default="default_icon")
    is_archived = Column(Boolean, default=False, nullable=False)
    # Whether this room mirrors to Cheese Tracker for this user: 'none' or
    # 'linked'. See VALID_CHEESE_LINKS in app/utils.py. Per-subscription rather than
    # per-room, because TrackedRoom.cheese_tracker_id is shared by everyone
    # tracking that room while the decision to mirror is one user's.
    cheese_link = Column(String(16), default='none', nullable=False, server_default='none')
    # Set when a sync finds a linked room missing from the user's Cheese
    # dashboard, cleared when it comes back. Purely a flag for the app to show:
    # nothing is ever removed on the strength of it.
    cheese_unlisted_at = Column(DateTime, nullable=True)
    user = relationship("User", back_populates="subscriptions")
    room = relationship("TrackedRoom", back_populates="subscriptions")
    tracked_slots = relationship("UserTrackedSlot", back_populates="subscription", cascade="all, delete-orphan")

class UserTrackedSlot(Base):
    __tablename__ = 'user_tracked_slots'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    room_id = Column(Integer, ForeignKey('tracked_rooms.id'), nullable=False)
    slot_id = Column(Integer, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)
    needs_backfill = Column(Boolean, default=True, nullable=False)
    # Separates "alert me about this slot" from "this slot is mine on Cheese
    # Tracker". One of:
    #   play  -- I am playing this slot. Claimed on Cheese, kept in sync.
    #   watch -- Alerts only. Never written to Cheese, never unclaimed by sync.
    # Meaningful for any Cheese-connected user, including before the room is
    # linked to a tracker: the picker offers the choice from the start, and the
    # link catch-up honours it rather than claiming everything it finds.
    # Without a Cheese key there is nothing to claim, so every slot is 'play'.
    # See TRACK_MODES in app/utils.py.
    track_mode = Column(String(16), nullable=False, default='play', server_default='play')
    notify_progression = Column(Boolean, nullable=True, default=None)
    notify_useful = Column(Boolean, nullable=True, default=None)
    notify_hints = Column(Boolean, nullable=True, default=None)
    notify_hints_remote_items = Column(Boolean, nullable=True, default=None)
    notify_finished = Column(Boolean, nullable=True, default=None)
    notify_filler = Column(Boolean, nullable=True, default=None)
    notify_trap = Column(Boolean, nullable=True, default=None)
    combine_notifications = Column(Boolean, nullable=True, default=None)
    suppress_own_events = Column(Boolean, nullable=True, default=None)
    remove_emojis = Column(Boolean, nullable=True, default=None)
    suppress_self_found = Column(Boolean, nullable=True, default=None)
    use_condensed_messages = Column(Boolean, nullable=True, default=None)
    suppress_connected = Column(Boolean, nullable=True, default=None)
    # Per-slot override for User.finished_definition_default. Null = inherit.
    finished_definition = Column(String(16), nullable=True, default=None)
    snooze_until = Column(DateTime, nullable=True)
    snooze_wake_on_slot_id = Column(Integer, nullable=True)
    # Set only when a slot is newly tracked in 'play' mode, and cleared by the first poll
    # that resolves the slot's game and datapackage checksum. Existing rows default to
    # False so turning auto-apply on never reaches backwards into a library of old slots:
    # the feature is forward-only by construction. See services/milestone_template_service.
    auto_apply_pending = Column(Boolean, nullable=False, default=False, server_default=sa_false())
    user = relationship("User", viewonly=True)    
    
    __table_args__ = (
        ForeignKeyConstraint(['user_id', 'room_id'], ['user_room_subscriptions.user_id', 'user_room_subscriptions.room_id']),
        UniqueConstraint('user_id', 'room_id', 'slot_id', name='_user_room_slot_uc'),
        Index('ix_usertrackedslot_user_room', 'user_id', 'room_id'),
    )
    subscription = relationship("UserRoomSubscription", back_populates="tracked_slots")
    threshold_groups = relationship("ThresholdGroup", back_populates="tracked_slot", cascade="all, delete-orphan")

class ThresholdGroup(Base):
    __tablename__ = 'threshold_groups'
    id = Column(Integer, primary_key=True)
    user_tracked_slot_id = Column(Integer, ForeignKey('user_tracked_slots.id'), nullable=False)
    name = Column(String(255), nullable=True)
    is_triggered = Column(Boolean, default=False, nullable=False)
    
    tracked_slot = relationship("UserTrackedSlot", back_populates="threshold_groups")
    items = relationship("ThresholdGroupItem", back_populates="group", cascade="all, delete-orphan")

class ThresholdGroupItem(Base):
    __tablename__ = 'threshold_group_items'
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('threshold_groups.id'), nullable=False)
    item_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    is_group = Column(Boolean, default=False, nullable=False)
    
    group = relationship("ThresholdGroup", back_populates="items")

class MilestoneTemplate(Base):
    __tablename__ = 'milestone_templates'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    game_name = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # "Always add this template to new slots I play for this game." Applied by the poller
    # on the first poll that knows the slot's game, never retroactively.
    auto_apply = Column(Boolean, nullable=False, default=False, server_default=sa_false())

    user = relationship("User", viewonly=True)
    items = relationship("MilestoneTemplateItem", back_populates="template", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('user_id', 'game_name', 'name', name='_user_game_template_uc'),
    )


class MilestoneTemplateItem(Base):
    __tablename__ = 'milestone_template_items'
    id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey('milestone_templates.id'), nullable=False)
    item_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    is_group = Column(Boolean, nullable=False, default=False)

    template = relationship("MilestoneTemplate", back_populates="items")


class UserIgnoreItem(Base):
    __tablename__ = 'user_ignore_items'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    item_name = Column(String(255), nullable=False)
    game_name = Column(String(255), nullable=True) 
    is_group = Column(Boolean, default=False, nullable=False, server_default='f')
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    user = relationship("User", back_populates="ignore_items")

    __table_args__ = (
        UniqueConstraint('user_id', 'item_name', 'game_name', name='_user_ignore_item_uc'),
    )

class CheeseDismissedTracker(Base):
    """
    A Cheese tracker the user has said they do not want in the app.

    The app offers newly-seen dashboard trackers as suggestions rather than
    importing them, so it needs somewhere to remember a "no". Without this the
    same room is offered again on the next sync, which is the nagging version of
    the auto-import this replaced. Adding the room later is unaffected: the
    import path clears the row.
    """
    __tablename__ = 'cheese_dismissed_trackers'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    cheese_tracker_id = Column(String(64), nullable=False)
    dismissed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'cheese_tracker_id', name='_user_dismissed_tracker_uc'),
    )

class UserWhitelistItem(Base):
    __tablename__ = 'user_whitelist_items'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    item_name = Column(String(255), nullable=False)
    game_name = Column(String(255), nullable=True)
    is_group = Column(Boolean, default=False, nullable=False, server_default='f')
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="whitelist_items")

    __table_args__ = (
        UniqueConstraint('user_id', 'item_name', 'game_name', name='_user_whitelist_item_uc'),
    )

class DatapackageCache(Base):
    __tablename__ = 'datapackage_cache'
    id = Column(Integer, primary_key=True)
    game = Column(String, nullable=False, index=True)
    checksum = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(BigInteger, nullable=False)
    entity_name = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('checksum', 'entity_type', 'entity_id', name='_checksum_entity_uc'),)

class NotifiedItem(Base):
    __tablename__ = 'notified_items'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, index=True) 
    receiving_slot_id = Column(Integer, nullable=False)
    sending_slot_id = Column(Integer, nullable=True) 
    item_id = Column(BigInteger, nullable=False)
    location_id = Column(BigInteger, nullable=False)
    item_index = Column(Integer, nullable=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    item_flags = Column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint('room_id', 'receiving_slot_id', 'item_index', name='_item_event_index_uc'),
        Index('ix_notifieditem_timestamp', 'timestamp'),
        Index('ix_notifieditem_room_receiving_time', 'room_id', 'receiving_slot_id', 'timestamp'),
    )

class NotifiedHint(Base):
    __tablename__ = 'notified_hints'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, index=True) 
    item_owner_id = Column(Integer, nullable=False)
    location_owner_id = Column(Integer, nullable=False)
    item_id = Column(BigInteger, nullable=False)
    location_id = Column(BigInteger, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)
    is_found = Column(Boolean, default=False, nullable=False)
    item_flags = Column(Integer, default=0)
    __table_args__ = (
        UniqueConstraint('room_id', 'item_id', 'location_id', 'item_owner_id', 'location_owner_id', name='_hint_event_uc'),
        Index('ix_notifiedhint_timestamp', 'timestamp'), 
        Index('ix_notifiedhint_room_owner_time', 'room_id', 'item_owner_id', 'timestamp'),
    )

class JWTBlocklist(Base):
    __tablename__ = 'jwt_blocklist'
    id = Column(Integer, primary_key=True)
    jti = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)

class SlotItemCount(Base):
    __tablename__ = 'slot_item_counts'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, ForeignKey('tracked_rooms.room_id'), nullable=False)
    slot_id = Column(Integer, nullable=False)
    item_id = Column(BigInteger, nullable=False)
    count = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint('room_id', 'slot_id', 'item_id', name='_slot_item_count_uc'),
    )