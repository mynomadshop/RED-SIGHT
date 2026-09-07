#!/usr/bin/env python3
# ruff: noqa: E402
"""Headless smoke test for the installed Command Center Settings surface."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The Windows runner has no interactive desktop. Qt's offscreen platform still
# constructs real widgets and actions, which is exactly what this test needs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")

# CI keeps this test in its checkout instead of shipping all build-time tests
# in the installer. REDSIGHT_TEST_ROOT points it at the installed payload;
# direct invocations default to the repository containing this file.
ROOT = Path(os.environ.get("REDSIGHT_TEST_ROOT") or Path(__file__).resolve().parents[2])
ROOT = ROOT.resolve()
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QToolBar

from app.ui import action_palette_stage106 as settings_ui
from app.ui import action_palette_stage114_mcp as mcp_ui
from app.ui import action_palette_stage115_lmstudio as lmstudio_ui
from app.ui.stable_command_center import StableCommandCenterMainWindow


def main() -> int:
    app = QApplication.instance() or QApplication([])
    report = settings_ui.install()
    mcp_ui.install()
    lmstudio_ui.install()

    assert report["provider"] == "none", report
    assert not settings_ui.PROVIDER_CONFIG.exists()
    assert not settings_ui.RUNTIME_CONFIG.exists()

    window = StableCommandCenterMainWindow()
    window.show()
    for _ in range(4):
        app.processEvents()

    action = window.findChild(QAction, "RedSightSettingsAction")
    assert action is not None, "the top Settings action was not attached"
    assert "Settings" in action.text()
    assert action.shortcut().toString() == "Ctrl+,"

    toolbar = getattr(window, "_redsight_settings_toolbar", None)
    assert isinstance(toolbar, QToolBar)
    assert window.toolBarArea(toolbar) == Qt.ToolBarArea.TopToolBarArea

    dialog = settings_ui.AdvancedSettingsDialog(window)
    labels = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
    expected = {"AI Provider", "Runtime", "MCP Servers", "LM Studio", "Diagnostics"}
    assert expected.issubset(labels), f"missing Settings tabs: {sorted(expected - set(labels))}"
    assert dialog.provider_tab.provider_combo.currentData() == "none"

    dialog.close()
    window.close()
    app.processEvents()
    print("SETTINGS_UI_SMOKE=PASS")
    print("SETTINGS_TABS=" + ",".join(labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
