# app/session_store.py
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session as OrmSession

from app.db import SessionLocal
from app.models import User, Session as BotSession


DEFAULT_STATE = "START"


def _ensure_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def get_session_state_data_by_wa_user_id(wa_user_id: str) -> tuple[str, Dict[str, Any]]:
    """
    Devuelve (state, data) para ese wa_user_id.
    Si no existe, lo crea (requiere que users exista).
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.wa_user_id == wa_user_id).first()
        if not user:
            # No lo creamos acá para no duplicar lógica.
            # main.py ya hace get_or_create_user antes de llamar a conversation.
            return DEFAULT_STATE, {"data": {}}

        s = db.query(BotSession).filter(BotSession.user_id == user.id).first()
        if not s:
            s = BotSession(user_id=user.id, state=DEFAULT_STATE, data={})
            db.add(s)
            db.commit()
            db.refresh(s)

        return s.state or DEFAULT_STATE, _ensure_dict(s.data)
    finally:
        db.close()


def save_session_by_wa_user_id(wa_user_id: str, state: str, data: Dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.wa_user_id == wa_user_id).first()
        if not user:
            return

        s = db.query(BotSession).filter(BotSession.user_id == user.id).first()
        if not s:
            s = BotSession(user_id=user.id, state=state, data=data or {})
            db.add(s)
        else:
            s.state = state
            s.data = data or {}
        db.commit()
    finally:
        db.close()


def reset_session_by_wa_user_id(wa_user_id: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.wa_user_id == wa_user_id).first()
        if not user:
            return

        s = db.query(BotSession).filter(BotSession.user_id == user.id).first()
        if not s:
            s = BotSession(user_id=user.id, state=DEFAULT_STATE, data={})
            db.add(s)
        else:
            s.state = DEFAULT_STATE
            s.data = {}
        db.commit()
    finally:
        db.close()