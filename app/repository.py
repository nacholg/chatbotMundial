# app/repository.py
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models import User, Lead, Conversation, Message


def get_or_create_user(db: Session, wa_user_id: str, phone: str | None = None, full_name: str | None = None) -> User:
    user = db.query(User).filter(User.wa_user_id == wa_user_id).first()
    if user:
        if phone and not user.phone:
            user.phone = phone
        if full_name and not user.full_name:
            user.full_name = full_name
        db.commit()
        db.refresh(user)
        return user

    user = User(wa_user_id=wa_user_id, phone=phone, full_name=full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_or_create_open_lead(db: Session, user_id: int, source: str = "whatsapp") -> Lead:
    lead = (
        db.query(Lead)
        .filter(Lead.user_id == user_id, Lead.status == "open")
        .order_by(desc(Lead.id))
        .first()
    )
    if lead:
        return lead
    lead = Lead(user_id=user_id, status="open", source=source)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def start_conversation(db: Session, user_id: int, lead_id: int | None, state: str | None = None) -> Conversation:
    conv = Conversation(user_id=user_id, lead_id=lead_id, state=state)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def log_message(
    db: Session,
    conversation_id: int,
    direction: str,
    text: str | None = None,
    button_id: str | None = None,
    wa_message_id: str | None = None,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        direction=direction,
        text=text,
        button_id=button_id,
        wa_message_id=wa_message_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def update_conversation_state(db: Session, conversation_id: int, state: str | None) -> None:
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        return
    conv.state = state
    db.commit()