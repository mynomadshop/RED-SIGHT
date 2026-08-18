"""
RedSight - High-Performance Local AI Intelligence Platform
Plugin System Module

Exports plugin classes and utilities.
"""

from app.plugins.plugin_system import (
    PluginManager,
    PluginEventBus,
    PluginEvent,
    BasePlugin,
    PluginManifest,
    PluginInfo,
    PluginState,
    PluginType,
    get_plugin_manager,
    get_event_bus,
    initialize_plugin_system,
    shutdown_plugin_system,
)

__all__ = [
    "PluginManager",
    "PluginEventBus",
    "PluginEvent",
    "BasePlugin",
    "PluginManifest",
    "PluginInfo",
    "PluginState",
    "PluginType",
    "get_plugin_manager",
    "get_event_bus",
    "initialize_plugin_system",
    "shutdown_plugin_system",
]
