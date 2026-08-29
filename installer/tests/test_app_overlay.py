#!/usr/bin/env python3
"""Tests for the RedSight application overlay.

Covers three things:

  * the MCP settings tab - how a pasted path is turned into server definitions,
    and how those definitions are read back from the file the native MCP layer
    actually loads;
  * the Stage 11.5 runtime configuration module, which is what puts the LM
    Studio endpoint into the environment the backend reads;
  * the Stage 11.5 UI fixes - endpoint redirection, cached nvidia-smi and LM
    Studio probes, and the visual-effects budget.

PySide6 is stubbed so this runs anywhere, including the Linux CI leg: the widget
code is not under test here, the logic behind it is.

    python3 installer/tests/test_app_overlay.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path

OVERLAY = Path(__file__).resolve().parents[1] / "app-overlay"


def _stub_pyside6() -> None:
    """Install a minimal PySide6 stand-in so the module imports headlessly."""
    names = {
        "PySide6.QtCore": ["Qt", "QThread"],
        "PySide6.QtGui": ["QFont"],
        "PySide6.QtWidgets": [
            "QAbstractItemView", "QComboBox", "QFileDialog", "QFormLayout",
            "QHBoxLayout", "QLabel", "QLineEdit", "QListWidget",
            "QListWidgetItem", "QMessageBox", "QPushButton", "QSpinBox",
            "QVBoxLayout", "QWidget",
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
    # Signal is evaluated in a class body, so it has to accept its argument
    # types and hand back something that can live as a class attribute.
    sys.modules["PySide6.QtCore"].Signal = lambda *a, **k: None


def _load_module(name: str = "app.ui.action_palette_stage114_mcp"):
    _stub_pyside6()
    if str(OVERLAY) not in sys.path:
        sys.path.insert(0, str(OVERLAY))
    import importlib

    return importlib.import_module(name)


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



def _stage115_runtime_checks() -> None:
    """redsight_bootstrap: the file the launcher and the backend both read."""
    import importlib

    if str(OVERLAY) not in sys.path:
        sys.path.insert(0, str(OVERLAY))

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LOCALAPPDATA"] = tmp
        for key in list(os.environ):
            if key.startswith(("LM_STUDIO", "LM_BASE_URL", "RED_SIGHT_", "VECTOR_BACKEND", "REDSIGHT_UI_")):
                del os.environ[key]
        sys.modules.pop("redsight_bootstrap", None)
        rb = importlib.import_module("redsight_bootstrap")

        print("\n== Stage 11.5: normalize_base_url ==")
        check("bare host:port gains a scheme and /v1", rb.normalize_base_url("127.0.0.1:1234") == "http://127.0.0.1:1234/v1")
        check("an existing /v1 is kept once", rb.normalize_base_url("http://h:1/v1") == "http://h:1/v1")
        check("a /models tail is trimmed", rb.normalize_base_url("http://h:1/v1/models") == "http://h:1/v1")
        check(
            "a /chat/completions tail is trimmed",
            rb.normalize_base_url("http://h:1/v1/chat/completions") == "http://h:1/v1",
        )
        check("surrounding whitespace is ignored", rb.normalize_base_url("  http://h:1/  ") == "http://h:1/v1")
        check("https is preserved", rb.normalize_base_url("https://h/v1") == "https://h/v1")
        check("an empty value stays empty", rb.normalize_base_url("") == "")

        print("\n== Stage 11.5: stored configuration ==")
        check("defaults are used when no file exists", rb.load_config()["base_url"] == rb.DEFAULT_BASE_URL)
        path = rb.save_config({"base_url": "lan-box:1234", "model": "qwen/q3", "runtime_mode": "native"})
        raw = Path(path).read_bytes()
        check("written without a byte order mark", not raw.startswith(b"\xef\xbb\xbf"), "(pydantic and json.load both reject one)")
        check("no temp file is left behind", not Path(str(path) + ".tmp").exists())
        stored = rb.load_config()
        check("the endpoint is normalised on the way in", stored["base_url"] == "http://lan-box:1234/v1")
        check("the model round-trips", stored["model"] == "qwen/q3")
        check("unset keys keep their defaults", stored["timeout_seconds"] == 180)
        check("an unknown effects level falls back to reduced", stored["ui_effects"] == "reduced")

        rb.save_config({"ui_effects": "off"})
        check("a known effects level is kept", rb.load_config()["ui_effects"] == "off")
        check("saving one key preserves the others", rb.load_config()["model"] == "qwen/q3")

        Path(path).write_text("{ not json", encoding="utf-8")
        check("a corrupt file degrades to defaults rather than raising", rb.load_config()["base_url"] == rb.DEFAULT_BASE_URL)
        Path(path).write_text("\ufeff" + json.dumps({"base_url": "http://bom:1234/v1"}), encoding="utf-8")
        check("a file with a byte order mark is still readable", rb.load_config()["base_url"] == "http://bom:1234/v1")

        print("\n== Stage 11.5: exported environment ==")
        rb.save_config({"base_url": "http://lan:1234/v1", "model": "m1", "runtime_mode": "native", "data_root": r"C:\rs\data"})
        env = rb.environment()
        check("LM_STUDIO_BASE_URL is exported", env["LM_STUDIO_BASE_URL"] == "http://lan:1234/v1", "(the only name the backend validator reads)")
        check("the historical LM_BASE_URL is exported", env["LM_BASE_URL"] == "http://lan:1234/v1")
        check("LM_STUDIO_URL drops the version segment", env["LM_STUDIO_URL"] == "http://lan:1234")
        check("the pydantic-native name is exported too", env["RED_SIGHT_LMSTUDIO__BASE_URL"] == "http://lan:1234/v1")
        check("the model is exported under both names", env["LM_STUDIO_MODEL"] == "m1" and env["RED_SIGHT_LMSTUDIO__MODEL_ID"] == "m1")
        check("the data root is exported with the nested delimiter", env["RED_SIGHT_PLATFORM__DATA_ROOT"] == r"C:\rs\data")
        check("native mode asks for the embedded vector store", env["VECTOR_BACKEND_EMBEDDED"] == "true")
        check("native mode stops the container hostname being used", env["VECTOR_BACKEND_HOST"] == "127.0.0.1")

        rb.save_config({"runtime_mode": "container", "model": ""})
        env = rb.environment()
        check("container mode leaves the vector backend alone", "VECTOR_BACKEND_EMBEDDED" not in env)
        check("no model means no model variable", "LM_STUDIO_MODEL" not in env)

        print("\n== Stage 11.5: applying the environment ==")
        os.environ["LM_STUDIO_BASE_URL"] = "http://explicit/v1"
        rb.apply_environment()
        check("an existing variable is not overwritten", os.environ["LM_STUDIO_BASE_URL"] == "http://explicit/v1", "(a launcher override must win)")
        rb.apply_environment(override=True)
        check("override=True does replace it", os.environ["LM_STUDIO_BASE_URL"] == "http://lan:1234/v1")


def _stage115_ui_checks() -> None:
    """The Stage 11.5 UI fixes: redirection, caching and the effects budget."""
    import importlib

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LOCALAPPDATA"] = tmp
        os.environ.pop("REDSIGHT_UI_EFFECTS", None)
        sys.modules.pop("redsight_bootstrap", None)
        rb = importlib.import_module("redsight_bootstrap")
        sys.modules.pop("app.ui.action_palette_stage115_lmstudio", None)
        ui = _load_module("app.ui.action_palette_stage115_lmstudio")

        print("\n== Stage 11.5: endpoint redirection ==")
        rb.save_config({"base_url": "http://127.0.0.1:1234/v1"})
        ui._state.pop("effective_origin", None)
        check(
            "nothing is redirected while the endpoint is the default",
            ui.effective_url("http://127.0.0.1:1234/v1/models") == "http://127.0.0.1:1234/v1/models",
        )

        rb.save_config({"base_url": "http://192.168.50.139:1234/v1"})
        ui._state.pop("effective_origin", None)
        check(
            "a hardcoded probe follows the configured endpoint",
            ui.effective_url("http://127.0.0.1:1234/v1/models") == "http://192.168.50.139:1234/v1/models",
            "(this is why Settings could pass while the UI showed offline)",
        )
        check(
            "the backend is never redirected",
            ui.effective_url("http://127.0.0.1:8000/api/v1/health") == "http://127.0.0.1:8000/api/v1/health",
        )
        check(
            "the actions gateway is never redirected",
            ui.effective_url("http://127.0.0.1:8765/memory/status") == "http://127.0.0.1:8765/memory/status",
        )
        check("Qdrant is never redirected", ui.effective_url("http://127.0.0.1:6333/readyz") == "http://127.0.0.1:6333/readyz")
        check("configured_origin has no path", ui.configured_origin() == "http://192.168.50.139:1234")

        print("\n== Stage 11.5: only the LM Studio model list is cached ==")
        check("the default origin's model list is ours", ui.is_lm_models_url("http://127.0.0.1:1234/v1/models"))
        check("the configured origin's model list is ours", ui.is_lm_models_url("http://192.168.50.139:1234/v1/models"))
        check(
            "another service exposing /models is left alone",
            not ui.is_lm_models_url("http://127.0.0.1:8000/api/v1/models"),
            "(caching someone else's endpoint would be a surprise)",
        )
        check("a non-models LM Studio URL is not cached", not ui.is_lm_models_url("http://127.0.0.1:1234/v1/chat/completions"))

        print("\n== Stage 11.5: nvidia-smi is recognised, everything else passes through ==")
        telemetry = ["nvidia-smi", "--query-gpu=index,name", "--format=csv"]
        check("the telemetry query is recognised", ui._is_nvidia_telemetry(telemetry))
        check("a full path is recognised", ui._is_nvidia_telemetry([r"C:\Windows\System32\nvidia-smi.exe", "--query-gpu=index"]))
        check("nvidia-smi without the query flag is left alone", not ui._is_nvidia_telemetry(["nvidia-smi", "-L"]))
        check("another program is left alone", not ui._is_nvidia_telemetry(["docker", "--query-gpu=x"]))
        check("a shell string is left alone", not ui._is_nvidia_telemetry("nvidia-smi --query-gpu=index"))
        check("an empty argv is left alone", not ui._is_nvidia_telemetry([]))

        print("\n== Stage 11.5: nvidia-smi runs once, not once per second ==")
        calls = {"n": 0}

        class _Result:
            returncode = 0
            stdout = "0, GPU, 10, 1, 2, 30, 40\n"
            stderr = ""

        def fake_run(argv, **kwargs):
            calls["n"] += 1
            return _Result()

        ui._original_subprocess_run = fake_run
        sampler = ui._NvidiaSampler(interval=60.0)
        first = sampler.sample(telemetry)
        second = sampler.sample(telemetry)
        third = sampler.sample(telemetry)
        check("the first GUI-thread read runs the process", calls["n"] == 1)
        check("later reads are served from the sample", calls["n"] == 1, f"(ran {calls['n']} times)")
        check("the same result is handed back", first is second is third)

        print("\n== Stage 11.5: the LM Studio probe is cached and non-blocking ==")
        fetches = {"n": 0}
        body = json.dumps({"data": [{"id": "qwen/q3"}]}).encode()

        probe = ui._ModelsProbe(interval=60.0)
        probe._fetch = lambda url, timeout: (fetches.__setitem__("n", fetches["n"] + 1), body)[1]
        response = probe.open("http://h/v1/models", 3.0)
        with response as handle:
            parsed = json.load(handle)
        check("the cold read returns a usable response", parsed["data"][0]["id"] == "qwen/q3")
        check("it is readable through the context manager", fetches["n"] == 1)
        probe.open("http://h/v1/models", 3.0).close()
        probe.open("http://h/v1/models", 3.0).close()
        check("later reads do not touch the network", fetches["n"] == 1, f"(fetched {fetches['n']} times)")

        failing = ui._ModelsProbe(interval=60.0)

        def boom(url, timeout):
            raise OSError("connection refused")

        failing._fetch = boom
        expect_error("an unreachable endpoint still raises for the caller", failing.open, "http://h/v1/models", 3.0)

        print("\n== Stage 11.5: the visual-effects budget ==")
        rb.save_config({"ui_effects": "full"})
        os.environ.pop("REDSIGHT_UI_EFFECTS", None)
        check("the stored level is used", ui.effect_level() == "full")
        os.environ["REDSIGHT_UI_EFFECTS"] = "off"
        check("the environment overrides the stored level", ui.effect_level() == "off")
        os.environ["REDSIGHT_UI_EFFECTS"] = "nonsense"
        rb.save_config({"ui_effects": "reduced"})
        check("an unknown level falls back to reduced", ui.effect_level() == "reduced")

        class _Timer:
            def __init__(self):
                self.interval = 50
                self.stopped = False

            def setInterval(self, value):
                self.interval = value

            def stop(self):
                self.stopped = True

        class _Widget:
            def __init__(self):
                self.timer = _Timer()
                self.hidden = False

            def hide(self):
                self.hidden = True

        widget = _Widget()
        ui._retime(widget, 200)
        check("a positive budget re-times the animation", widget.timer.interval == 200)
        widget = _Widget()
        ui._retime(widget, 0)
        check("a zero budget stops the timer", widget.timer.stopped)
        check("a zero budget hides the ambient layer", widget.hidden, "(a translucent full-window repaint is the costly one)")
        ui._retime(object(), 100)
        check("a widget with no timer is left alone", True)

        check("full leaves the shipped cadence in place", ui.install_effect_budget("full")["patched"] == [])


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

    _stage115_runtime_checks()
    _stage115_ui_checks()

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
