# app/main.py
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Response, HTTPException
from typing import Optional

from .settings import settings
from .conversation import handle_input, set_db_context, get_session

from app.db import SessionLocal
from app.repository import (
    message_exists,
    get_or_create_user,
    get_or_create_open_lead,
    get_or_create_open_conversation,  # ✅ NUEVO (reusa conversación)
    log_message,
    update_conversation_state,
)

app = FastAPI()


@app.get("/whatsapp/webhook")
async def verify_whatsapp_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN and challenge:
        return Response(content=challenge, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Webhook verification failed")


def _extract_contact_name(value: dict) -> Optional[str]:
    contacts = value.get("contacts") or []
    if contacts and isinstance(contacts, list):
        prof = (contacts[0] or {}).get("profile") or {}
        name = prof.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


@app.post("/whatsapp/webhook")
async def receive_whatsapp_webhook(request: Request):
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {}) or {}

            contact_name = _extract_contact_name(value)

            messages = value.get("messages") or []
            if not messages:
                continue

            for msg in messages:
                user_id = msg.get("from")
                if not user_id:
                    continue

                wa_message_id = msg.get("id")  # ✅ clave dedupe
                msg_type = msg.get("type")

                text = None
                button_id = None

                if msg_type == "text":
                    text = (msg.get("text") or {}).get("body")

                elif msg_type == "interactive":
                    interactive = msg.get("interactive") or {}
                    i_type = interactive.get("type")
                    if i_type == "button_reply":
                        button_id = (interactive.get("button_reply") or {}).get("id")
                    # si más adelante usan list_reply, se suma acá

                db = SessionLocal()
                try:
                    # ✅ FIX PRO: dedupe primero (antes de crear user/lead/conv)
                    if wa_message_id and message_exists(db, wa_message_id):
                        print("[DEBUG] duplicate message (db) ignored:", wa_message_id)
                        continue

                    # Entities
                    user = get_or_create_user(db, wa_user_id=user_id, phone=user_id, full_name=contact_name)
                    lead = get_or_create_open_lead(db, user.id, source="whatsapp")

                    # Estado actual desde tu session store (Postgres)
                    session = get_session(user_id)
                    current_state = session.get("state")

                    # ✅ Reusar conversación del lead (en vez de crear una nueva por msg)
                    conv = get_or_create_open_conversation(
                        db,
                        user_id=user.id,
                        lead_id=lead.id,
                        state=current_state,
                    )

                    # Contexto: tu conversation.py usa esto para loguear OUT en la misma conv
                    set_db_context(user_id, conversation_id=conv.id, lead_id=lead.id)

                    # Log IN
                    log_message(
                        db,
                        conversation_id=conv.id,
                        direction="in",
                        text=text,
                        button_id=button_id,
                        wa_message_id=wa_message_id,
                    )

                    # Flow
                    await handle_input(user_id=user_id, text=text, button_id=button_id)

                    # Persistir state actualizado
                    session2 = get_session(user_id)
                    update_conversation_state(db, conv.id, session2.get("state"))

                finally:
                    db.close()

    return {"ok": True}