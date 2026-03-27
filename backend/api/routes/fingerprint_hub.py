"""
واجهة REST موحّدة للبصمة تحت /api/fingerprint/* (بالإضافة إلى /api/devices/.../fingerprint).
تدعم JSON موسّع، إصدارات، تحقق تناسق، تطبيق على الجهاز.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_current_user
from db.models import Device, DeviceFingerprint, DeviceStatus, FingerprintRevision, User
from core.fingerprint.generator import FingerprintGenerator
from core.fingerprint.spoofer import FingerprintSpoofer
from core.fingerprint.samsung_enhanced import (
    is_samsung_fingerprint,
    merge_profile_defaults_for_apply,
    samsung_apply_user_notes,
)
from core.fingerprint.merge import fingerprint_row_to_apply_dict, parse_extended
from core.fingerprint.consistency import run_consistency_checks
from core.emulator.avd import sync_avd_hardware_with_fingerprint
from core.tools.adb import ADBTool

router = APIRouter(prefix="/fingerprint", tags=["fingerprint-hub"])
fp_generator = FingerprintGenerator()
fp_spoofer = FingerprintSpoofer()
adb_tool = ADBTool()


class FingerprintFullResponse(BaseModel):
    id: int
    device_id: int
    imei: Optional[str] = None
    android_id: Optional[str] = None
    mac_address: Optional[str] = None
    device_model: Optional[str] = None
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    device_codename: Optional[str] = None
    build_fingerprint: Optional[str] = None
    sdk_version: Optional[int] = None
    android_version: Optional[str] = None
    board: Optional[str] = None
    hardware: Optional[str] = None
    serial_number: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    network_type: Optional[str] = None
    ip_address: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    ap_version: Optional[str] = None
    csc_version: Optional[str] = None
    extended: Dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime
    consistency: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class FingerprintPutBody(BaseModel):
    imei: Optional[str] = None
    android_id: Optional[str] = None
    mac_address: Optional[str] = None
    device_model: Optional[str] = None
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    device_codename: Optional[str] = None
    build_fingerprint: Optional[str] = None
    sdk_version: Optional[int] = None
    android_version: Optional[str] = None
    board: Optional[str] = None
    hardware: Optional[str] = None
    serial_number: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    network_type: Optional[str] = None
    ip_address: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    ap_version: Optional[str] = None
    csc_version: Optional[str] = None
    extended: Optional[Dict[str, Any]] = None
    revision_label: Optional[str] = None


async def _device_fp(
    device_id: int, db: AsyncSession, user: User
) -> tuple[Device, DeviceFingerprint]:
    r = await db.execute(select(Device).where(Device.id == device_id))
    device = r.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    if device.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(403, "Access denied")
    r2 = await db.execute(select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id))
    fp = r2.scalar_one_or_none()
    if not fp:
        fp = DeviceFingerprint(device_id=device_id)
        db.add(fp)
        await db.flush()
    return device, fp


def _row_to_response(fp: DeviceFingerprint, with_checks: bool = True) -> FingerprintFullResponse:
    ext = parse_extended(fp.extended_json)
    flat = fingerprint_row_to_apply_dict(fp)
    flat.pop("_extended_raw", None)
    cons = run_consistency_checks(flat) if with_checks else None
    return FingerprintFullResponse(
        id=fp.id,
        device_id=fp.device_id,
        imei=fp.imei,
        android_id=fp.android_id,
        mac_address=fp.mac_address,
        device_model=fp.device_model,
        manufacturer=fp.manufacturer,
        brand=fp.brand,
        device_codename=fp.device_codename,
        build_fingerprint=fp.build_fingerprint,
        sdk_version=fp.sdk_version,
        android_version=fp.android_version,
        board=fp.board,
        hardware=fp.hardware,
        serial_number=fp.serial_number,
        latitude=fp.latitude,
        longitude=fp.longitude,
        altitude=fp.altitude,
        network_type=fp.network_type,
        ip_address=fp.ip_address,
        timezone=fp.timezone,
        language=fp.language,
        country=fp.country,
        ap_version=fp.ap_version,
        csc_version=fp.csc_version,
        extended=ext,
        updated_at=fp.updated_at,
        consistency=cons,
    )


async def _next_revision_version(db: AsyncSession, device_id: int) -> int:
    q = await db.scalar(
        select(func.coalesce(func.max(FingerprintRevision.version), 0)).where(
            FingerprintRevision.device_id == device_id
        )
    )
    return int(q or 0) + 1


async def _save_revision(
    db: AsyncSession,
    device_id: int,
    fp: DeviceFingerprint,
    label: Optional[str],
) -> None:
    snap = _row_to_response(fp, with_checks=False).model_dump()
    snap["extended"] = parse_extended(fp.extended_json)
    rev = FingerprintRevision(
        device_id=device_id,
        fingerprint_id=fp.id,
        version=await _next_revision_version(db, device_id),
        label=label or "snapshot",
        snapshot_json=json.dumps(snap, default=str),
    )
    db.add(rev)


def _apply_body_to_row(fp: DeviceFingerprint, data: FingerprintPutBody) -> None:
    d = data.model_dump(exclude_none=True, exclude={"extended", "revision_label"})
    for k, v in d.items():
        if hasattr(fp, k):
            setattr(fp, k, v)
    if data.extended is not None:
        fp.extended_json = json.dumps(data.extended, ensure_ascii=False)


@router.get("/{device_id}", response_model=FingerprintFullResponse)
async def get_fingerprint_hub(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _, fp = await _device_fp(device_id, db, user)
    await db.refresh(fp)
    return _row_to_response(fp)


@router.put("/{device_id}", response_model=FingerprintFullResponse)
async def put_fingerprint_hub(
    device_id: int,
    body: FingerprintPutBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    device, fp = await _device_fp(device_id, db, user)
    await _save_revision(db, device_id, fp, body.revision_label or "before_put")
    _apply_body_to_row(fp, body)
    await db.flush()
    await db.refresh(fp)
    sync_avd_hardware_with_fingerprint(device.avd_name, fp)
    return _row_to_response(fp)


@router.post("/{device_id}/apply")
async def apply_fingerprint_hub(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    device, fp = await _device_fp(device_id, db, user)
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(400, "Device must be running with ADB serial")
    data = fingerprint_row_to_apply_dict(fp, {"console_port": device.console_port})
    data.pop("_extended_raw", None)
    data = merge_profile_defaults_for_apply(data)
    chk = run_consistency_checks({k: v for k, v in data.items() if k != "_extended_raw"})
    if not chk["ok"]:
        raise HTTPException(422, detail={"message": "Consistency check failed", **chk})
    try:
        report = await fp_spoofer.apply(adb_tool, device.adb_serial, data)
        await _save_revision(db, device_id, fp, "after_apply")
        await db.flush()
        deep = is_samsung_fingerprint(data)
        note, detail = samsung_apply_user_notes(deep)
        return {
            "success": True,
            "report": report,
            "consistency_warnings": chk.get("warnings", []),
            "samsung_extended_spoof": deep,
            "note": note,
            "detail": detail,
        }
    except Exception as e:
        raise HTTPException(500, detail=f"Apply failed: {e}")


@router.post("/{device_id}/randomize", response_model=FingerprintFullResponse)
async def randomize_fingerprint_hub(
    device_id: int,
    device_model: Optional[str] = None,
    apply: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    device, fp = await _device_fp(device_id, db, user)
    await _save_revision(db, device_id, fp, "before_randomize")
    new_data = fp_generator.generate(device_model=device_model)
    ext = new_data.pop("extended", None)
    for k, v in new_data.items():
        if hasattr(fp, k):
            setattr(fp, k, v)
    if ext is not None:
        fp.extended_json = json.dumps(ext, ensure_ascii=False)
    await db.flush()
    await db.refresh(fp)
    sync_avd_hardware_with_fingerprint(device.avd_name, fp)
    if apply and device.status == DeviceStatus.running and device.adb_serial:
        try:
            d = fingerprint_row_to_apply_dict(fp, {"console_port": device.console_port})
            d = merge_profile_defaults_for_apply(d)
            await fp_spoofer.apply(adb_tool, device.adb_serial, d)
        except Exception:
            pass
    return _row_to_response(fp)


@router.get("/{device_id}/revisions")
async def list_revisions(
    device_id: int,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _device_fp(device_id, db, user)
    r = await db.execute(
        select(FingerprintRevision)
        .where(FingerprintRevision.device_id == device_id)
        .order_by(FingerprintRevision.version.desc())
        .limit(limit)
    )
    rows = r.scalars().all()
    return [
        {
            "id": x.id,
            "version": x.version,
            "label": x.label,
            "created_at": x.created_at,
        }
        for x in rows
    ]


@router.post("/{device_id}/revert/{revision_id}", response_model=FingerprintFullResponse)
async def revert_fingerprint(
    device_id: int,
    revision_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    device, fp = await _device_fp(device_id, db, user)
    r = await db.execute(
        select(FingerprintRevision).where(
            FingerprintRevision.id == revision_id,
            FingerprintRevision.device_id == device_id,
        )
    )
    rev = r.scalar_one_or_none()
    if not rev:
        raise HTTPException(404, "Revision not found")
    await _save_revision(db, device_id, fp, "before_revert")
    snap = json.loads(rev.snapshot_json)
    ext = snap.pop("extended", None)
    col_names = {c.name for c in DeviceFingerprint.__table__.columns}
    for k, v in snap.items():
        if k in ("id", "device_id", "updated_at", "consistency"):
            continue
        if k in col_names:
            setattr(fp, k, v)
    fp.extended_json = json.dumps(ext, ensure_ascii=False) if ext else None
    await db.flush()
    await db.refresh(fp)
    sync_avd_hardware_with_fingerprint(device.avd_name, fp)
    return _row_to_response(fp)


@router.get("/{device_id}/compare")
async def compare_revision(
    device_id: int,
    revision_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _, fp = await _device_fp(device_id, db, user)
    r = await db.execute(
        select(FingerprintRevision).where(
            FingerprintRevision.id == revision_id,
            FingerprintRevision.device_id == device_id,
        )
    )
    rev = r.scalar_one_or_none()
    if not rev:
        raise HTTPException(404, "Revision not found")
    old = json.loads(rev.snapshot_json)
    cur = _row_to_response(fp, with_checks=False).model_dump()
    keys = set(old.keys()) | set(cur.keys())
    keys.discard("consistency")
    diff: Dict[str, List[Any]] = {}
    for k in sorted(keys):
        if k == "extended":
            if json.dumps(old.get(k), sort_keys=True) != json.dumps(cur.get(k), sort_keys=True):
                diff[k] = [old.get(k), cur.get(k)]
            continue
        if old.get(k) != cur.get(k):
            diff[k] = [old.get(k), cur.get(k)]
    return {"revision_id": revision_id, "diff": diff}


@router.post("/{device_id}/validate")
async def validate_only(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _, fp = await _device_fp(device_id, db, user)
    data = fingerprint_row_to_apply_dict(fp)
    data.pop("_extended_raw", None)
    return run_consistency_checks(data)


@router.get("/profiles/list")
async def list_profiles():
    from core.fingerprint.generator import DEVICE_PROFILES

    return [{"device_model": p["device_model"], "manufacturer": p.get("manufacturer")} for p in DEVICE_PROFILES]
