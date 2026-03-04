# app/whatsapp.py
from __future__ import annotations

import httpx
from typing import Any, Dict, List, Optional

from .settings import settings


def _wa_url() -> str:
    api_version = settings.WHATSAPP_API_VERSION or "v19.0"
    return f"https://graph.facebook.com/{api_version}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


async def _post(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = _wa_url()
    headers = _auth_headers()

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code >= 400:
        print("WHATSAPP API ERROR:", r.status_code, r.text)
        r.raise_for_status()

    return r.json()


def _log_outgoing_best_effort(
    *,
    conversation_id: Optional[int],
    text: Optional[str],
    button_id: Optional[str] = None,
) -> None:
    """No rompe el envío si falla DB."""
    if not conversation_id:
        return
    try:
        from app.db import SessionLocal
        from app.repository import log_message

        db = SessionLocal()
        try:
            log_message(
                db,
                conversation_id=conversation_id,
                direction="out",
                text=text,
                button_id=button_id,
                wa_message_id=None,
            )
        finally:
            db.close()
    except Exception as e:
        print("[DB] outbound log failed:", repr(e))


async def send_text(to: str, text: str, conversation_id: Optional[int] = None) -> Dict[str, Any]:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    res = await _post(payload)

    _log_outgoing_best_effort(conversation_id=conversation_id, text=text)

    return res


async def send_buttons(
    to: str,
    body_text: str,
    buttons: List[Dict[str, str]],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
    conversation_id: Optional[int] = None,
) -> Dict[str, Any]:
    action_buttons = []
    for b in buttons:
        action_buttons.append(
            {
                "type": "reply",
                "reply": {"id": b["id"], "title": b["title"]},
            }
        )

    interactive: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": action_buttons},
    }

    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }

    res = await _post(payload)

    # Logueo el “cuerpo” + ids de botones para tener trazabilidad
    ids = ",".join([b["id"] for b in buttons]) if buttons else None
    text_to_log = f"{header_text + ' | ' if header_text else ''}{body_text}"
    _log_outgoing_best_effort(conversation_id=conversation_id, text=text_to_log, button_id=ids)

    return res