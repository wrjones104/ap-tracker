import uuid

from sqlalchemy import (
    create_engine, Column, Integer, String, ForeignKey, DateTime, 
    UniqueConstraint, Boolean, ForeignKeyConstraint, BigInteger,
    Index
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
    cheese_api_key = Column(String, nullable=True)
    cheese_user_id = Column(Integer, nullable=True)
    cheese_last_sync = Column(DateTime, nullable=True)
    is_syncing_cheese = Column(Boolean, nullable=False, default=False, server_default='f')
    cheese_sync_started_at = Column(DateTime, nullable=True)
    is_guest = Column(Boolean, nullable=False, default=True, server_default='t')
    guest_uuid = Column(String, nullable=True, unique=True, index=True)
    subscriptions = relationship("UserRoomSubscription", back_populates="user", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
    notify_progression_default = Column(Boolean, default=True, nullable=False)
    notify_useful_default = Column(Boolean, default=True, nullable=False)
    notify_hints_default = Column(Boolean, default=True, nullable=False)
    notify_finished_default = Column(Boolean, default=False, nullable=False)
    notify_hints_remote_items_default = Column(Boolean, default=True, nullable=False)
    ignore_items = relationship("UserIgnoreItem", back_populates="user", cascade="all, delete-orphan")

class Device(Base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    fcm_token = Column(String, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    android_id = Column(String, nullable=True, index=True)
    user = relationship("User", back_populates="devices")
    __table_args__ = (
        UniqueConstraint('user_id', 'android_id', name='_user_android_id_uc'),
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
    is_setup = Column(Boolean, default=False, nullable=False)
    subscriptions = relationship("UserRoomSubscription", back_populates="room", cascade="all, delete-orphan")

class UserRoomSubscription(Base):
    __tablename__ = 'user_room_subscriptions'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    room_id = Column(Integer, ForeignKey('tracked_rooms.id'), primary_key=True)
    alias = Column(String, nullable=False)
    icon_name = Column(String, default="default_icon")
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
    notify_progression = Column(Boolean, nullable=True, default=None)
    notify_useful = Column(Boolean, nullable=True, default=None)
    notify_hints = Column(Boolean, nullable=True, default=None)
    notify_hints_remote_items = Column(Boolean, nullable=True, default=None)
    notify_finished = Column(Boolean, nullable=True, default=None)
    user = relationship("User", viewonly=True)    
    
    __table_args__ = (
        ForeignKeyConstraint(['user_id', 'room_id'], ['user_room_subscriptions.user_id', 'user_room_subscriptions.room_id']),
        UniqueConstraint('user_id', 'room_id', 'slot_id', name='_user_room_slot_uc'),
    )
    subscription = relationship("UserRoomSubscription", back_populates="tracked_slots")

class UserIgnoreItem(Base):
    __tablename__ = 'user_ignore_items'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    item_name = Column(String(255), nullable=False)
    game_name = Column(String(255), nullable=True) 
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    user = relationship("User", back_populates="ignore_items")

    __table_args__ = (
        UniqueConstraint('user_id', 'item_name', 'game_name', name='_user_ignore_item_uc'),
    )

class DatapackageCache(Base):
    __tablename__ = 'datapackage_cache'
    id = Column(Integer, primary_key=True)
    game = Column(String, nullable=False, index=True)
    checksum = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(BigInteger, nullable=False)
    entity_name = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('game', 'checksum', 'entity_type', 'entity_id', name='_game_checksum_entity_uc'),)

class NotifiedItem(Base):
    __tablename__ = 'notified_items'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, index=True) 
    receiving_slot_id = Column(Integer, nullable=False)
    sending_slot_id = Column(Integer, nullable=True) 
    item_id = Column(BigInteger, nullable=False)
    location_id = Column(BigInteger, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    item_flags = Column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint('room_id', 'receiving_slot_id', 'item_id', 'location_id', name='_item_event_uc'),
        Index('ix_notifieditem_timestamp', 'timestamp'),
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
    is_found = Column(Boolean, default=False, nullable=False)
    __table_args__ = (
        UniqueConstraint('room_id', 'item_id', 'location_id', 'item_owner_id', 'location_owner_id', name='_hint_event_uc'),
        Index('ix_notifiedhint_timestamp', 'timestamp'), # <-- ADDED THIS
    )

class JWTBlocklist(Base):
    __tablename__ = 'jwt_blocklist'
    id = Column(Integer, primary_key=True)
    jti = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)