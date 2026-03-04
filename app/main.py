# app/conversation.py
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Response, HTTPException
app = FastAPI()
from datetime import datetime, timezone
from typing import Dict, Any, Optional


from .whatsapp import send_text, send_buttons

try:
    from .ms_graph_excel import append_row_to_sharepoint_excel
except Exception:
    append_row_to_sharepoint_excel = None



from .settings import settings
from .conversation import handle_input, set_db_context, get_session

from app.db import SessionLocal
from app.repository import (
    get_or_create_user,
    get_or_create_open_lead,
    start_conversation,
    log_message,
    update_conversation_state,
)

@app.get("/whatsapp/webhook")
async def verify_whatsapp_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN and challenge:
        return Response(content=challenge, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Webhook verification failed")


def _extract_contact_name(value: dict) -> str | None:
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
            value = change.get("value", {})

            contact_name = _extract_contact_name(value)

            messages = value.get("messages")
            if not messages:
                continue

            for msg in messages:
                user_id = msg.get("from")
                if not user_id:
                    continue

                wa_message_id = msg.get("id")
                msg_type = msg.get("type")

                text = None
                button_id = None

                if msg_type == "text":
                    text = (msg.get("text") or {}).get("body")

                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    i_type = interactive.get("type")
                    if i_type == "button_reply":
                        button_id = (interactive.get("button_reply") or {}).get("id")

                # ✅ DB log + contexto
                db = SessionLocal()
                try:
                    user = get_or_create_user(db, wa_user_id=user_id, phone=user_id, full_name=contact_name)
                    lead = get_or_create_open_lead(db, user.id, source="whatsapp")

                    session = get_session(user_id)
                    current_state = session.get("state")

                    conv = start_conversation(db, user.id, lead.id, state=current_state)

                    set_db_context(user_id, conversation_id=conv.id, lead_id=lead.id)

                    log_message(
                        db,
                        conversation_id=conv.id,
                        direction="in",
                        text=text,
                        button_id=button_id,
                        wa_message_id=wa_message_id,
                    )

                    await handle_input(user_id=user_id, text=text, button_id=button_id)

                    session2 = get_session(user_id)
                    update_conversation_state(db, conv.id, session2.get("state"))
                finally:
                    db.close()

    return {"ok": True}