import asyncio
import json
import logging
from collections import defaultdict
from typing import Dict, List, Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections per device."""

    def __init__(self):
        # device_id -> list of (websocket, user_id)
        self._connections: Dict[int, List[tuple]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, device_id: int, user_id: int) -> None:
        """Register a WebSocket connection for a device."""
        async with self._lock:
            self._connections[device_id].append((ws, user_id))
        logger.info(f"WS connected: device={device_id}, user={user_id}, total={len(self._connections[device_id])}")

    async def disconnect(self, ws: WebSocket, device_id: int) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            connections = self._connections.get(device_id, [])
            self._connections[device_id] = [(w, u) for w, u in connections if w != ws]
            if not self._connections[device_id]:
                del self._connections[device_id]
        logger.info(f"WS disconnected: device={device_id}")

    async def broadcast(self, device_id: int, data: Dict[str, Any]) -> None:
        """Send data to all subscribers of a device."""
        connections = list(self._connections.get(device_id, []))
        if not connections:
            return

        message = json.dumps(data)
        dead = []
        for ws, user_id in connections:
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.debug(f"WS send failed to user {user_id} on device {device_id}: {e}")
                dead.append((ws, user_id))

        # Clean up dead connections
        if dead:
            async with self._lock:
                self._connections[device_id] = [
                    (w, u) for w, u in self._connections.get(device_id, [])
                    if (w, u) not in dead
                ]

    async def broadcast_all(self, data: Dict[str, Any]) -> None:
        """Send data to all connected WebSocket clients across all devices."""
        message = json.dumps(data)
        all_connections = []
        for device_id, connections in list(self._connections.items()):
            for ws, user_id in connections:
                all_connections.append((device_id, ws, user_id))

        dead = []
        for device_id, ws, user_id in all_connections:
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.debug(f"WS broadcast_all failed: {e}")
                dead.append((device_id, ws))

        if dead:
            async with self._lock:
                for device_id, ws in dead:
                    self._connections[device_id] = [
                        (w, u) for w, u in self._connections.get(device_id, [])
                        if w != ws
                    ]

    def get_subscriber_count(self, device_id: int) -> int:
        """Return number of active subscribers for a device."""
        return len(self._connections.get(device_id, []))

    def get_all_device_ids(self) -> List[int]:
        """Return all device IDs that have active connections."""
        return list(self._connections.keys())

    async def send_to_user(self, user_id: int, data: Dict[str, Any]) -> None:
        """Send data to all connections for a specific user."""
        message = json.dumps(data)
        for device_id, connections in list(self._connections.items()):
            for ws, uid in connections:
                if uid == user_id:
                    try:
                        await ws.send_text(message)
                    except Exception:
                        pass


# Global singleton instance
ws_manager = WebSocketManager()
