"""
RedSight UI package.

The canonical live desktop implementation is:

    app.ui.command_center.CommandCenterMainWindow

Keep this package initializer side-effect free so importing an app.ui
submodule cannot be broken by stale optional exports.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = [
    "CommandCenterMainWindow",
    "CommandCenter",
]


def __getattr__(name: str) -> Any:
    """
    Lazy compatibility exports.

    CommandCenterMainWindow is the canonical RedSight desktop class.
    CommandCenter remains as a compatibility alias.
    """

    if name in {
        "CommandCenterMainWindow",
        "CommandCenter",
    }:
        module = import_module(
            ".command_center",
            __name__,
        )

        return getattr(
            module,
            "CommandCenterMainWindow",
        )

    if name == "CommandCenterState":
        module = import_module(
            ".command_center",
            __name__,
        )

        if hasattr(
            module,
            "CommandCenterState",
        ):
            return getattr(
                module,
                "CommandCenterState",
            )

        raise AttributeError(
            "CommandCenterState is not defined by the current "
            "RedSight Command Center implementation."
        )

    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )


def __dir__() -> list[str]:
    return sorted(
        set(globals()) |
        set(__all__)
    )