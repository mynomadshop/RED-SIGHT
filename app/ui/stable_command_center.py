"""Stability-focused compatibility layer for the RedSight Command Center.

The original CommandCenterMainWindow remains untouched so historical Stage
repair/install tooling that expects it continues to work. This subclass keeps
that UI and its hooks while moving slow network/memory work off the Qt event
thread and preventing overlapping health polls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .command_center import (
    ChatWidget,
    CommandCenterMainWindow,
    HealthDashboardWidget,
    _redsight_stage10_commit,
    _redsight_stage10_messages,
)
from .runtime_services import extract_chat_response

logger = logging.getLogger(__name__)


class StableCommandCenterMainWindow(CommandCenterMainWindow):
    """Drop-in Command Center with non-blocking service calls and task guards."""

    def __init__(self, api_base_url: str = "http://127.0.0.1:8000"):
        self._dashboard_task: asyncio.Task[Any] | None = None
        self._chat_tasks: set[asyncio.Task[Any]] = set()
        super().__init__(api_base_url=api_base_url)

    def _spawn(self, coro: Any, *, track_chat: bool = False) -> asyncio.Task[Any] | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.statusBar().showMessage("RedSight async event loop is not running")
            logger.error("Command Center operation requested without a running asyncio loop")
            return None

        task = loop.create_task(coro)
        if track_chat:
            self._chat_tasks.add(task)
            task.add_done_callback(self._chat_tasks.discard)
        return task

    def _on_chat_message(self, message: str):
        """Queue a chat request without blocking the Qt event loop."""
        self.statusBar().showMessage(f"Sending: {message[:50]}...")
        self._spawn(self._send_to_api(message), track_chat=True)

    async def _send_to_api(self, message: str):
        """Send chat to RedSight while offloading legacy memory-gateway calls."""
        chat_tab = self._tabs.widget(0)
        try:
            messages = await asyncio.to_thread(_redsight_stage10_messages, message)
            timeout = httpx.Timeout(30.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self._api_base_url}/api/v1/chat",
                    json={"messages": messages, "stream": False},
                )
                response.raise_for_status()
                data = response.json()

            await asyncio.to_thread(_redsight_stage10_commit, data)
            if isinstance(chat_tab, ChatWidget):
                chat_tab.add_assistant_message(extract_chat_response(data))
            self.statusBar().showMessage("Ready")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("RedSight chat request failed")
            if isinstance(chat_tab, ChatWidget):
                chat_tab.add_assistant_message(f"Error: {exc}")
            self.statusBar().showMessage("Chat request failed")

    def _update_dashboard(self):
        """Start one health refresh at a time; skip timer ticks while one is active."""
        if self._dashboard_task is not None and not self._dashboard_task.done():
            return
        task = self._spawn(self._update_dashboard_async())
        if task is not None:
            self._dashboard_task = task

    async def _update_dashboard_async(self):
        try:
            timeout = httpx.Timeout(5.0, connect=2.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{self._api_base_url}/api/v1/health")
                response.raise_for_status()
                health_data = response.json()

            health_tab = self._tabs.widget(1)
            if health_tab:
                for widget in health_tab.findChildren(HealthDashboardWidget):
                    widget.update_health(health_data)
            self.statusBar().showMessage("Ready")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Health refresh unavailable: %s", exc)
            self.statusBar().showMessage("Backend health unavailable")

    def closeEvent(self, event):  # noqa: N802 - Qt API name
        """Cancel in-flight async work before the underlying widgets are destroyed."""
        if hasattr(self, "_update_timer"):
            self._update_timer.stop()
        if self._dashboard_task is not None and not self._dashboard_task.done():
            self._dashboard_task.cancel()
        for task in tuple(self._chat_tasks):
            task.cancel()
        super().closeEvent(event)


# Compatibility name used by the launcher and package exports.
CommandCenterMainWindowStable = StableCommandCenterMainWindow
