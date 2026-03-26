from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, Float, ForeignKey,
    DateTime, Text, Enum as SAEnum, func
)
from sqlalchemy.orm import relationship, DeclarativeBase
import enum


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class DeviceStatus(str, enum.Enum):
    created = "created"
    booting = "booting"
    running = "running"
    stopped = "stopped"
    error = "error"


class ProxyType(str, enum.Enum):
    http = "http"
    socks5 = "socks5"


class OperationStatus(str, enum.Enum):
    success = "success"
    failure = "failure"
    pending = "pending"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(256), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.user, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    github_id = Column(BigInteger, unique=True, nullable=True, index=True)
    github_login = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    devices = relationship("Device", back_populates="owner", cascade="all, delete-orphan")
    logs = relationship("OperationLog", back_populates="user", cascade="all, delete-orphan")
    stored_apks = relationship("StoredApk", back_populates="owner", cascade="all, delete-orphan")


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False, index=True)
    status = Column(SAEnum(DeviceStatus), default=DeviceStatus.created, nullable=False)
    avd_name = Column(String(128), nullable=True)
    adb_port = Column(Integer, nullable=True)
    adb_serial = Column(String(64), nullable=True)
    scrcpy_port = Column(Integer, nullable=True)
    qmp_port = Column(Integer, nullable=True)
    console_port = Column(Integer, nullable=True)
    pid = Column(Integer, nullable=True)
    ram_mb = Column(Integer, default=2048, nullable=False)
    cpu_cores = Column(Integer, default=2, nullable=False)
    api_level = Column(Integer, default=31, nullable=False)
    arch = Column(String(32), default="x86_64", nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    owner = relationship("User", back_populates="devices")
    fingerprint = relationship("DeviceFingerprint", back_populates="device", uselist=False, cascade="all, delete-orphan")
    proxy_config = relationship("ProxyConfig", back_populates="device", uselist=False, cascade="all, delete-orphan")
    logs = relationship("OperationLog", back_populates="device", cascade="all, delete-orphan")


class DeviceFingerprint(Base):
    __tablename__ = "device_fingerprints"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, unique=True)
    imei = Column(String(20), nullable=True)
    android_id = Column(String(32), nullable=True)
    mac_address = Column(String(20), nullable=True)
    device_model = Column(String(128), nullable=True)
    manufacturer = Column(String(128), nullable=True)
    brand = Column(String(128), nullable=True)
    device_codename = Column(String(128), nullable=True)
    build_fingerprint = Column(String(512), nullable=True)
    sdk_version = Column(Integer, nullable=True)
    android_version = Column(String(32), nullable=True)
    board = Column(String(128), nullable=True)
    hardware = Column(String(128), nullable=True)
    serial_number = Column(String(64), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    altitude = Column(Float, nullable=True)
    network_type = Column(String(16), nullable=True)
    ip_address = Column(String(45), nullable=True)
    timezone = Column(String(64), nullable=True)
    language = Column(String(10), nullable=True)
    country = Column(String(10), nullable=True)
    # Samsung / Odin-style build labels (spoofed via setprop where permitted)
    ap_version = Column(String(64), nullable=True)
    csc_version = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    device = relationship("Device", back_populates="fingerprint")


class ProxyConfig(Base):
    __tablename__ = "proxy_configs"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, unique=True)
    enabled = Column(Boolean, default=False, nullable=False)
    proxy_type = Column(SAEnum(ProxyType), default=ProxyType.http, nullable=False)
    host = Column(String(256), nullable=True)
    port = Column(Integer, nullable=True)
    username = Column(String(128), nullable=True)
    password = Column(String(256), nullable=True)
    mitm_active = Column(Boolean, default=False, nullable=False)
    mitm_port = Column(Integer, nullable=True)
    mitm_pid = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    device = relationship("Device", back_populates="proxy_config")


class StoredApk(Base):
    """مكتبة APK مشتركة — رفع مرة وتثبيت على أي جهاز شغّال."""

    __tablename__ = "stored_apks"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    display_name = Column(String(256), nullable=True)
    stored_filename = Column(String(512), nullable=False, unique=True)
    original_filename = Column(String(256), nullable=False)
    size_bytes = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    owner = relationship("User", back_populates="stored_apks")


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(128), nullable=False)
    status = Column(SAEnum(OperationStatus), default=OperationStatus.pending, nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    device = relationship("Device", back_populates="logs")
    user = relationship("User", back_populates="logs")
