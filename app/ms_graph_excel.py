# app/ms_graph_excel.py
from __future__ import annotations

import time
import urllib.parse
from typing import Any, List, Optional, Tuple

import httpx
from .settings import settings

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_token_cache: Tuple[Optional[str], float] = (None, 0.0)  # (token, expires_at_epoch)


async def _get_app_token() -> str:
    global _token_cache
    token, exp = _token_cache
    now = time.time()
    if token and now < exp - 60:
        return token

    if not (settings.MS_TENANT_ID and settings.MS_CLIENT_ID and settings.MS_CLIENT_SECRET):
        raise RuntimeError("Missing MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET")

    url = f"https://login.microsoftonline.com/{settings.MS_TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": settings.MS_CLIENT_ID,
        "client_secret": settings.MS_CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, data=data)
        if r.status_code >= 400:
            raise RuntimeError(f"Token error {r.status_code}: {r.text}")
        j = r.json()

    access_token = j["access_token"]
    expires_in = int(j.get("expires_in", 3599))
    _token_cache = (access_token, now + expires_in)
    return access_token


async def _graph_get(path: str) -> dict:
    token = await _get_app_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{_GRAPH_BASE}{path}", headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"Graph GET {path} -> {r.status_code}: {r.text}")
        return r.json()


async def _graph_post(path: str, json_body: dict) -> dict:
    token = await _get_app_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{_GRAPH_BASE}{path}", headers=headers, json=json_body)
        if r.status_code >= 400:
            raise RuntimeError(f"Graph POST {path} -> {r.status_code}: {r.text}")
        return r.json()


async def resolve_site_id() -> str:
    # GET /sites/{hostname}:/{server-relative-path}
    if not (settings.SP_HOSTNAME and settings.SP_SITE_PATH):
        raise RuntimeError("Missing SP_HOSTNAME / SP_SITE_PATH")

    site_path = settings.SP_SITE_PATH.lstrip("/")
    j = await _graph_get(f"/sites/{settings.SP_HOSTNAME}:/{site_path}")
    return j["id"]


def _encode_drive_path(file_path: str) -> str:
    p = file_path.lstrip("/")
    return urllib.parse.quote(p, safe="/()!$&'*,;=:@")  # keep slashes


async def append_row_to_sharepoint_excel(values: List[Any]) -> None:
    """
    POST /sites/{site-id}/drive/root:/{item-path}:/workbook/tables/{table-name}/rows/add
    Body: {"values": [[...]]}
    """
    if not settings.MS_EXCEL_ENABLED:
        return

    if not settings.SP_EXCEL_FILE_PATH:
        raise RuntimeError("Missing SP_EXCEL_FILE_PATH")

    table_name = settings.SP_EXCEL_TABLE_NAME or "Leads"
    site_id = await resolve_site_id()
    item_path = _encode_drive_path(settings.SP_EXCEL_FILE_PATH)

    endpoint = f"/sites/{site_id}/drive/root:/{item_path}:/workbook/tables/{table_name}/rows/add"
    await _graph_post(endpoint, {"values": [values]})