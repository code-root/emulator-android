import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.deps import get_db, get_current_user
from db.models import Device, DeviceStatus, ProxyConfig, ProxyType, User
from core.tools.adb import ADBTool
from core.tools.mitm_tool import MitmManager
from config import settings

router = APIRouter(prefix="/devices", tags=["proxy"])
adb_tool = ADBTool()
mitm_manager = MitmManager()
logger = logging.getLogger(__name__)


class ProxyConfigResponse(BaseModel):
    id: int
    device_id: int
    enabled: bool
    proxy_type: str
    host: Optional[str]
    port: Optional[int]
    username: Optional[str]
    password: Optional[str]
    mitm_active: bool
    mitm_port: Optional[int]
    updated_at: datetime

    class Config:
        from_attributes = True


class ProxyUpdateRequest(BaseModel):
    enabled: bool = False
    proxy_type: str = "http"
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None


async def _get_device_or_404(device_id: int, db: AsyncSession, user: User) -> Device:
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return device


async def _get_or_create_proxy(device_id: int, db: AsyncSession) -> ProxyConfig:
    result = await db.execute(select(ProxyConfig).where(ProxyConfig.device_id == device_id))
    proxy = result.scalar_one_or_none()
    if not proxy:
        proxy = ProxyConfig(device_id=device_id, enabled=False)
        db.add(proxy)
        await db.flush()
    return proxy


@router.get("/{device_id}/proxy", response_model=ProxyConfigResponse)
async def get_proxy(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_device_or_404(device_id, db, current_user)
    proxy = await _get_or_create_proxy(device_id, db)
    await db.refresh(proxy)
    return proxy


@router.put("/{device_id}/proxy", response_model=ProxyConfigResponse)
async def update_proxy(
    device_id: int,
    data: ProxyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    proxy = await _get_or_create_proxy(device_id, db)

    proxy.enabled = data.enabled
    proxy.proxy_type = ProxyType(data.proxy_type) if data.proxy_type else ProxyType.http
    proxy.host = data.host
    proxy.port = data.port
    proxy.username = data.username
    proxy.password = data.password

    # Apply to running device
    if device.status == DeviceStatus.running and device.adb_serial:
        try:
            if data.enabled and data.host and data.port:
                await mitm_manager.set_device_proxy(adb_tool, device.adb_serial, data.host, data.port)
            else:
                await mitm_manager.clear_device_proxy(adb_tool, device.adb_serial)
        except Exception as e:
            logger.warning(f"Failed to apply proxy to device {device_id}: {e}")

    await db.flush()
    await db.refresh(proxy)
    return proxy


@router.post("/{device_id}/proxy/start")
async def start_proxy(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(status_code=400, detail="Device must be running")

    proxy = await _get_or_create_proxy(device_id, db)
    if proxy.mitm_active:
        raise HTTPException(status_code=400, detail="Mitmproxy is already running")

    mitm_port = settings.MITMPROXY_BASE_PORT + device_id
    try:
        pid = await mitm_manager.start(device_id, mitm_port)
        proxy.mitm_active = True
        proxy.mitm_port = mitm_port
        proxy.mitm_pid = pid
        proxy.enabled = True
        proxy.host = "127.0.0.1"
        proxy.port = mitm_port

        await mitm_manager.set_device_proxy(adb_tool, device.adb_serial, "127.0.0.1", mitm_port)
        await db.flush()
        return {"success": True, "port": mitm_port, "pid": pid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start mitmproxy: {e}")


@router.post("/{device_id}/proxy/stop")
async def stop_proxy(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    proxy = await _get_or_create_proxy(device_id, db)

    try:
        await mitm_manager.stop(device_id)
    except Exception as e:
        logger.warning(f"Error stopping mitmproxy for device {device_id}: {e}")

    proxy.mitm_active = False
    proxy.mitm_pid = None

    if device.status == DeviceStatus.running and device.adb_serial:
        try:
            await mitm_manager.clear_device_proxy(adb_tool, device.adb_serial)
        except Exception:
            pass

    await db.flush()
    return {"success": True}


@router.get("/{device_id}/proxy/traffic")
async def get_traffic(
    device_id: int,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_device_or_404(device_id, db, current_user)
    try:
        traffic = await mitm_manager.get_traffic_log(device_id, limit=limit)
        return {"entries": traffic, "count": len(traffic)}
    except Exception as e:
        return {"entries": [], "count": 0, "error": str(e)}
