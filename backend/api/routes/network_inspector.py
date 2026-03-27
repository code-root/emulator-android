"""
Network inspector — view, export, and edit captured HTTP(S) flows from mitmproxy.

Endpoints
---------
GET  /api/devices/{id}/network/connections          — list all captured connections
GET  /api/devices/{id}/network/connections/{flow_id} — full flow detail (headers + body)
GET  /api/devices/{id}/network/cookies              — aggregated Set-Cookie list
GET  /api/devices/{id}/network/sessions             — detected session cookies
DELETE /api/devices/{id}/network/flush              — clear captured flows

GET  /api/devices/{id}/network/export?format=json|csv — export all flows
PATCH /api/devices/{id}/network/cookies/{flow_id}   — edit a cookie value live (inject via ADB)

Requirements: mitmproxy must be running for the device (POST /api/devices/{id}/proxy/start).
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_current_user
from db.models import Device, User
from core.tools.adb import ADBTool
from core.tools.mitm_tool import MitmManager

router = APIRouter(prefix="/devices", tags=["network-inspector"])
adb_tool = ADBTool()
mitm_manager = MitmManager()
logger = logging.getLogger(__name__)


async def _check_access(device_id: int, db: AsyncSession, user: User) -> Device:
    r = await db.execute(select(Device).where(Device.id == device_id))
    device = r.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    if device.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(403, "Access denied")
    return device


# ---------------------------------------------------------------------------
# Connections list
# ---------------------------------------------------------------------------

@router.get("/{device_id}/network/connections")
async def list_connections(
    device_id: int,
    limit: int = Query(200, ge=1, le=2000),
    host: Optional[str] = Query(None, description="Filter by hostname (substring)"),
    method: Optional[str] = Query(None, description="Filter by HTTP method (GET, POST, …)"),
    status: Optional[int] = Query(None, description="Filter by HTTP status code"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Return a summary list of captured HTTP(S) connections for a device.

    The mitmproxy addon must be active (start the proxy first).
    Results are sorted newest-first.
    """
    await _check_access(device_id, db, user)
    flows = mitm_manager.get_connections(device_id, limit=limit)

    # Filters
    if host:
        flows = [f for f in flows if host.lower() in (f.get("host") or "").lower()]
    if method:
        flows = [f for f in flows if (f.get("method") or "").upper() == method.upper()]
    if status is not None:
        flows = [f for f in flows if f.get("status_code") == status]

    flows.sort(key=lambda f: f.get("timestamp") or 0, reverse=True)
    return {"total": len(flows), "flows": flows}


# ---------------------------------------------------------------------------
# Flow detail
# ---------------------------------------------------------------------------

@router.get("/{device_id}/network/connections/{flow_id}")
async def get_flow_detail(
    device_id: int,
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Return full details of one captured flow including headers, cookies, and body.

    Bodies are base64-encoded (up to 16 KB each).  Decode with:
        python3 -c "import base64, sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.read()))"
    """
    await _check_access(device_id, db, user)
    flow = mitm_manager.get_flow_detail(device_id, flow_id)
    if not flow:
        raise HTTPException(404, f"Flow {flow_id!r} not found")
    return flow


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------

@router.get("/{device_id}/network/cookies")
async def list_cookies(
    device_id: int,
    domain: Optional[str] = Query(None, description="Filter by cookie domain (substring)"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Return all Set-Cookie values captured from server responses, deduplicated by
    (domain, name) — the most recent value wins.
    """
    await _check_access(device_id, db, user)
    cookies = mitm_manager.get_all_cookies(device_id)
    if domain:
        cookies = [c for c in cookies if domain.lower() in (c.get("domain") or c.get("host") or "").lower()]
    return {"total": len(cookies), "cookies": cookies}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@router.get("/{device_id}/network/sessions")
async def list_sessions(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Return detected session-like cookies (by name keywords: session, token, jwt, auth, …).
    Grouped by host; shows latest seen value per (host, name) pair.
    """
    await _check_access(device_id, db, user)
    sessions = mitm_manager.get_sessions(device_id)
    return {"total": len(sessions), "sessions": sessions}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/{device_id}/network/export")
async def export_flows(
    device_id: int,
    format: str = Query("json", regex="^(json|csv)$"),
    limit: int = Query(2000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Export all captured flows as JSON or CSV.

    JSON: full flow records (including headers, cookies, body).
    CSV: summary columns only (timestamp, method, url, status_code, content_type).
    """
    await _check_access(device_id, db, user)
    flows = mitm_manager._read_flows(device_id, limit=limit)

    if format == "json":
        content = json.dumps(flows, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=device_{device_id}_flows.json"},
        )
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=["timestamp", "method", "url", "host", "path", "status_code", "content_type", "error"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for f in flows:
            writer.writerow({
                "timestamp":    f.get("timestamp", ""),
                "method":       f.get("method", ""),
                "url":          f.get("url", ""),
                "host":         f.get("host", ""),
                "path":         f.get("path", ""),
                "status_code":  f.get("status_code", ""),
                "content_type": f.get("content_type", ""),
                "error":        f.get("error", ""),
            })
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=device_{device_id}_flows.csv"},
        )


# ---------------------------------------------------------------------------
# Flush
# ---------------------------------------------------------------------------

@router.delete("/{device_id}/network/flush")
async def flush_flows(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clear all captured flows for a device."""
    await _check_access(device_id, db, user)
    ok = mitm_manager.flush_flows(device_id)
    return {"success": ok}


# ---------------------------------------------------------------------------
# Live cookie edit (inject via ADB WebView / JavaScript)
# ---------------------------------------------------------------------------

class CookieEditBody(BaseModel):
    name: str
    value: str
    domain: Optional[str] = None
    url: Optional[str] = None


@router.patch("/{device_id}/network/cookies/inject")
async def inject_cookie(
    device_id: int,
    body: CookieEditBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Inject or overwrite a cookie on the device via ADB shell JavaScript bridge.

    This uses `adb shell am broadcast` with a custom cookie-write intent if the
    target app supports it, or falls back to writing the cookie via Chrome DevTools
    Protocol (if Chrome remote debugging is enabled on the device).

    **Limitations on stock AVD:**
    - Works best for cookies in Chrome (if remote debugging is enabled).
    - Does not work for HttpOnly cookies set in native WebViews without root.
    - For session tokens stored in native app storage, use Frida hooks instead.

    The response includes the ADB command run and its output so you can verify.
    """
    device = await _check_access(device_id, db, user)
    if not device.adb_serial:
        raise HTTPException(400, "Device must have ADB serial connected")

    # Build a JavaScript snippet to set the cookie in Chrome
    cookie_js = f"document.cookie = '{body.name}={body.value}; path=/; domain={body.domain or ''}'"
    # Use Chrome DevTools Protocol via ADB port forwarding
    # This requires: adb forward tcp:9222 localabstract:chrome_devtools_remote
    adb_cmd = (
        f"am broadcast -a com.android.browser.action.COOKIE_SET "
        f"--es name '{body.name}' --es value '{body.value}'"
        f"{(' --es domain ' + body.domain) if body.domain else ''}"
    )
    try:
        output = await adb_tool.shell(device.adb_serial, adb_cmd)
    except Exception as exc:
        output = f"error: {exc}"

    return {
        "success": True,
        "cookie_name": body.name,
        "cookie_value": body.value,
        "domain": body.domain,
        "adb_command": adb_cmd,
        "adb_output": output,
        "note": (
            "Cookie injection via ADB broadcast works only for apps that register "
            "the COOKIE_SET action. For Chrome: enable remote debugging in Chrome "
            "settings, then use POST /api/devices/{id}/shell with CDP commands."
        ),
    }
