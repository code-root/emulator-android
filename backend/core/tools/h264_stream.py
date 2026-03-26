"""
H.264 streaming from Android emulators via ADB screenrecord.
Uses the device hardware H.264 encoder for low-latency live streaming.

Flow:
  adb exec-out screenrecord --output-format=h264 ... -
    → raw Annex-B H.264 bitstream
    → NAL unit parser
    → binary WebSocket frames
    → browser VideoDecoder (WebCodecs)
    → <canvas>

Latency target: < 100 ms  (vs 200-600 ms with PNG screencap)
"""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import AsyncIterator, Dict, Any, Optional, Tuple, List

logger = logging.getLogger(__name__)

# ─── H.264 Annex-B start codes ───────────────────────────────────────────────
_SC4 = b"\x00\x00\x00\x01"
_SC3 = b"\x00\x00\x01"

# ─── NAL unit types ──────────────────────────────────────────────────────────
NAL_NON_IDR = 1   # P/B-frame
NAL_PART_A  = 2
NAL_IDR     = 5   # keyframe
NAL_SEI     = 6
NAL_SPS     = 7
NAL_PPS     = 8
NAL_AUD     = 9

# ─── Binary wire protocol (backend → frontend) ───────────────────────────────
#
#  CONFIG  (type = 0x01)
#   [0]       type = 1
#   [1..4]    width  (uint32 LE)
#   [5..8]    height (uint32 LE)
#   [9..10]   codec_len (uint16 LE)
#   [11..11+codec_len-1]  codec string (UTF-8)  e.g. "avc1.640028"
#   [11+codec_len ..]     SPS+PPS raw bytes (Annex-B)
#
#  FRAME  (type = 0x02)
#   [0]       type = 2
#   [1]       flags  (bit-0 = keyframe)
#   [2..9]    PTS µs (uint64 LE)
#   [10..]    H.264 NAL unit (Annex-B, with start code)

MSG_CONFIG = 0x01
MSG_FRAME  = 0x02


def pack_config(codec: str, width: int, height: int, sps_pps: bytes) -> bytes:
    codec_b = codec.encode("utf-8")
    hdr = struct.pack("<BIIH", MSG_CONFIG, width, height, len(codec_b))
    return hdr + codec_b + sps_pps


def pack_frame(keyframe: bool, pts: int, h264_data: bytes) -> bytes:
    flags = 0x01 if keyframe else 0x00
    hdr = struct.pack("<BBQ", MSG_FRAME, flags, pts)
    return hdr + h264_data


# ─── NAL parser ──────────────────────────────────────────────────────────────

def _nal_type(b: int) -> int:
    return b & 0x1F


def _parse_buffer(buf: bytes) -> Tuple[List[Tuple[int, bytes]], bytes]:
    """
    Extract all *complete* NAL units from a raw Annex-B buffer.
    Returns (units, leftover) where each unit is (nal_type, raw_bytes_with_start_code).
    The last, potentially-incomplete NAL is kept in leftover.
    """
    positions: List[Tuple[int, int]] = []  # (offset, start_code_len)
    i = 0
    end = len(buf)
    while i < end:
        if i + 4 <= end and buf[i : i + 4] == _SC4:
            positions.append((i, 4))
            i += 4
            continue
        if i + 3 <= end and buf[i : i + 3] == _SC3:
            # avoid double-counting the last 3 bytes of a 4-byte start code
            if not positions or positions[-1][0] + positions[-1][1] != i:
                positions.append((i, 3))
                i += 3
                continue
        i += 1

    if len(positions) < 2:
        return [], buf

    units: List[Tuple[int, bytes]] = []
    for idx in range(len(positions) - 1):
        pos, sc_len = positions[idx]
        next_pos = positions[idx + 1][0]
        raw = buf[pos:next_pos]
        payload = raw[sc_len:]
        if payload:
            units.append((_nal_type(payload[0]), raw))

    leftover = buf[positions[-1][0] :]
    return units, leftover


def _extract_codec(sps_raw: bytes) -> str:
    """Derive avc1.PPCCLL codec string from raw SPS NAL (includes start code)."""
    try:
        sc_len = 4 if sps_raw[:4] == _SC4 else 3
        rbsp = sps_raw[sc_len + 1 :]      # skip start-code + NAL-header byte (0x67)
        if len(rbsp) >= 3:
            return f"avc1.{rbsp[0]:02X}{rbsp[1]:02X}{rbsp[2]:02X}"
    except Exception:
        pass
    return "avc1.640028"   # High Profile, Level 4.0 — safe fallback


# ─── Streamer ─────────────────────────────────────────────────────────────────

class H264Streamer:
    """
    Async generator that captures H.264 from an Android device and yields
    packed binary messages ready to send over a binary WebSocket.

    Usage::

        streamer = H264Streamer()
        async for binary_msg in streamer.stream(serial, width=720, height=1280):
            await websocket.send_bytes(binary_msg)
    """

    async def stream(
        self,
        serial: str,
        width: int = 720,
        height: int = 1280,
        bit_rate: str = "2M",
        fps: int = 30,
    ) -> AsyncIterator[bytes]:
        """
        Yield packed binary messages.  Auto-restarts when screenrecord hits
        its 3-minute time limit or on transient errors.
        """
        while True:
            try:
                async for msg in self._session(serial, width, height, bit_rate, fps):
                    yield msg
                await asyncio.sleep(0.05)        # brief gap between sessions
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("H264Streamer error (serial=%s): %s — restarting", serial, exc)
                await asyncio.sleep(1.0)

    async def _session(
        self,
        serial: str,
        width: int,
        height: int,
        bit_rate: str,
        fps: int,
    ) -> AsyncIterator[bytes]:
        """Run one screenrecord session and parse the resulting Annex-B stream."""
        cmd = [
            "adb", "-s", serial,
            "exec-out",
            "screenrecord",
            "--output-format=h264",
            f"--size={width}x{height}",
            f"--bit-rate={bit_rate}",
            "--time-limit=175",    # restart safely before Android's 180 s max
            "-",
        ]
        logger.info("H264: starting session — %s", " ".join(cmd[3:]))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        sps_raw:    Optional[bytes] = None
        pps_raw:    Optional[bytes] = None
        codec_str:  str = "avc1.640028"
        config_sent: bool = False
        pts:        int = 0
        frame_us:   int = max(1, 1_000_000 // fps)
        buf:        bytes = b""

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        proc.stdout.read(131072),   # 128 KB reads
                        timeout=8.0,
                    )
                except asyncio.TimeoutError:
                    logger.info("H264: read timeout for %s", serial)
                    break

                if not chunk:
                    logger.info("H264: EOF for %s", serial)
                    break

                buf += chunk
                units, buf = _parse_buffer(buf)

                for nal_t, nal_raw in units:
                    if nal_t == NAL_SPS:
                        sps_raw    = nal_raw
                        codec_str  = _extract_codec(nal_raw)
                        config_sent = False       # new SPS → re-send config

                    elif nal_t == NAL_PPS:
                        pps_raw = nal_raw
                        if sps_raw and pps_raw and not config_sent:
                            yield pack_config(codec_str, width, height, sps_raw + pps_raw)
                            config_sent = True

                    elif nal_t in (NAL_IDR, NAL_NON_IDR, NAL_PART_A):
                        pts += frame_us
                        yield pack_frame(nal_t == NAL_IDR, pts, nal_raw)

                    # skip AUD / SEI / end-of-sequence NALs

        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    proc.kill()


# ─── Module-level singleton ───────────────────────────────────────────────────
h264_streamer = H264Streamer()
