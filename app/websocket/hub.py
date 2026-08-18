"""
RedSight - High-Performance Local AI Intelligence Platform
WebSocket Hub for Real-Time Streaming

Provides a centralized WebSocket hub for:
- Streaming chat responses (token-by-token)
- Live telemetry updates (GPU, system metrics)
- Multi-agent orchestration status
- Alert notifications
- Plugin event broadcasting
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class WSMessageType(str, Enum):
    """WebSocket message types."""
    TOKEN = "token"
    DONE = "done"
    ERROR = "error"
    SYSTEM_STATUS = "system_status"
    GPU_STATUS = "gpu_status"
    AGENT_STATUS = "agent_status"
    ALERT = "alert"
    PLUGIN_EVENT = "plugin_event"
    BROADCAST = "broadcast"


@dataclass
class WSMessage:
    """WebSocket message envelope."""
    type: WSMessageType
    data: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "type": self.type.value,
            "data": self.data,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())


class WebSocketSession:
    """Represents an active WebSocket connection."""

    def __init__(self, session_id: str, websocket):
        self.session_id = session_id
        self.websocket = websocket
        self.connected_at = time.time()
        self.subscriptions: Set[str] = set()
        self.is_active = True

    async def send(self, message: WSMessage) -> bool:
        """Send a message to this session."""
        if not self.is_active:
            return False
        try:
            await self.websocket.send_text(message.to_json())
            return True
        except Exception as e:
            logger.warning(f"Failed to send to session {self.session_id}: {e}")
            self.is_active = False
            return False

    async def send_text(self, text: str):
        """Send raw text."""
        if not self.is_active:
            return
        try:
            await self.websocket.send_text(text)
        except Exception as e:
            logger.warning(f"Failed to send text to session {self.session_id}: {e}")
            self.is_active = False

    async def close(self):
        """Close the session."""
        self.is_active = False
        try:
            await self.websocket.close()
        except Exception:
            pass


class WebSocketHub:
    """Central hub for managing WebSocket connections and broadcasting."""

    def __init__(self):
        self._sessions: Dict[str, WebSocketSession] = {}
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._broadcast_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def connect(self, websocket) -> str:
        """Connect a new WebSocket and return session ID."""
        await websocket.accept()
        session_id = str(uuid.uuid4())
        session = WebSocketSession(session_id, websocket)
        self._sessions[session_id] = session

        # Subscribe to default channels
        session.subscriptions.update(["system_status", "gpu_status", "alerts"])

        logger.info(f"WebSocket connected: {session_id}")
        return session_id

    async def disconnect(self, session_id: str):
        """Disconnect a session."""
        session = self._sessions.pop(session_id, None)
        if session:
            await session.close()
            logger.info(f"WebSocket disconnected: {session_id}")

    async def send_to_session(self, session_id: str, message: WSMessage) -> bool:
        """Send a message to a specific session."""
        session = self._sessions.get(session_id)
        if session:
            return await session.send(message)
        return False

    async def broadcast(self, message: WSMessage, exclude_session: Optional[str] = None):
        """Broadcast a message to all sessions."""
        for sid, session in self._sessions.items():
            if sid != exclude_session:
                await session.send(message)

    def subscribe(self, session_id: str, channel: str):
        """Subscribe a session to a channel."""
        session = self._sessions.get(session_id)
        if session:
            session.subscriptions.add(channel)

    def unsubscribe(self, session_id: str, channel: str):
        """Unsubscribe a session from a channel."""
        session = self._sessions.get(session_id)
        if session:
            session.subscriptions.discard(channel)

    def on_event(self, event_type: str, callback: Callable):
        """Register a callback for an event type."""
        self._subscribers[event_type].append(callback)

    async def emit_event(self, event_type: str, data: Dict[str, Any]):
        """Emit an event to all subscribers."""
        for callback in self._subscribers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"Event callback error for {event_type}: {e}")

    async def start_broadcast_loop(self):
        """Start the broadcast queue processing loop."""
        self._running = True
        self._task = asyncio.create_task(self._process_broadcast_queue())
        logger.info("WebSocket broadcast loop started")

    async def stop_broadcast_loop(self):
        """Stop the broadcast queue processing loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("WebSocket broadcast loop stopped")

    async def _process_broadcast_queue(self):
        """Process broadcast messages from the queue."""
        while self._running:
            try:
                message = await asyncio.wait_for(self._broadcast_queue.get(), timeout=1.0)
                await self.broadcast(message)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Broadcast queue error: {e}")

    async def send_broadcast(self, message: WSMessage):
        """Enqueue a broadcast message."""
        await self._broadcast_queue.put(message)

    @property
    def active_sessions(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)

    async def get_session_list(self) -> List[Dict[str, Any]]:
        """Get list of active sessions."""
        return [
            {
                "session_id": sid,
                "connected_at": s.connected_at,
                "subscriptions": list(s.subscriptions),
                "is_active": s.is_active,
            }
            for sid, s in self._sessions.items()
            if s.is_active
        ]


# ─── Global Hub Instance ─────────────────────────────────────────────

ws_hub: Optional[WebSocketHub] = None


def get_ws_hub() -> WebSocketHub:
    """Get the global WebSocket hub instance."""
    global ws_hub
    if ws_hub is None:
        ws_hub = WebSocketHub()
    return ws_hub


async def initialize_ws_hub():
    """Initialize and start the WebSocket hub."""
    hub = get_ws_hub()
    await hub.start_broadcast_loop()
    logger.info("WebSocket hub initialized")
    return hub


async def shutdown_ws_hub():
    """Shutdown the WebSocket hub."""
    global ws_hub
    if ws_hub:
        await ws_hub.stop_broadcast_loop()
        for session in list(ws_hub._sessions.values()):
            await session.close()
        ws_hub = None
        logger.info("WebSocket hub shut down")
