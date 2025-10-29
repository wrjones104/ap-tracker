from sqlalchemy import (
    create_engine, Column, Integer, String, ForeignKey, DateTime, 
    UniqueConstraint, Boolean, ForeignKeyConstraint
)
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, nullable=False, unique=True, index=True)
    discord_username = Column(String, nullable=False)
    discord_avatar_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    subscriptions = relationship("UserRoomSubscription", back_populates="user", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
    notify_progression_default = Column(Boolean, default=True, nullable=False)
    notify_useful_default = Column(Boolean, default=True, nullable=False)
    notify_hints_default = Column(Boolean, default=True, nullable=False)

class Device(Base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    fcm_token = Column(String, nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    user = relationship("User", back_populates="devices")

class TrackedRoom(Base):
    __tablename__ = 'tracked_rooms'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, unique=True, index=True)
    hostname = Column(String, default="archipelago.gg")
    tracker_id = Column(String)
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
    notify_progression = Column(Boolean, nullable=True, default=None)
    notify_useful = Column(Boolean, nullable=True, default=None)
    notify_hints = Column(Boolean, nullable=True, default=None)
    
    __table_args__ = (
        ForeignKeyConstraint(['user_id', 'room_id'], ['user_room_subscriptions.user_id', 'user_room_subscriptions.room_id']),
        UniqueConstraint('user_id', 'room_id', 'slot_id', name='_user_room_slot_uc'),
    )
    subscription = relationship("UserRoomSubscription", back_populates="tracked_slots")

class DatapackageCache(Base):
    __tablename__ = 'datapackage_cache'
    id = Column(Integer, primary_key=True)
    game = Column(String, nullable=False, index=True)
    checksum = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False)
    entity_name = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('game', 'checksum', 'entity_type', 'entity_id', name='_game_checksum_entity_uc'),)

class NotifiedItem(Base):
    __tablename__ = 'notified_items'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, index=True) 
    receiving_slot_id = Column(Integer, nullable=False)
    item_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('room_id', 'receiving_slot_id', 'item_id', 'location_id', name='_item_event_uc'),)

class NotifiedHint(Base):
    __tablename__ = 'notified_hints'
    id = Column(Integer, primary_key=True)
    room_id = Column(String, nullable=False, index=True) 
    item_owner_id = Column(Integer, nullable=False)
    location_owner_id = Column(Integer, nullable=False)
    item_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_found = Column(Boolean, default=False, nullable=False)
    __table_args__ = (UniqueConstraint('room_id', 'item_id', 'location_id', 'item_owner_id', 'location_owner_id', name='_hint_event_uc'),)