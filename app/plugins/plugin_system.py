"""
RedSight - High-Performance Local AI Intelligence Platform
Plugin System

Provides an extensible plugin architecture for adding capabilities:
- Plugin discovery and loading
- Plugin lifecycle management
- Plugin event system
- Plugin API for registering tools, skills, and hooks
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class PluginState(str, Enum):
    """Plugin lifecycle states."""
    INSTALLED = "installed"
    LOADING = "loading"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"


class PluginType(str, Enum):
    """Plugin types."""
    TOOL = "tool"  # Adds new tools
    SKILL = "skill"  # Adds new skills
    HOOK = "hook"  # Hooks into system events
    PROVIDER = "provider"  # Adds new model providers
    UI = "ui"  # Adds UI components
    STORAGE = "storage"  # Adds custom storage backends


@dataclass
class PluginManifest:
    """Plugin manifest (metadata)."""
    name: str
    version: str
    description: str
    plugin_type: PluginType
    author: str = ""
    license: str = ""
    entry_point: str = ""  # Module path to Plugin class
    requirements: List[str] = field(default_factory=list)
    hooks: Dict[str, List[str]] = field(default_factory=dict)  # event -> handler methods
    tools: List[str] = field(default_factory=list)  # tool names this plugin provides
    skills: List[str] = field(default_factory=list)  # skill names this plugin provides
    min_platform_version: str = "1.0.0"
    max_platform_version: str = "99.99.99"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        """Create manifest from dict."""
        return cls(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            plugin_type=PluginType(data.get("plugin_type", "tool")),
            author=data.get("author", ""),
            license=data.get("license", ""),
            entry_point=data.get("entry_point", ""),
            requirements=data.get("requirements", []),
            hooks=data.get("hooks", {}),
            tools=data.get("tools", []),
            skills=data.get("skills", []),
            min_platform_version=data.get("min_platform_version", "1.0.0"),
            max_platform_version=data.get("max_platform_version", "99.99.99"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "plugin_type": self.plugin_type.value,
            "author": self.author,
            "license": self.license,
            "entry_point": self.entry_point,
            "requirements": self.requirements,
            "hooks": self.hooks,
            "tools": self.tools,
            "skills": self.skills,
            "min_platform_version": self.min_platform_version,
            "max_platform_version": self.max_platform_version,
        }


@dataclass
class PluginInfo:
    """Runtime plugin info."""
    manifest: PluginManifest
    state: PluginState = PluginState.INSTALLED
    error_message: Optional[str] = None
    loaded_at: Optional[float] = None
    plugin_instance: Optional[Any] = None


class BasePlugin(ABC):
    """Base class for all plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin version."""
        pass

    @abstractmethod
    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialize the plugin. Return True on success."""
        pass

    @abstractmethod
    async def shutdown(self):
        """Shutdown the plugin."""
        pass

    async def on_event(self, event_type: str, data: Dict[str, Any]) -> Any:
        """Handle a system event. Override to add custom behavior."""
        pass

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tools provided by this plugin (optional)."""
        return []

    def get_skills(self) -> List[Dict[str, Any]]:
        """Return skills provided by this plugin (optional)."""
        return []


class PluginManager:
    """Manages plugin discovery, loading, and lifecycle."""

    def __init__(self, plugin_dir: Optional[str] = None):
        self._plugins: Dict[str, PluginInfo] = {}
        self._hooks: Dict[str, List[Callable]] = {}
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._plugin_dir = Path(plugin_dir) if plugin_dir else Path("plugins")
        self._plugin_dir.mkdir(parents=True, exist_ok=True)
        self._loaded_plugins_file = self._plugin_dir / "loaded_plugins.json"

    async def discover_plugins(self) -> List[PluginManifest]:
        """Discover plugins in the plugin directory."""
        manifests = []
        if not self._plugin_dir.exists():
            return manifests

        for plugin_path in self._plugin_dir.iterdir():
            if not plugin_path.is_dir():
                continue
            manifest_path = plugin_path / "plugin.json"
            if not manifest_path.exists():
                continue
            try:
                with open(manifest_path, "r") as f:
                    data = json.load(f)
                manifest = PluginManifest.from_dict(data)
                manifests.append(manifest)
                logger.info(f"Discovered plugin: {manifest.name} v{manifest.version}")
            except Exception as e:
                logger.error(f"Failed to load plugin manifest from {plugin_path}: {e}")

        return manifests

    async def load_plugin(self, manifest: PluginManifest) -> bool:
        """Load and activate a plugin."""
        plugin_info = PluginInfo(manifest=manifest, state=PluginState.LOADING)

        try:
            # Check requirements
            for req in manifest.requirements:
                if not await self._check_requirement(req):
                    plugin_info.state = PluginState.ERROR
                    plugin_info.error_message = f"Missing requirement: {req}"
                    self._plugins[manifest.name] = plugin_info
                    return False

            # Import the plugin module
            if manifest.entry_point:
                module = await self._import_module(manifest.entry_point)
                if module is None:
                    plugin_info.state = PluginState.ERROR
                    plugin_info.error_message = f"Failed to import module: {manifest.entry_point}"
                    self._plugins[manifest.name] = plugin_info
                    return False

                # Find and instantiate the plugin class
                plugin_class = getattr(module, "Plugin", None)
                if plugin_class is None:
                    plugin_info.state = PluginState.ERROR
                    plugin_info.error_message = "Plugin class not found (expected 'Plugin')"
                    self._plugins[manifest.name] = plugin_info
                    return False

                plugin_instance = plugin_class()
                plugin_info.plugin_instance = plugin_instance

                # Initialize the plugin
                context = {
                    "plugin_dir": str(self._plugin_dir),
                    "manager": self,
                }
                success = await plugin_instance.initialize(context)
                if not success:
                    plugin_info.state = PluginState.ERROR
                    plugin_info.error_message = "Plugin initialization failed"
                    self._plugins[manifest.name] = plugin_info
                    return False

                plugin_info.state = PluginState.ACTIVE
                plugin_info.loaded_at = time.time()

                # Register hooks
                await self._register_hooks(manifest, plugin_instance)

                # Register tools and skills
                tools = plugin_instance.get_tools()
                skills = plugin_instance.get_skills()
                for tool in tools:
                    self._hooks.setdefault("tool:" + tool.get("name", ""), []).append(tool)
                for skill in skills:
                    self._hooks.setdefault("skill:" + skill.get("name", ""), []).append(skill)

            self._plugins[manifest.name] = plugin_info
            logger.info(f"Plugin loaded: {manifest.name} v{manifest.version}")
            return True

        except Exception as e:
            plugin_info.state = PluginState.ERROR
            plugin_info.error_message = str(e)
            self._plugins[manifest.name] = plugin_info
            logger.error(f"Failed to load plugin {manifest.name}: {e}")
            return False

    async def unload_plugin(self, plugin_name: str) -> bool:
        """Unload and deactivate a plugin."""
        plugin_info = self._plugins.get(plugin_name)
        if not plugin_info:
            return False

        try:
            if plugin_info.plugin_instance:
                await plugin_info.plugin_instance.shutdown()

            plugin_info.state = PluginState.UNINSTALLED
            logger.info(f"Plugin unloaded: {plugin_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to unload plugin {plugin_name}: {e}")
            return False

    async def emit_event(self, event_type: str, data: Dict[str, Any]) -> List[Any]:
        """Emit an event to all registered handlers."""
        results = []

        # Call plugin event handlers
        for plugin_info in self._plugins.values():
            if plugin_info.state != PluginState.ACTIVE:
                continue
            if plugin_info.plugin_instance:
                try:
                    result = await plugin_info.plugin_instance.on_event(event_type, data)
                    if result is not None:
                        results.append(result)
                except Exception as e:
                    logger.error(f"Plugin event handler error in {plugin_info.manifest.name}: {e}")

        # Call direct hook handlers
        for handler in self._event_handlers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(data)
                else:
                    result = handler(data)
                results.append(result)
            except Exception as e:
                logger.error(f"Hook handler error for {event_type}: {e}")

        return results

    def on(self, event_type: str, handler: Callable):
        """Register a direct event handler (not plugin-based)."""
        self._event_handlers.setdefault(event_type, []).append(handler)

    def get_active_plugins(self) -> List[PluginInfo]:
        """Get all active plugins."""
        return [
            p for p in self._plugins.values()
            if p.state == PluginState.ACTIVE
        ]

    def get_plugin_info(self, plugin_name: str) -> Optional[PluginInfo]:
        """Get info for a specific plugin."""
        return self._plugins.get(plugin_name)

    def get_all_plugins(self) -> List[PluginInfo]:
        """Get all plugins."""
        return list(self._plugins.values())

    async def get_plugin_status(self) -> Dict[str, Any]:
        """Get status of all plugins."""
        return {
            name: {
                "state": info.state.value,
                "version": info.manifest.version,
                "error": info.error_message,
                "loaded_at": info.loaded_at,
            }
            for name, info in self._plugins.items()
        }

    async def _check_requirement(self, requirement: str) -> bool:
        """Check if a requirement is satisfied."""
        # Simple check: try to import the module
        module_name = requirement.split(">=")[0].split("==")[0].split("<")[0].strip()
        try:
            importlib.import_module(module_name)
            return True
        except ImportError:
            return False

    async def _import_module(self, entry_point: str) -> Optional[Any]:
        """Import a module by entry point path."""
        try:
            module = importlib.import_module(entry_point)
            return module
        except Exception as e:
            logger.error(f"Failed to import module {entry_point}: {e}")
            return None

    async def _register_hooks(self, manifest: PluginManifest, plugin_instance: BasePlugin):
        """Register plugin hooks."""
        for event_type, handlers in manifest.hooks.items():
            for handler_name in handlers:
                handler = getattr(plugin_instance, handler_name, None)
                if handler and callable(handler):
                    self._event_handlers.setdefault(event_type, []).append(handler)


# ─── Plugin Event System ─────────────────────────────────────────────

class PluginEvent:
    """Represents a plugin event."""

    def __init__(self, event_type: str, data: Dict[str, Any], source: Optional[str] = None):
        self.event_type = event_type
        self.data = data
        self.source = source
        self.timestamp = time.time()
        self.handled = False
        self.result: Optional[Any] = None


class PluginEventBus:
    """Event bus for plugin communication."""

    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = {}
        self._history: List[PluginEvent] = []
        self._max_history = 1000

    def subscribe(self, event_type: str, listener: Callable):
        """Subscribe to an event type."""
        self._listeners.setdefault(event_type, []).append(listener)

    def unsubscribe(self, event_type: str, listener: Callable):
        """Unsubscribe from an event type."""
        if event_type in self._listeners:
            self._listeners[event_type].remove(listener)

    async def publish(self, event: PluginEvent) -> PluginEvent:
        """Publish an event to all subscribers."""
        # Add to history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Call listeners
        for listener in self._listeners.get(event.event_type, []):
            try:
                if asyncio.iscoroutinefunction(listener):
                    result = await listener(event)
                else:
                    result = listener(event)
                if result is not None:
                    event.result = result
                    event.handled = True
            except Exception as e:
                logger.error(f"Event listener error for {event.event_type}: {e}")

        return event

    def get_history(
        self,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[PluginEvent]:
        """Get event history."""
        if event_type:
            history = [e for e in self._history if e.event_type == event_type]
        else:
            history = self._history
        return history[-limit:]

    def clear_history(self):
        """Clear event history."""
        self._history.clear()


# ─── Global Plugin Manager ───────────────────────────────────────────

plugin_manager: Optional[PluginManager] = None
event_bus: Optional[PluginEventBus] = None


def get_plugin_manager() -> PluginManager:
    """Get the global plugin manager instance."""
    global plugin_manager
    if plugin_manager is None:
        plugin_manager = PluginManager()
    return plugin_manager


def get_event_bus() -> PluginEventBus:
    """Get the global event bus instance."""
    global event_bus
    if event_bus is None:
        event_bus = PluginEventBus()
    return event_bus


async def initialize_plugin_system(plugin_dir: Optional[str] = None):
    """Initialize the plugin system."""
    global plugin_manager, event_bus
    plugin_manager = PluginManager(plugin_dir=plugin_dir)
    event_bus = PluginEventBus()
    logger.info("Plugin system initialized")
    return plugin_manager


async def shutdown_plugin_system():
    """Shutdown the plugin system."""
    global plugin_manager, event_bus
    if plugin_manager:
        for plugin in list(plugin_manager.get_all_plugins()):
            await plugin_manager.unload_plugin(plugin.manifest.name)
        plugin_manager = None
        event_bus = None
        logger.info("Plugin system shut down")
