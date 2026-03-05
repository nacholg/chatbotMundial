# app/models.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from .db import Base

class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)

    state = Column(String(64), nullable=False, default="START")
    data = Column(JSONB, nullable=False, default=dict)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    wa_user_id = Column(String(64), unique=True, index=True, nullable=False)  # tu user_id interno / wa id
    phone = Column(String(32), unique=True, index=True, nullable=True)
    full_name = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    leads = relationship("Lead", back_populates="user")
    conversations = relationship("Conversation", back_populates="user")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, index=True, nullable=False)  # ej: "MIA-R16-03JUL"
    name = Column(String(200), nullable=False)
    city = Column(String(80), nullable=True)
    venue = Column(String(120), nullable=True)
    start_at = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, default=True, nullable=False)

    selections = relationship("LeadSelection", back_populates="event")


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    status = Column(String(32), nullable=False, default="open")  # open / qualified / won / lost
    source = Column(String(50), nullable=True)  # whatsapp / ig / etc
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="leads")
    selections = relationship("LeadSelection", back_populates="lead", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="lead")


class LeadSelection(Base):
    __tablename__ = "lead_selections"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)

    quantity = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lead = relationship("Lead", back_populates="selections")
    event = relationship("Event", back_populates="selections")

    __table_args__ = (
        UniqueConstraint("lead_id", "event_id", name="uq_lead_event"),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True, index=True)

    state = Column(String(64), nullable=True)  # tu FSM state
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="conversations")
    lead = relationship("Lead", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)

    direction = Column(String(8), nullable=False)  # "in" / "out"
    text = Column(Text, nullable=True)
    button_id = Column(String(80), nullable=True)
    wa_message_id = Column(String(120), nullable=True, unique=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="messages")