# app/conversation.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, Optional

from .settings import settings
from .whatsapp import send_text, send_buttons

# Excel (SharePoint) opcional — queda “best-effort”
try:
    from .ms_graph_excel import append_row_to_sharepoint_excel
except Exception:
    append_row_to_sharepoint_excel = None

# ✅ Session store en Postgres
from app.session_store import (
    get_session_state_data_by_wa_user_id,
    save_session_by_wa_user_id,
    reset_session_by_wa_user_id,
)

# ✅ DB helpers para selections
from app.db import SessionLocal
from app.models import Event, LeadSelection, Lead


STATE_START = "START"
STATE_ASK_PAX = "ASK_PAX"
STATE_PICK_INSTANCES = "PICK_INSTANCES"
STATE_ASK_HOTEL = "ASK_HOTEL"
STATE_ASK_CITY_MODE = "ASK_CITY_MODE"
STATE_ASK_CITY_TEXT = "ASK_CITY_TEXT"
STATE_ASK_CONTACT = "ASK_CONTACT"
STATE_HUMAN_PENDING = "HUMAN_PENDING"


# -------------------------
# Session (Postgres)
# -------------------------
def reset_session(user_id: str) -> None:
    reset_session_by_wa_user_id(user_id)


def get_session(user_id: str) -> Dict[str, Any]:
    """
    Mantiene el mismo formato que tu código original:
      {"state": "...", "data": {...}}
    En DB guardamos {"data": {...}} dentro del JSON para compatibilidad.
    """
    state, payload = get_session_state_data_by_wa_user_id(user_id)
    payload = payload if isinstance(payload, dict) else {}

    data = payload.get("data")
    if not isinstance(data, dict):
        data = {}

    return {"state": state or STATE_START, "data": data}


def _save_session(user_id: str, session: Dict[str, Any]) -> None:
    state = session.get("state") or STATE_START
    data = session.get("data") if isinstance(session.get("data"), dict) else {}
    save_session_by_wa_user_id(user_id, state=state, data={"data": data})


# -------------------------
# Contexto DB (conv/lead)
# -------------------------
def set_db_context(user_id: str, conversation_id: int, lead_id: int | None) -> None:
    s = get_session(user_id)
    s["data"]["_conversation_id"] = conversation_id
    s["data"]["_lead_id"] = lead_id
    _save_session(user_id, s)


def _conv_id(user_id: str) -> Optional[int]:
    s = get_session(user_id)
    cid = s.get("data", {}).get("_conversation_id")
    return cid if isinstance(cid, int) else None


def _lead_id(user_id: str) -> Optional[int]:
    """
    Devuelve el lead_id asociado al usuario.
    1️⃣ Primero intenta leerlo desde la sesión
    2️⃣ Si no existe (ej: reinicio del container), lo reconstruye desde la DB
    """
    s = get_session(user_id)
    lid = s.get("data", {}).get("_lead_id")

    if isinstance(lid, int):
        return lid

    db = SessionLocal()
    try:
        from app.models import User

        user = db.query(User).filter(User.wa_user_id == user_id).first()
        if not user:
            return None

        lead = (
            db.query(Lead)
            .filter(Lead.user_id == user.id)
            .order_by(Lead.id.desc())
            .first()
        )
        if not lead:
            return None

        s["data"]["_lead_id"] = lead.id
        _save_session(user_id, s)
        return lead.id

    except Exception as e:
        print("[DB] lead lookup failed:", repr(e))
        return None
    finally:
        db.close()


# -------------------------
# Outbound wrappers (log en DB via whatsapp.py)
# -------------------------
async def _send_text(user_id: str, text: str) -> None:
    await send_text(user_id, text, conversation_id=_conv_id(user_id))


async def _send_buttons(
    user_id: str,
    *,
    body_text: str,
    buttons,
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> None:
    await send_buttons(
        to=user_id,
        header_text=header_text,
        body_text=body_text,
        footer_text=footer_text,
        buttons=buttons,
        conversation_id=_conv_id(user_id),
    )


# -------------------------
# Normalización de button_id (robusta)
# -------------------------
def _normalize_button_id(button_id: Optional[str]) -> Optional[str]:
    """
    En condiciones normales llega un id simple (ej: INST_QF_KC).
    Si por algún bug te llega una string con comas, elegimos el primer token útil.
    """
    if not button_id:
        return None

    bid = str(button_id).strip()
    if not bid:
        return None

    if "," in bid:
        parts = [p.strip() for p in bid.split(",") if p.strip()]
        # prioriza tokens reconocibles
        for p in parts:
            if p.startswith("INST_") or p in {
                "MENU_TICKETS", "MENU_HUMAN",
                "PAX_1_2", "PAX_3_5", "PAX_6_10",
                "HOTEL_YES", "HOTEL_NO",
                "CITY_SPECIFIC", "CITY_FLEX",
                "INST_DONE", "INST_CLEAR",
            }:
                return p
        return parts[0] if parts else bid

    return bid


# -------------------------
# Instancias Argentina (multi-select)
# -------------------------
# ✅ IMPORTANTE: estos IDs ahora matchean con events.code en tu DB
INSTANCE_LABELS = {
    "INST_GROUPS": "🇦🇷 Fase de Grupos",
    "INST_R32_MIAMI": "🎯 16vos Miami",
    "INST_R16_ATL": "🔥 8vos Atlanta",
    "INST_QF_KC": "💎 4tos Kansas City",
    "INST_SF_ATL": "🚀 Semifinal Atlanta",
    "INST_F_NY": "🏆 Final New York",
}


def _ensure_instances_list(data: Dict[str, Any]) -> None:
    if "instances" not in data or not isinstance(data["instances"], list):
        data["instances"] = []


def _toggle_instance(data: Dict[str, Any], inst_id: str) -> bool:
    """Return True if added, False if removed."""
    _ensure_instances_list(data)
    if inst_id in data["instances"]:
        data["instances"].remove(inst_id)
        return False
    data["instances"].append(inst_id)
    return True


def _instances_text(data: Dict[str, Any]) -> str:
    _ensure_instances_list(data)
    if not data["instances"]:
        return "(sin selección)"
    labels = [INSTANCE_LABELS.get(i, i) for i in data["instances"]]
    return ", ".join(labels)


def _db_toggle_instance_selection(user_id: str, inst_code: str, added: bool) -> None:
    """
    Persiste INST_* en lead_selections:
      - added=True  => insert si no existe
      - added=False => delete
    Además: auto-califica lead: open -> qualified/hot
    """
    lid = _lead_id(user_id)
    if not lid:
        return

    db = SessionLocal()
    try:
        ev = db.query(Event).filter(Event.code == inst_code).first()
        if not ev:
            print(f"[DB] Event missing for code={inst_code}. Seed events (INST_*).")
            return

        if added:
            exists = (
                db.query(LeadSelection)
                .filter(LeadSelection.lead_id == lid, LeadSelection.event_id == ev.id)
                .first()
            )
            if not exists:
                # ✅ quantity=1 (no None)
                db.add(LeadSelection(lead_id=lid, event_id=ev.id, quantity=1))
                db.commit()
        else:
            (
                db.query(LeadSelection)
                .filter(LeadSelection.lead_id == lid, LeadSelection.event_id == ev.id)
                .delete()
            )
            db.commit()

        # auto-qualify
        count_sel = db.query(LeadSelection).filter(LeadSelection.lead_id == lid).count()
        lead = db.query(Lead).filter(Lead.id == lid).first()
        if lead:
            if count_sel >= 2 and lead.status == "open":
                lead.status = "hot"
                db.commit()
            elif count_sel >= 1 and lead.status == "open":
                lead.status = "qualified"
                db.commit()

    except Exception as e:
        print("[DB] toggle selection failed:", repr(e))
    finally:
        db.close()


def _db_clear_instance_selections(user_id: str) -> None:
    lid = _lead_id(user_id)
    if not lid:
        return
    db = SessionLocal()
    try:
        db.query(LeadSelection).filter(LeadSelection.lead_id == lid).delete()
        db.commit()
    except Exception as e:
        print("[DB] clear selections failed:", repr(e))
    finally:
        db.close()


# -------------------------
# UI helpers
# -------------------------
async def show_main_menu(user_id: str):
    await _send_buttons(
        user_id,
        header_text="Mundial FIFA 2026",
        body_text="Hola 👋 Soy el asistente. ¿Qué querés hacer?",
        footer_text="Escribí ASESOR o /reset",
        buttons=[
            {"id": "MENU_TICKETS", "title": "🎟️ Entradas"},
            {"id": "MENU_HUMAN", "title": "👤 Asesor"},
        ],
    )


async def ask_pax(user_id: str):
    await _send_buttons(
        user_id,
        header_text="Pasajeros",
        body_text="¿Cuántas personas viajan?",
        buttons=[
            {"id": "PAX_1_2", "title": "1–2"},
            {"id": "PAX_3_5", "title": "3–5"},
            {"id": "PAX_6_10", "title": "6–10"},
        ],
        footer_text="Si son más, escribí: 10+",
    )


def parse_pax_id(pax_id: str) -> Optional[str]:
    return {
        "PAX_1_2": "1-2",
        "PAX_3_5": "3-5",
        "PAX_6_10": "6-10",
    }.get(pax_id)


async def pick_instances_menu(user_id: str, data: Dict[str, Any]):
    selected = _instances_text(data)
    body = (
        "Seleccioná una o más instancias de *Argentina - Road to the Final*.\n"
        "Podés tocar varias opciones.\n\n"
        f"Seleccionadas: {selected}"
    )
    await _send_buttons(
        user_id,
        header_text="Argentina - Road to the Final",
        body_text=body,
        footer_text="Cuando termines, tocá ✅ Listo",
        buttons=[
            {"id": "INST_GROUPS", "title": "Grupos"},
            {"id": "INST_R32_MIAMI", "title": "16vos Miami"},
            {"id": "INST_R16_ATL", "title": "8vos Atlanta"},
        ],
    )
    await _send_buttons(
        user_id,
        header_text="Argentina - Road to the Final",
        body_text="Seguís eligiendo o finalizá:",
        footer_text="Podés tocar ✅ Listo cuando quieras",
        buttons=[
            {"id": "INST_QF_KC", "title": "4tos KC"},
            {"id": "INST_SF_ATL", "title": "Semifinal Atlanta"},
            {"id": "INST_F_NY", "title": "Final New York"},
        ],
    )
    await _send_buttons(
        user_id,
        header_text="Confirmación",
        body_text="¿Listo con la selección?",
        buttons=[
            {"id": "INST_DONE", "title": "✅ Listo"},
            {"id": "INST_CLEAR", "title": "🧹 Borrar"},
            {"id": "MENU_HUMAN", "title": "👤 Asesor"},
        ],
    )


async def ask_hotel(user_id: str):
    await _send_buttons(
        user_id,
        header_text="Alojamiento",
        body_text="¿Necesitan hotel?",
        buttons=[
            {"id": "HOTEL_YES", "title": "🏨 Sí"},
            {"id": "HOTEL_NO", "title": "❌ No"},
            {"id": "MENU_HUMAN", "title": "👤 Asesor"},
        ],
    )


async def ask_city_mode(user_id: str):
    await _send_buttons(
        user_id,
        header_text="Ciudad",
        body_text="¿Tenés una ciudad específica o sos flexible?",
        buttons=[
            {"id": "CITY_SPECIFIC", "title": "📍 Ciudad específica"},
            {"id": "CITY_FLEX", "title": "🌎 Flexible"},
            {"id": "MENU_HUMAN", "title": "👤 Asesor"},
        ],
    )


# -------------------------
# Resúmenes
# -------------------------
def build_customer_summary(data: Dict[str, Any]) -> str:
    pax = data.get("pax_range", "-")
    inst = _instances_text(data)
    hotel = data.get("hotel", "(pendiente)")
    city_mode = data.get("city_mode", "(pendiente)")
    city_text = data.get("city_text", "")
    city_line = city_mode
    if city_mode == "Ciudad específica" and city_text:
        city_line = f"{city_mode}: {city_text}"

    contact = data.get("contact", "(pendiente)")

    return (
        "✅ Resumen de tu consulta\n"
        "• Producto: Entradas Hospitality (Argentina)\n"
        f"• Pasajeros: {pax}\n"
        f"• Instancias: {inst}\n"
        f"• Hotel: {hotel}\n"
        f"• Ciudad: {city_line}\n"
        f"• Contacto: {contact}\n"
    )


def build_internal_summary(user_phone: str, state: str, data: Dict[str, Any]) -> str:
    pax = data.get("pax_range", "(sin dato)")
    inst = _instances_text(data)
    hotel = data.get("hotel", "(sin dato)")
    city_mode = data.get("city_mode", "(sin dato)")
    city_text = data.get("city_text", "")
    city_line = city_mode
    if city_mode == "Ciudad específica" and city_text:
        city_line = f"{city_mode}: {city_text}"

    contact = data.get("contact", "(sin dato)")
    last_text = data.get("last_text", "")

    return (
        "🔔 NUEVO LEAD MUNDIAL 2026 (Hospitality)\n"
        f"Cliente WA: {user_phone}\n"
        f"Estado: {state}\n"
        f"Pax: {pax}\n"
        f"Instancias: {inst}\n"
        f"Hotel: {hotel}\n"
        f"Ciudad: {city_line}\n"
        f"Contacto: {contact}\n"
        + (f"\nÚltimo msg: {last_text}" if last_text else "")
        + "\n\nResponder desde el número oficial."
    )


async def _handoff(user_phone: str, state: str, data: Dict[str, Any]) -> None:
    print("[HANDOFF] entered", user_phone, state, data)

    # 1) WhatsApp interno
    if settings.INTERNAL_SALES_WA_TO:
        try:
            await send_text(
                settings.INTERNAL_SALES_WA_TO,
                build_internal_summary(user_phone, state, data),
            )
            print("[HANDOFF] internal WA sent")
        except Exception as e:
            print("[HANDOFF] Internal WA send failed:", repr(e))

    # 2) Excel SharePoint (best-effort)
    if append_row_to_sharepoint_excel and getattr(settings, "MS_EXCEL_ENABLED", 0):
        try:
            ts = datetime.now(timezone.utc).isoformat()
            row = [
                ts,
                user_phone,
                data.get("pax_range", ""),
                _instances_text(data),
                data.get("contact", ""),
                "HUMAN_PENDING",
            ]
            print("[EXCEL] about to append row:", row)
            await append_row_to_sharepoint_excel(row)
            print("[EXCEL] append success")
        except Exception as e:
            print("[EXCEL] append failed:", repr(e))
    else:
        print(
            "[EXCEL] skipped",
            {
                "append_row_to_sharepoint_excel": bool(append_row_to_sharepoint_excel),
                "MS_EXCEL_ENABLED": getattr(settings, "MS_EXCEL_ENABLED", None),
            },
        )

# -------------------------
# Main handler
# -------------------------
async def handle_input(user_id: str, text: str | None, button_id: str | None):
    # ✅ normaliza button_id
    button_id = _normalize_button_id(button_id)

    session = get_session(user_id)
    state = session["state"]
    data = session["data"]

    def _commit():
        _save_session(user_id, session)

    if text and text.strip():
        data["last_text"] = text.strip()
        _commit()

    print(f"[DEBUG] user={user_id} state={state} text={text!r} button_id={button_id!r}")

    # Reset global
    cmd = (text or "").strip().lower()
    if cmd in ("/reset", "reset", "reiniciar", "empezar de nuevo", "/start", "start"):
        reset_session(user_id)
        await show_main_menu(user_id)
        return

    # Si ya está en manos humanas: responder 1 sola vez
    if state == STATE_HUMAN_PENDING:
        if not data.get("pending_notified"):
            data["pending_notified"] = True
            _commit()
            await _send_text(user_id, "✅ Ya tomamos tu consulta. Un asesor te responde en breve.")
        return

    # Atajo global a humano (texto o botón)
    if (text or "").strip().upper() == "ASESOR" or button_id == "MENU_HUMAN":
        session["state"] = STATE_HUMAN_PENDING
        _commit()
        await _send_text(user_id, "Perfecto. Un asesor te escribe en breve 👤")
        await _handoff(user_id, state, data)
        return

    # START
    if state == STATE_START:
        if button_id == "MENU_TICKETS":
            data["intent"] = "entradas hospitality argentina"
            session["state"] = STATE_ASK_PAX
            _commit()
            await ask_pax(user_id)
            return

        await show_main_menu(user_id)
        return

    # ASK_PAX
    if state == STATE_ASK_PAX:
        if button_id:
            pax = parse_pax_id(button_id)
            if pax:
                data["pax_range"] = pax
                session["state"] = STATE_PICK_INSTANCES
                _commit()
                await pick_instances_menu(user_id, data)
                return

        if text and text.strip() == "10+":
            data["pax_range"] = "10+"
            session["state"] = STATE_PICK_INSTANCES
            _commit()
            await pick_instances_menu(user_id, data)
            return

        await _send_text(user_id, "No entendí la cantidad. Elegí una opción o escribí 10+.")
        return

    # PICK_INSTANCES (multi)
    if state == STATE_PICK_INSTANCES:
        if button_id in INSTANCE_LABELS:
            added = _toggle_instance(data, button_id)

            # ✅ persistencia en DB (lead_selections)
            _db_toggle_instance_selection(user_id, button_id, added=added)

            _commit()
            msg = (
                f"{'✅ Sumé' if added else '🗑️ Saqué'}: {INSTANCE_LABELS.get(button_id, button_id)}\n\n"
                f"Seleccionadas: {_instances_text(data)}"
            )
            await _send_text(user_id, msg)
            await pick_instances_menu(user_id, data)
            return

        if button_id == "INST_CLEAR":
            data["instances"] = []
            _db_clear_instance_selections(user_id)
            _commit()
            await _send_text(user_id, "🧹 Listo. Borré la selección.")
            await pick_instances_menu(user_id, data)
            return

        if button_id == "INST_DONE":
            _ensure_instances_list(data)
            if not data["instances"]:
                await _send_text(
                    user_id,
                    "Necesito que elijas al menos una instancia (Grupos/16vos/8vos/4tos/SF/Final).",
                )
                await pick_instances_menu(user_id, data)
                return

            session["state"] = STATE_ASK_HOTEL
            _commit()
            await ask_hotel(user_id)
            return

        await _send_text(user_id, "Elegí instancias con los botones y tocá ✅ Listo cuando termines.")
        await pick_instances_menu(user_id, data)
        return

    # ASK_HOTEL
    if state == STATE_ASK_HOTEL:
        if button_id == "HOTEL_YES":
            data["hotel"] = "Sí"
            session["state"] = STATE_ASK_CITY_MODE
            _commit()
            await ask_city_mode(user_id)
            return
        if button_id == "HOTEL_NO":
            data["hotel"] = "No"
            session["state"] = STATE_ASK_CITY_MODE
            _commit()
            await ask_city_mode(user_id)
            return

        await _send_text(user_id, "¿Necesitan hotel? Elegí Sí o No.")
        return

    # ASK_CITY_MODE
    if state == STATE_ASK_CITY_MODE:
        if button_id == "CITY_FLEX":
            data["city_mode"] = "Flexible"
            data.pop("city_text", None)
            session["state"] = STATE_ASK_CONTACT
            _commit()
            await _send_text(
                user_id,
                "Perfecto 👌\n\nPasame *Nombre y Email* (en un solo mensaje).\nEj: Juan Pérez - juan@email.com",
            )
            return

        if button_id == "CITY_SPECIFIC":
            data["city_mode"] = "Ciudad específica"
            session["state"] = STATE_ASK_CITY_TEXT
            _commit()
            await _send_text(user_id, "Decime la ciudad (ej: Miami, Dallas, Atlanta, New York).")
            return

        await _send_text(user_id, "Elegí: Ciudad específica o Flexible.")
        return

    # ASK_CITY_TEXT
    if state == STATE_ASK_CITY_TEXT:
        if text and text.strip():
            data["city_text"] = text.strip()
            session["state"] = STATE_ASK_CONTACT
            _commit()
            await _send_text(
                user_id,
                "Perfecto 👌\n\nPasame *Nombre y Email* (en un solo mensaje).\nEj: Juan Pérez - juan@email.com",
            )
            return

        await _send_text(user_id, "Decime la ciudad en texto (ej: Miami).")
        return

    # ASK_CONTACT
    if state == STATE_ASK_CONTACT:
        if text and text.strip():
            data["contact"] = text.strip()
            session["state"] = STATE_HUMAN_PENDING
            _commit()

            summary = build_customer_summary(data)
            await _send_text(user_id, summary + "\nGracias. Un asesor te escribe en breve 👤")

            await _handoff(user_id, state, data)
            return

        await _send_text(user_id, "Necesito Nombre y Email en un solo mensaje. Ej: Juan Pérez - juan@email.com")
        return

    # fallback
    session["state"] = STATE_START
    _commit()
    await show_main_menu(user_id)