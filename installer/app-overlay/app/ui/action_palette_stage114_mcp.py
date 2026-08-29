"""RedSight Stage 11.4 - MCP server setup from the Settings dialog.

Adds an "MCP Servers" tab to the Stage 10.6 Advanced Settings dialog so servers
can be registered by pasting a path, with no hand-editing of JSON.

What a pasted path may be:

  * a .json / .yaml / .yml config file holding server definitions, in either
    RedSight's flat ``{name: {...}}`` form or the common ``mcpServers`` /
    ``mcp_servers`` wrapper;
  * a folder containing such files (each is read and merged);
  * an executable or script (``.exe``, ``.cmd``, ``.bat``, ``.py``, ``.js``),
    which is registered as a stdio server;
  * an http(s):// URL, registered as a remote server.

Definitions are written to the file the native MCP layer actually reads:

    %LOCALAPPDATA%\\RedSight\\private\\mcp-native.json

which is what ``redsight_actions/mcp_native_stage111.load_server_definitions``
treats as the explicit opt-in that activates ``mcp.call`` and
``mcp.native.test``.

Additive by design: installed by monkey-patching the dialog, so nothing in the
existing Stage 10.6 module changes.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
PRIVATE_DIR = LOCALAPPDATA / "RedSight" / "private"
# Must match redsight_actions/mcp_native_stage111.PRIVATE_CONFIG.
MCP_CONFIG = PRIVATE_DIR / "mcp-native.json"

_CONFIG_SUFFIXES = {".json", ".yaml", ".yml"}
_COMMAND_SUFFIXES = {".exe", ".cmd", ".bat", ".ps1", ".py", ".js", ".mjs", ".sh", ""}
_SERVER_FIELDS = ("command", "url", "transport")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def load_servers() -> dict[str, dict[str, Any]]:
    """Read the native MCP config, tolerating a missing or malformed file."""
    try:
        if not MCP_CONFIG.exists():
            return {}
        raw = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return _server_map(raw)


def save_servers(servers: dict[str, dict[str, Any]]) -> Path:
    """Write the config atomically so a crash cannot truncate it."""
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "mcp_servers": servers}
    temp = MCP_CONFIG.with_name(MCP_CONFIG.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, MCP_CONFIG)
    return MCP_CONFIG


def _server_map(raw: Any) -> dict[str, dict[str, Any]]:
    """Extract ``{name: definition}`` from any of the accepted shapes."""
    if not isinstance(raw, dict):
        return {}

    # Unwrap the common container keys before looking for definitions.
    for key in ("mcp_servers", "mcpServers", "servers"):
        inner = raw.get(key)
        if isinstance(inner, dict):
            raw = inner
            break

    result: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if isinstance(value, dict) and any(field in value for field in _SERVER_FIELDS):
            result[str(name)] = value
    return result


def _load_definition_file(path: Path) -> dict[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return _server_map(json.loads(text))
    try:
        import yaml  # optional; only needed for YAML configs
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            f"{path.name} is YAML, but PyYAML is not installed in this environment."
        ) from exc
    return _server_map(yaml.safe_load(text))


# ---------------------------------------------------------------------------
# Path interpretation
# ---------------------------------------------------------------------------


def definitions_from_path(raw_path: str) -> dict[str, dict[str, Any]]:
    """Turn a pasted path or URL into server definitions.

    Raises ValueError with a message meant to be shown to the user.
    """
    text = (raw_path or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("Paste a path to an MCP config file, a folder of them, "
                         "an MCP server executable, or an http(s) URL.")

    if text.lower().startswith(("http://", "https://")):
        name = _name_from_url(text)
        return {name: {"transport": "http", "url": text}}

    path = Path(os.path.expandvars(text)).expanduser()
    if not path.exists():
        raise ValueError(f"Path not found:\n{path}")

    if path.is_dir():
        found: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for child in sorted(path.iterdir()):
            if child.is_file() and child.suffix.lower() in _CONFIG_SUFFIXES:
                try:
                    found.update(_load_definition_file(child))
                except Exception as exc:
                    errors.append(f"{child.name}: {exc}")
        if not found:
            detail = ("\n" + "\n".join(errors)) if errors else ""
            raise ValueError(
                f"No MCP server definitions found in:\n{path}\n\n"
                f"Expected a .json, .yaml or .yml file containing server entries.{detail}"
            )
        return found

    suffix = path.suffix.lower()
    if suffix in _CONFIG_SUFFIXES:
        found = _load_definition_file(path)
        if not found:
            raise ValueError(
                f"{path.name} contains no MCP server definitions.\n\n"
                "Each entry needs a 'command' or a 'url'."
            )
        return found

    if suffix in _COMMAND_SUFFIXES:
        return {path.stem or "mcp-server": _stdio_definition(path)}

    raise ValueError(
        f"Not recognised as an MCP server: {path.name}\n\n"
        "Provide a .json/.yaml config, a folder containing one, "
        "an executable or script, or an http(s) URL."
    )


def _stdio_definition(path: Path) -> dict[str, Any]:
    """Build a stdio server entry, routing scripts through their interpreter."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        # sys.executable would be the UI's interpreter; prefer an explicit python
        # on PATH so the server does not inherit the UI environment.
        return {"transport": "stdio", "command": shutil.which("python") or "python",
                "args": [str(path)], "cwd": str(path.parent)}
    if suffix in {".js", ".mjs"}:
        return {"transport": "stdio", "command": shutil.which("node") or "node",
                "args": [str(path)], "cwd": str(path.parent)}
    if suffix == ".ps1":
        return {"transport": "stdio", "command": "powershell.exe",
                "args": ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
                "cwd": str(path.parent)}
    return {"transport": "stdio", "command": str(path), "args": [], "cwd": str(path.parent)}


def _name_from_url(url: str) -> str:
    trimmed = url.split("//", 1)[-1]
    host = trimmed.split("/", 1)[0]
    return (host.replace(":", "-") or "mcp-server").lower()


def describe(definition: dict[str, Any]) -> str:
    """One-line summary for the list widget."""
    url = str(definition.get("url") or "").strip()
    if url:
        return f"http  ->  {url}"
    command = str(definition.get("command") or "").strip()
    args = definition.get("args") or []
    if args:
        return f"stdio ->  {command} {' '.join(str(a) for a in args)}"
    return f"stdio ->  {command}"


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------


class McpServersTab(QWidget):
    def __init__(self, dialog: Any) -> None:
        super().__init__()
        self._dialog = dialog
        self._servers: dict[str, dict[str, Any]] = load_servers()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("MCP servers")
        font = QFont("Segoe UI", 12)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        blurb = QLabel(
            "Paste the path to an MCP config file, a folder containing config files, "
            "an MCP server executable or script, or an http(s) URL. Registered servers "
            "become available to the agent as mcp.call and mcp.native.test."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color:#AAB4BF;")
        layout.addWidget(blurb)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.path_edit = QLineEdit()
        self.path_edit.setClearButtonEnabled(True)
        self.path_edit.setPlaceholderText(r"D:\tools\my-mcp-server\config.json")
        form.addRow("Path or URL", self.path_edit)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.browse_file_button = QPushButton("Browse file...")
        self.browse_folder_button = QPushButton("Browse folder...")
        self.add_button = QPushButton("Add")
        self.add_button.setObjectName("PrimaryButton")
        buttons.addWidget(self.browse_file_button)
        buttons.addWidget(self.browse_folder_button)
        buttons.addWidget(self.add_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.server_list = QListWidget()
        self.server_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.server_list, 1)

        actions = QHBoxLayout()
        self.remove_button = QPushButton("Remove selected")
        self.open_button = QPushButton("Open config folder")
        actions.addWidget(self.remove_button)
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#9FAAB6;")
        layout.addWidget(self.status)

        self.browse_file_button.clicked.connect(self._browse_file)
        self.browse_folder_button.clicked.connect(self._browse_folder)
        self.add_button.clicked.connect(self._add)
        self.remove_button.clicked.connect(self._remove)
        self.open_button.clicked.connect(self._open_folder)
        self.path_edit.returnPressed.connect(self._add)

        self._refresh()

    # -- helpers ----------------------------------------------------------

    def _refresh(self) -> None:
        self.server_list.clear()
        for name in sorted(self._servers):
            item = QListWidgetItem(f"{name}    {describe(self._servers[name])}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.server_list.addItem(item)
        count = len(self._servers)
        if count:
            self.status.setText(f"{count} server(s) configured in {MCP_CONFIG}")
        else:
            self.status.setText("No MCP servers configured yet.")

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select an MCP config file or server executable", "",
            "MCP configs and servers (*.json *.yaml *.yml *.exe *.cmd *.bat *.ps1 *.py *.js);;All files (*.*)",
        )
        if path:
            self.path_edit.setText(path)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select a folder containing MCP config files")
        if path:
            self.path_edit.setText(path)

    def _add(self) -> None:
        try:
            found = definitions_from_path(self.path_edit.text())
        except Exception as exc:
            QMessageBox.warning(self, "MCP server", str(exc))
            return

        overwritten = sorted(set(found) & set(self._servers))
        if overwritten:
            reply = QMessageBox.question(
                self, "MCP server",
                "Replace the existing definition(s) for:\n\n  " + "\n  ".join(overwritten),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._servers.update(found)
        self.path_edit.clear()
        self._refresh()
        self.status.setText(
            f"Added {len(found)} server(s): {', '.join(sorted(found))}. "
            "Choose Save & Apply to write the configuration."
        )

    def _remove(self) -> None:
        item = self.server_list.currentItem()
        if item is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        self._servers.pop(name, None)
        self._refresh()
        self.status.setText(f"Removed {name}. Choose Save & Apply to write the configuration.")

    def _open_folder(self) -> None:
        PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(PRIVATE_DIR))  # noqa: S606 - Windows shell open
        except Exception as exc:
            QMessageBox.information(self, "MCP server", f"Config folder:\n{PRIVATE_DIR}\n\n{exc}")

    # -- called by the dialog's Save & Apply -------------------------------

    def apply(self) -> None:
        path = save_servers(self._servers)
        self.status.setText(f"Saved {len(self._servers)} server(s) to {path}")


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def _add_tab(dialog: Any) -> None:
    tab = McpServersTab(dialog)
    dialog._rs114_mcp_tab = tab
    # Sit before Diagnostics, which is conventionally last.
    index = max(dialog.tabs.count() - 1, 0)
    dialog.tabs.insertTab(index, tab, "MCP Servers")


def install() -> bool:
    """Add the MCP tab to the Advanced Settings dialog. Idempotent."""
    from app.ui import action_palette_stage106 as s106

    cls = s106.AdvancedSettingsDialog
    if getattr(cls, "_rs114_installed", False):
        return False

    original_init = cls.__init__
    original_apply = getattr(cls, "_apply", None)

    def patched_init(self, window, *args, **kwargs):  # type: ignore[no-untyped-def]
        original_init(self, window, *args, **kwargs)
        try:
            _add_tab(self)
        except Exception:
            # The rest of Settings must keep working even if this tab fails.
            import traceback

            traceback.print_exc()

    def patched_apply(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        tab = getattr(self, "_rs114_mcp_tab", None)
        if tab is not None:
            try:
                tab.apply()
            except Exception:
                import traceback

                traceback.print_exc()
        if original_apply is not None:
            return original_apply(self, *args, **kwargs)
        return None

    cls.__init__ = patched_init
    if original_apply is not None:
        cls._apply = patched_apply
    cls._rs114_installed = True
    return True
