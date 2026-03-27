import asyncio
import base64
import io
import json
import logging
import time
import zlib
from collections import deque
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from PIL import Image
from sqlalchemy import select

from api.deps import get_current_user_from_token
from db.database import AsyncSessionLocal
from db.models import Device, DeviceStatus
from core.tools.adb import ADBTool
from services.ws_manager import ws_manager

router = APIRouter(tags=["websocket"])
adb_tool = ADBTool()
logger = logging.getLogger(__name__)

# 0ms = أقصى سرعة جدولة (مضاعفة مقارنةً بفاصل 1ms) — المعدل الحقيقي = زمن screencap على ADB فقط.
SCREENSHOT_INTERVAL_MIN_MS = 0
SCREENSHOT_INTERVAL_MAX_MS = 2500
SCREENSHOT_INTERVAL_DEFAULT_MS = 0

SERIAL_CACHE_TTL_SEC = 120.0
# عند فشل screencap (جهاز غير موجود في ADB): إبطاء المحاولات وتقليل الضجيج في السجلات.
SCREENSHOT_FAIL_BACKOFF_MIN_SEC = 0.25
SCREENSHOT_FAIL_BACKOFF_MAX_SEC = 5.0
ADB_LOSS_NOTIFY_INTERVAL_SEC = 12.0
# بعد التحكم: جدولة اللقطة التالية فوراً (0 = بدون تأخير إضافي).
POST_CONTROL_FRAME_GAP_SEC = 0.0

# دمج مقاطع السحب المتسلسلة (نهاية المقطع ≈ بداية التالي) في swipe واحد = أقل استدعاءات adb مع نفس المسار الكلي.
SWIPE_COALESCE_MAX_SEGMENTS = 36
SWIPE_COALESCE_JOIN_EPS_PX = 6
SWIPE_COALESCE_MIN_DURATION_MS = 35
SWIPE_COALESCE_MAX_DURATION_MS = 700

# بث سريع: JPEG أخف من PNG؛ تصغير أقصى ضلع يقلل الحجم ووقت الترميز/الشبكة.
STREAM_JPEG_MAX_SIDE = 1008
STREAM_JPEG_QUALITY = 76

# خمول الشاشة: بعد تكرار نفس الإطار نطيل الفاصل قليلاً (لا نعيد ترميز/إرسال).
IDLE_DWELL_MIN_SEC = 0.0
IDLE_DWELL_MAX_SEC =0.0
IDLE_DWELL_STEP_SEC = 0.0


def _frame_signature(raw: bytes) -> tuple[int, int]:
    """بصمة سريعة O(n) في C داخل zlib — كافية لاكتشاف تكرار الإطار."""
    return (len(raw), zlib.adler32(raw) & 0xFFFFFFFF)


def _png_to_jpeg_stream(png_bytes: bytes) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(png_bytes)) as im:
        im = im.convert("RGB")
        w, h = im.size
        m = max(w, h)
        if m > STREAM_JPEG_MAX_SIDE:
            s = STREAM_JPEG_MAX_SIDE / m
            nw, nh = max(1, int(w * s)), max(1, int(h * s))
            im = im.resize((nw, nh), Image.Resampling.BILINEAR)
            w, h = nw, nh
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=STREAM_JPEG_QUALITY, optimize=False)
        return buf.getvalue(), w, h


def _encode_live_frame(png_bytes: bytes, use_jpeg: bool) -> tuple[str, str, int, int]:
    if use_jpeg:
        jpeg, w, h = _png_to_jpeg_stream(png_bytes)
        return base64.b64encode(jpeg).decode("ascii"), "jpeg", w, h
    w, h = _png_dimensions(png_bytes)
    return base64.b64encode(png_bytes).decode("ascii"), "png", w, h


def _png_ihdr_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Read width/height from PNG IHDR without decoding the image (much faster than PIL per frame)."""
    i = png_bytes.find(b"IHDR")
    if i < 4 or i + 12 > len(png_bytes):
        raise ValueError("IHDR not found")
    w = int.from_bytes(png_bytes[i + 4 : i + 8], "big")
    h = int.from_bytes(png_bytes[i + 8 : i + 12], "big")
    if not (0 < w <= 8192 and 0 < h <= 8192):
        raise ValueError("invalid IHDR size")
    return w, h


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    try:
        return _png_ihdr_dimensions(png_bytes)
    except Exception:
        with Image.open(io.BytesIO(png_bytes)) as im:
            return im.width, im.height


def _adb_serial_not_found(err: BaseException | str) -> bool:
    s = str(err).lower()
    return "not found" in s and ("device" in s or "adb:" in s)


def _clamp_interval_ms(raw_ms) -> int:
    try:
        interval_ms = int(float(raw_ms))
    except (TypeError, ValueError):
        interval_ms = int(SCREENSHOT_INTERVAL_DEFAULT_MS)
    lo = int(SCREENSHOT_INTERVAL_MIN_MS)
    hi = int(SCREENSHOT_INTERVAL_MAX_MS)
    return max(lo, min(hi, interval_ms))


def _swipe_segments_chain(prev: dict, nxt: dict, eps: int = SWIPE_COALESCE_JOIN_EPS_PX) -> bool:
    try:
        x2, y2 = int(prev.get("x2", 0)), int(prev.get("y2", 0))
        x1, y1 = int(nxt.get("x1", 0)), int(nxt.get("y1", 0))
    except (TypeError, ValueError):
        return False
    return abs(x2 - x1) <= eps and abs(y2 - y1) <= eps


def _merge_swipe_chain(chain: list[dict]) -> dict:
    a, b = chain[0], chain[-1]
    total_d = 0
    for x in chain:
        try:
            total_d += int(x.get("duration_ms", 25))
        except (TypeError, ValueError):
            total_d += 25
    d = max(
        SWIPE_COALESCE_MIN_DURATION_MS,
        min(SWIPE_COALESCE_MAX_DURATION_MS, total_d),
    )
    return {
        "action": "swipe",
        "x1": int(a.get("x1", 0)),
        "y1": int(a.get("y1", 0)),
        "x2": int(b.get("x2", 0)),
        "y2": int(b.get("y2", 0)),
        "duration_ms": d,
    }


@router.websocket("/ws/{device_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    device_id: int,
    token: str = Query(...),
):
    # Authenticate
    async with AsyncSessionLocal() as db:
        user = await get_current_user_from_token(token, db)
        if not user:
            await websocket.close(code=4001, reason="Unauthorized")
            return

        # Check device access
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

    # ADB serializes commands per device: a background screencap blocks tap/key until it
    # finishes. One worker drains control messages first, then takes screenshots.
    control_queue: asyncio.Queue[dict] = asyncio.Queue()
    control_prefetch: deque[dict] = deque()
    session = {
        "subscribe_screenshots": False,
        "interval_sec": SCREENSHOT_INTERVAL_DEFAULT_MS / 1000.0,
        "stream_jpeg": True,
        "serial": None,
        "serial_cached_at": 0.0,
    }
    adaptive = {"last_sent_sig": None, "idle_streak": 0}

    def adaptive_reset() -> None:
        adaptive["last_sent_sig"] = None
        adaptive["idle_streak"] = 0

    async def refresh_serial_cache(force: bool = False) -> str | None:
        now = time.monotonic()
        if (
            not force
            and session["serial"]
            and (now - session["serial_cached_at"]) < SERIAL_CACHE_TTL_SEC
        ):
            return session["serial"]
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Device).where(Device.id == device_id))
            dev = result.scalar_one_or_none()
        serial = None
        if dev and dev.status == DeviceStatus.running and dev.adb_serial:
            serial = dev.adb_serial
        session["serial"] = serial
        session["serial_cached_at"] = time.monotonic()
        return serial

    def serial_for_control_sync() -> str | None:
        """Hot path: no DB round-trip when cache is warm."""
        now = time.monotonic()
        if (
            session["serial"]
            and (now - session["serial_cached_at"]) < SERIAL_CACHE_TTL_SEC
        ):
            return session["serial"]
        return None

    frame_state = {"next_at": time.monotonic()}
    screenshot_state = {"fail_streak": 0, "last_notify_monotonic": 0.0}

    def bump_next_frame_after_input() -> None:
        adaptive_reset()
        soon = time.monotonic() + POST_CONTROL_FRAME_GAP_SEC
        frame_state["next_at"] = min(frame_state["next_at"], soon)

    async def run_control_action(msg: dict) -> None:
        action = msg.get("action")
        if action == "_resume":
            return
        serial = serial_for_control_sync()
        if serial is None:
            serial = await refresh_serial_cache()
        if not serial:
            return
        try:
            if action == "tap":
                x, y = msg.get("x", 0), msg.get("y", 0)
                await adb_tool.tap(serial, int(x), int(y))
                await websocket.send_json({"type": "ack", "action": "tap", "x": x, "y": y})
            elif action == "swipe":
                x1, y1 = msg.get("x1", 0), msg.get("y1", 0)
                x2, y2 = msg.get("x2", 0), msg.get("y2", 0)
                duration = msg.get("duration_ms", 300)
                await adb_tool.swipe(serial, int(x1), int(y1), int(x2), int(y2), int(duration))
                await websocket.send_json({"type": "ack", "action": "swipe"})
            elif action == "keyevent":
                key = msg.get("key", "KEYCODE_HOME")
                await adb_tool.key_event(serial, key)
                await websocket.send_json({"type": "ack", "action": "keyevent", "key": key})
            elif action == "input_text":
                text = msg.get("text", "")
                await adb_tool.input_text(serial, text)
                await websocket.send_json({"type": "ack", "action": "input_text"})
            else:
                return
            bump_next_frame_after_input()
        except WebSocketDisconnect:
            raise
        except Exception as e:
            logger.debug(f"ADB control error device {device_id}: {e}")

    def control_pop_nowait() -> dict | None:
        if control_prefetch:
            return control_prefetch.popleft()
        try:
            return control_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def control_await_one() -> dict:
        if control_prefetch:
            return control_prefetch.popleft()
        return await control_queue.get()

    async def run_coalesced_swipe(first: dict) -> None:
        chain = [first]
        while len(chain) < SWIPE_COALESCE_MAX_SEGMENTS:
            nxt = control_pop_nowait()
            if nxt is None:
                break
            if nxt.get("action") == "_resume":
                continue
            if nxt.get("action") == "swipe" and _swipe_segments_chain(chain[-1], nxt):
                chain.append(nxt)
            else:
                control_prefetch.appendleft(nxt)
                break
        if len(chain) == 1:
            await run_control_action(chain[0])
        else:
            await run_control_action(_merge_swipe_chain(chain))

    async def dispatch_control(msg: dict) -> None:
        if msg.get("action") == "_resume":
            return
        if msg.get("action") == "swipe":
            await run_coalesced_swipe(msg)
        else:
            await run_control_action(msg)

    async def adb_orchestrator() -> None:
        try:
            while True:
                # Priority: drain all pending taps/swipes/keys before any screencap
                while True:
                    msg = control_pop_nowait()
                    if msg is None:
                        break
                    await dispatch_control(msg)

                if session["subscribe_screenshots"]:
                    wait = max(0.0, frame_state["next_at"] - time.monotonic())
                    get_control = asyncio.create_task(control_queue.get())
                    sleep_t = asyncio.create_task(asyncio.sleep(wait))
                    done, pending = await asyncio.wait(
                        {get_control, sleep_t},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                        try:
                            await t
                        except asyncio.CancelledError:
                            pass

                    if get_control in done:
                        msg = get_control.result()
                        await dispatch_control(msg)
                        continue

                    serial = await refresh_serial_cache()
                    if serial:
                        base_iv = session["interval_sec"]
                        try:
                            png_bytes = await adb_tool.screenshot(serial)
                            screenshot_state["fail_streak"] = 0
                            t_after = time.monotonic()
                            sig = _frame_signature(png_bytes)
                            use_jpeg = session.get("stream_jpeg", True)

                            if (
                                adaptive["last_sent_sig"] is not None
                                and sig == adaptive["last_sent_sig"]
                            ):
                                adaptive["idle_streak"] += 1
                                dwell = min(
                                    IDLE_DWELL_MAX_SEC,
                                    IDLE_DWELL_MIN_SEC
                                    + IDLE_DWELL_STEP_SEC * adaptive["idle_streak"],
                                )
                                frame_state["next_at"] = t_after + max(base_iv, dwell)
                            else:
                                adaptive["idle_streak"] = 0
                                adaptive["last_sent_sig"] = sig
                                dev_w, dev_h = _png_dimensions(png_bytes)
                                b64, fmt, w, h = _encode_live_frame(png_bytes, use_jpeg)
                                await websocket.send_json({
                                    "type": "screenshot",
                                    "data": b64,
                                    "format": fmt,
                                    "width": w,
                                    "height": h,
                                    "device_width": dev_w,
                                    "device_height": dev_h,
                                })
                                frame_state["next_at"] = t_after + base_iv
                        except WebSocketDisconnect:
                            raise
                        except Exception as e:
                            logger.debug(f"Screenshot error for device {device_id}: {e}")
                            await refresh_serial_cache(force=True)
                            t_now = time.monotonic()
                            if _adb_serial_not_found(e):
                                session["serial"] = None
                                session["serial_cached_at"] = 0.0
                                screenshot_state["fail_streak"] = min(
                                    screenshot_state["fail_streak"] + 1, 16
                                )
                                k = max(0, screenshot_state["fail_streak"] - 1)
                                delay = min(
                                    SCREENSHOT_FAIL_BACKOFF_MAX_SEC,
                                    SCREENSHOT_FAIL_BACKOFF_MIN_SEC * (2**min(k, 6)),
                                )
                                if (
                                    t_now - screenshot_state["last_notify_monotonic"]
                                    >= ADB_LOSS_NOTIFY_INTERVAL_SEC
                                ):
                                    screenshot_state["last_notify_monotonic"] = t_now
                                    try:
                                        await websocket.send_json({
                                            "type": "adb_unavailable",
                                            "message": (
                                                "الجهاز غير ظاهر في ADB — ربما أُغلق المحاكي أو انقطع الاتصال."
                                            ),
                                            "detail": str(e)[:400],
                                        })
                                    except Exception:
                                        pass
                                frame_state["next_at"] = t_now + max(delay, base_iv)
                            else:
                                screenshot_state["fail_streak"] = 0
                                frame_state["next_at"] = t_now + max(0.05, base_iv)
                    else:
                        frame_state["next_at"] = time.monotonic() + session["interval_sec"]
                else:
                    msg = await control_await_one()
                    await dispatch_control(msg)
        except asyncio.CancelledError:
            pass
        except WebSocketDisconnect:
            pass

    adb_task = asyncio.create_task(adb_orchestrator())

    try:
        # Send initial device status (client may disconnect immediately — e.g. React Strict Mode)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Device).where(Device.id == device_id))
            device = result.scalar_one_or_none()
            if device:
                session["serial"] = device.adb_serial
                session["serial_cached_at"] = time.monotonic()
                await websocket.send_json({
                    "type": "status",
                    "status": device.status.value,
                    "device_id": device_id,
                    "adb_serial": device.adb_serial,
                })

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                msg = json.loads(raw)
                action = msg.get("action")

                if action == "subscribe_screenshots":
                    interval_ms = _clamp_interval_ms(msg.get("interval_ms", SCREENSHOT_INTERVAL_DEFAULT_MS))
                    session["interval_sec"] = interval_ms / 1000.0
                    sm = msg.get("stream_mode", "jpeg")
                    session["stream_jpeg"] = str(sm).lower() not in ("png", "raw", "lossless")
                    adaptive_reset()
                    session["subscribe_screenshots"] = True
                    frame_state["next_at"] = time.monotonic()
                    await refresh_serial_cache(force=True)
                    await control_queue.put({"action": "_resume"})
                    await websocket.send_json({
                        "type": "ack",
                        "action": "subscribe_screenshots",
                        "interval_ms": interval_ms,
                        "stream_mode": "jpeg" if session["stream_jpeg"] else "png",
                    })

                elif action == "unsubscribe_screenshots":
                    session["subscribe_screenshots"] = False
                    await websocket.send_json({"type": "ack", "action": "unsubscribe_screenshots"})

                elif action in ("tap", "swipe", "keyevent", "input_text"):
                    await control_queue.put(msg)

                elif action == "ping":
                    await websocket.send_json({"type": "pong"})

                else:
                    await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})

            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except WebSocketDisconnect:
                    break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for device {device_id}, user {user.id}")
    except Exception as e:
        logger.error(f"WebSocket error for device {device_id}: {e}")
    finally:
        adb_task.cancel()
        try:
            await adb_task
        except asyncio.CancelledError:
            pass
        await ws_manager.disconnect(websocket, device_id)
