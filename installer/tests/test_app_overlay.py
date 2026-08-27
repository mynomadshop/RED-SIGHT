#!/usr/bin/env python3
"""Tests for the RedSight application overlay.

Exercises the pure logic of the MCP settings tab - how a pasted path is turned
into server definitions, and how those definitions are read back from the file
the native MCP layer actually loads.

PySide6 is stubbed so this runs anywhere, including the Linux CI leg: the widget
code is not under test here, the path interpretation is.

    python3 installer/tests/test_app_overlay.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

OVERLAY = Path(__file__).resolve().parents[1] / "app-overlay"


def _stub_pyside6() -> None:
    """Install a minimal PySide6 stand-in so the module imports headlessly."""
    names = {
        "PySide6.QtCore": ["Qt"],
        "PySide6.QtGui": ["QFont"],
        "PySide6.QtWidgets": [
            "QAbstractItemView", "QFileDialog", "QFormLayout", "QHBoxLayout",
            "QLabel", "QLineEdit", "QListWidget", "QListWidgetItem",
            "QMessageBox", "QPushButton", "QVBoxLayout", "QWidget",
        ],
    }
    root = types.ModuleType("PySide6")
    sys.modules["PySide6"] = root
    for mod_name, attrs in names.items():
        mod = types.ModuleType(mod_name)
        for attr in attrs:
            # A plain class is enough: nothing here is instantiated.
            setattr(mod, attr, type(attr, (), {}))
        sys.modules[mod_name] = mod
        setattr(root, mod_name.split(".")[-1], mod)


def _load_module():
    _stub_pyside6()
    sys.path.insert(0, str(OVERLAY))
    import importlib

    return importlib.import_module("app.ui.action_palette_stage114_mcp")


PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")
        print(f"  FAIL  {name} {detail}")


def expect_error(name: str, fn, *args) -> None:
    try:
        fn(*args)
    except Exception:
        check(name, True)
        return
    check(name, False, "(no error raised)")


def main() -> int:
    mcp = _load_module()

    print("\n== _server_map: accepted config shapes ==")
    flat = {"demo": {"url": "http://localhost:40404/mcp"}}
    check("flat {name: {...}} form", mcp._server_map(flat) == flat)
    check(
        "mcpServers wrapper (Claude/Hermes style)",
        mcp._server_map({"mcpServers": flat}) == flat,
    )
    check("mcp_servers wrapper", mcp._server_map({"mcp_servers": flat}) == flat)
    check("servers wrapper", mcp._server_map({"servers": flat}) == flat)
    check(
        "stdio entries with command are kept",
        mcp._server_map({"a": {"command": "node", "args": ["x.js"]}}) != {},
    )
    check("entries with no command/url/transport are dropped", mcp._server_map({"a": {"note": "hi"}}) == {})
    check("non-dict input is ignored", mcp._server_map(["nope"]) == {})
    check("empty input is ignored", mcp._server_map({}) == {})

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        print("\n== definitions_from_path ==")

        url = mcp.definitions_from_path("https://mcp.example.com/sse")
        check("an https URL becomes a remote server", list(url.values())[0]["url"] == "https://mcp.example.com/sse")
        check("URL server is named from the host", "mcp.example.com" in list(url)[0])

        cfg = root / "servers.json"
        cfg.write_text(json.dumps({"mcpServers": {"files": {"command": "npx", "args": ["-y", "server"]}}}))
        from_file = mcp.definitions_from_path(str(cfg))
        check("a .json config file is read", "files" in from_file)
        check("its command survives", from_file["files"]["command"] == "npx")

        # A folder of definitions, plus files that must be ignored.
        folder = root / "configs"
        folder.mkdir()
        (folder / "one.json").write_text(json.dumps({"alpha": {"url": "http://a/mcp"}}))
        (folder / "two.json").write_text(json.dumps({"mcp_servers": {"beta": {"command": "beta.exe"}}}))
        (folder / "notes.md").write_text("ignore me")
        (folder / "unrelated.json").write_text(json.dumps({"nothing": "useful"}))
        from_dir = mcp.definitions_from_path(str(folder))
        check("a folder merges every config in it", set(from_dir) == {"alpha", "beta"}, f"(got {sorted(from_dir)})")

        exe = root / "my-mcp-server.exe"
        exe.write_text("stub")
        from_exe = mcp.definitions_from_path(str(exe))
        check("an executable becomes a stdio server", from_exe["my-mcp-server"]["transport"] == "stdio")
        check("the executable is the command", from_exe["my-mcp-server"]["command"] == str(exe))
        check("cwd defaults to its folder", from_exe["my-mcp-server"]["cwd"] == str(root))

        script = root / "server.py"
        script.write_text("print('hi')")
        from_py = mcp.definitions_from_path(str(script))
        check("a .py server runs through python", "python" in from_py["server"]["command"].lower())
        check("and passes the script as an argument", from_py["server"]["args"] == [str(script)])

        js = root / "index.js"
        js.write_text("//")
        from_js = mcp.definitions_from_path(str(js))
        check("a .js server runs through node", "node" in from_js["index"]["command"].lower())

        # Quoted paths are what actually lands on the clipboard from Explorer.
        quoted = mcp.definitions_from_path(f'"{exe}"')
        check("a quoted pasted path is accepted", "my-mcp-server" in quoted)
        check("surrounding whitespace is tolerated", "my-mcp-server" in mcp.definitions_from_path(f"  {exe}  "))

        print("\n== definitions_from_path: rejections ==")
        expect_error("empty input is rejected", mcp.definitions_from_path, "")
        expect_error("a missing path is rejected", mcp.definitions_from_path, str(root / "nope.json"))
        expect_error("an unrelated extension is rejected", mcp.definitions_from_path, str(folder / "notes.md"))
        expect_error("a json with no definitions is rejected", mcp.definitions_from_path, str(folder / "unrelated.json"))
        empty_dir = root / "empty"
        empty_dir.mkdir()
        expect_error("a folder with no definitions is rejected", mcp.definitions_from_path, str(empty_dir))

        print("\n== save_servers / load_servers ==")
        # Point the module at a temp config rather than the real LOCALAPPDATA.
        mcp.PRIVATE_DIR = root / "private"
        mcp.MCP_CONFIG = mcp.PRIVATE_DIR / "mcp-native.json"

        check("no config yet reads as empty", mcp.load_servers() == {})

        servers = {"alpha": {"url": "http://a/mcp"}, "beta": {"command": "beta.exe", "args": []}}
        written = mcp.save_servers(servers)
        check("save writes the config file", written.exists())

        raw = json.loads(written.read_text())
        check(
            "written in the shape the native MCP layer reads",
            "mcp_servers" in raw and set(raw["mcp_servers"]) == {"alpha", "beta"},
        )
        check("round-trips through load_servers", mcp.load_servers() == servers)
        check("no temp file is left behind", not (mcp.PRIVATE_DIR / "mcp-native.json.tmp").exists())

        mcp.MCP_CONFIG.write_text("{ this is not json")
        check("a corrupt config degrades to empty rather than raising", mcp.load_servers() == {})

        print("\n== describe ==")
        check("http servers summarised by URL", "http://a/mcp" in mcp.describe({"url": "http://a/mcp"}))
        check("stdio servers summarised by command", "beta.exe" in mcp.describe({"command": "beta.exe"}))
        check(
            "arguments are included",
            "-y server" in mcp.describe({"command": "npx", "args": ["-y", "server"]}),
        )

    print("\n" + "=" * 60)
    print(f"  {PASS} passed, {FAIL} failed")
    print("=" * 60)
    if FAIL:
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
