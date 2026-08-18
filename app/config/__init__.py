"""
RedSight - High-Performance Local AI Intelligence Platform
Configuration module

Exports settings and capability registry.
"""

from app.config.settings import Settings, get_settings, reset_settings
from app.config.capability_registry import CapabilityRegistry

__all__ = ["Settings", "get_settings", "reset_settings", "CapabilityRegistry"]
