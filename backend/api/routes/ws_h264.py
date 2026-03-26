"""
WebSocket endpoint for real-time H.264 streaming.

Route: /ws/{device_id}/h264?token=JWT

Binary frames from backend → browser:
  CONFIG  (type=1): codec string + SPS+PPS  → initialize VideoDecoder
  FRAME   (type=2): keyframe flag + PTS + H.264 NAL  → decode & draw to <canvas>

JSON text frames from browser → backend:
  tap / swipe / keyevent / input_text  (same protocol as /ws/{device_id})
  {"action":"ping"}

Latency: < 100 ms  vs  200-600 ms for JPEG screencap.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

from api.deps import get_current_user_from_token
from db.database import AsyncSessionLocal
from db.models import Device, DeviceStatus
from core.tools.adb import ADBTool
from core.tools.h264_stream import H264Streamer
from services.ws_manager import ws_manager

router  = APIRouter(tags=["websocket-h264"])
adb     = ADBTool()
logger  = logging.getLogger(__name__)

SERIAL_TTL_SEC = 120.0

# ── swipe coalescing (same constants as ws.py) ────────────────────────────────
SWIPE_MAX_SEGS   = 36
SWIPE_JOIN_EPS   = 6
SWIPE_MIN_DUR_MS = 35
SWIPE_MAX_DUR_MS = 700


def _segs_chain(prev: dict, nxt: dict, eps: int = SWIPE_JOIN_EPS) -> bool:
    try:
        return (
            abs(int(prev.get("x2", 0)) - int(nxt.get("x1", 0))) <= eps
            and abs(int(prev.get("y2", 0)) - int(nxt.get("y1", 0))) <= eps
        )
    except (TypeError, ValueError):
        return False


def _merge_chain(chain: list[dict]) -> dict:
    total = sum(int(x.get("duration_ms", 25)) for x in chain)
    return {
        "action":      "swipe",
        "x1":          int(chain[0].get("x1", 0)),
        "y1":          int(chain[0].get("y1", 0)),
        "x2":          int(chain[-1].get("x2", 0)),
        "y2":          int(chain[-1].get("y2", 0)),
        "duration_ms": max(SWIPE_MIN_DUR_MS, min(SWIPE_MAX_DUR_MS, total)),
    }


@router.websocket("/ws/{device_id}/h264")
async def ws_h264_endpoint(
    websocket: WebSocket,
    device_id: int,
    token: str = Query(...),
):
    # ── auth ─────────────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        user = await get_current_user_from_token(token, db)
        if not user:
            await websocket.close(code=4001, reason="Unauthorized")
            return
        result = await db.execute(select(Device).where(Device.id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            await websocket.close(code=4004, reason="Device not found")
            return
        if device.owner_id != user.id and user.role.value != "admin":
            await websocket.close(code=4003, reason="Forbidden")
            return

    await websocket.accept()
    await ws_manager.connect(websocket, device_id, user.id)

    # ── shared state ─────────────────────────────────────────────────────────
    serial_state  = {"serial": device.adb_serial, "cached_at": time.monotonic()}
    control_queue: asyncio.Queue[dict] = asyncio.Queue()
    prefetch:       deque[dict]         = deque()
    streaming_active = asyncio.Event()   # set when serial is available

    async def get_serial(force: bool = False) -> str | None:
        now = time.monotonic()
        if not force and serial_state["serial"] and (now - serial_state["cached_at"]) < SERIAL_TTL_SEC:
            return serial_state["serial"]
        async with AsyncSessionLocal() as db2:
            r = await db2.execute(select(Device).where(Device.id == device_id))
            dev = r.scalar_one_or_none()
        serial = dev.adb_serial if dev and dev.status == DeviceStatus.running and dev.adb_serial else None
        serial_state.update(serial=serial, cached_at=time.monotonic())
        return serial

    # ── H.264 streaming task ──────────────────────────────────────────────────
    async def stream_task() -> None:
        streamer = H264Streamer()
        while True:
            serial = await get_serial(force=True)
            if not serial:
                await asyncio.sleep(2.0)
                continue
            streaming_active.set()
            try:
                async for binary_msg in streamer.stream(serial, width=720, height=1280, bit_rate="3M", fps=30):
                    try:
                        await websocket.send_bytes(binary_msg)
                    except WebSocketDisconnect:
                        return
                    except Exception:
                        return
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("H264 stream task error: %s", exc)
                await asyncio.sleep(1.0)

    # ── ADB control task ──────────────────────────────────────────────────────
    async def control_task() -> None:
        while True:
            msg = prefetch.popleft() if prefetch else await control_queue.get()
            action = msg.get("action")
            if action in ("_noop", "ping"):
                continue

            serial = serial_state["serial"]
            if not serial:
                serial = await get_serial()
            if not serial:
                continue

            try:
                if action == "tap":
                    await adb.tap(serial, int(msg.get("x", 0)), int(msg.get("y", 0)))
                elif action == "swipe":
                    # coalesce consecutive swipe segments
                    chain = [msg]
                    while len(chain) < SWIPE_MAX_SEGS:
                        nxt = prefetch.popleft() if prefetch else None
                        if nxt is None:
                            try:
                                nxt = control_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        if nxt.get("action") == "swipe" and _segs_chain(chain[-1], nxt):
                            chain.append(nxt)
                        else:
                            prefetch.appendleft(nxt)
                            break
                    merged = chain[0] if len(chain) == 1 else _merge_chain(chain)
                    await adb.swipe(
                        serial,
                        int(merged.get("x1", 0)), int(merged.get("y1", 0)),
                        int(merged.get("x2", 0)), int(merged.get("y2", 0)),
                        int(merged.get("duration_ms", 300)),
                    )
                elif action == "keyevent":
                    await adb.key_event(serial, msg.get("key", "KEYCODE_HOME"))
                elif action == "input_text":
                    await adb.input_text(serial, msg.get("text", ""))
                elif action == "screenshot_once":
                    # single PNG fallback for clients that need a static shot
                    png = await adb.screenshot(serial)
                    import base64
                    await websocket.send_json({
                        "type": "screenshot",
                        "data": base64.b64encode(png).decode(),
                        "format": "png",
                    })
            except WebSocketDisconnect:
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("ADB control error: %s", exc)

    stream_t  = asyncio.create_task(stream_task())
    control_t = asyncio.create_task(control_task())

    # ── send initial status ───────────────────────────────────────────────────
    try:
        await websocket.send_json({
            "type":       "status",
            "status":     device.status.value,
            "device_id":  device_id,
            "adb_serial": device.adb_serial,
            "stream":     "h264",
        })

        # ── receive loop ─────────────────────────────────────────────────────
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                msg = json.loads(raw)
                action = msg.get("action", "")
                if action == "ping":
                    await websocket.send_json({"type": "pong"})
                elif action in ("tap", "swipe", "keyevent", "input_text", "screenshot_once"):
                    await control_queue.put(msg)
                elif action == "get_status":
                    s = await get_serial(force=True)
                    await websocket.send_json({
                        "type": "status",
                        "adb_serial": s,
                        "streaming": streaming_active.is_set(),
                    })
                else:
                    await websocket.send_json({"type": "error", "message": f"Unknown: {action}"})

            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except WebSocketDisconnect:
                    break

    except WebSocketDisconnect:
        logger.info("H264 WS disconnected — device %d user %d", device_id, user.id)
    except Exception as exc:
        logger.error("H264 WS error — device %d: %s", device_id, exc)
    finally:
        stream_t.cancel()
        control_t.cancel()
        await asyncio.gather(stream_t, control_t, return_exceptions=True)
        await ws_manager.disconnect(websocket, device_id)
