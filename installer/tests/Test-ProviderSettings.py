"""Windows: drive real Settings controls, HTTP adapters, DPAPI, and restart action."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    root = Path(os.environ["REDSIGHT_TEST_ROOT"]).resolve()
    sys.path.insert(0, str(root))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="redsight-settings-test-")
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

    from app.ui import action_palette_stage106 as ui

    requests = []
    warnings = []

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, body, status=200):
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            self.reply({"data": [{"id": "fixture-model"}]})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            if self.path.startswith("/reject/"):
                self.reply({"error": "Invalid test key"}, 401)
            elif self.path.endswith("/messages"):
                blocks = [{"type": "text", "text": "READY"}]
                if payload.get("tool_choice", {}).get("type") == "any":
                    blocks = [{"type": "tool_use", "id": "p1", "name": "redsight_probe", "input": {"value": "READY"}}]
                self.reply({"content": blocks})
            elif ":generateContent" in self.path:
                parts = [{"text": "READY"}]
                if payload.get("toolConfig", {}).get("functionCallingConfig", {}).get("mode") == "ANY":
                    parts = [{"functionCall": {"name": "redsight_probe", "args": {"value": "READY"}}, "thoughtSignature": "signed"}]
                self.reply({"candidates": [{"content": {"parts": parts}}]})
            else:
                message = {"content": "READY"}
                if payload.get("tool_choice") == "required":
                    message = {"tool_calls": [{"id": "p1", "type": "function", "function": {
                        "name": "redsight_probe", "arguments": '{"value":"READY"}'}}]}
                self.reply({"choices": [{"message": message}]})

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    application = QApplication.instance() or QApplication([])
    QMessageBox.warning = lambda *args: warnings.append(args[-1])
    QMessageBox.information = lambda *args: None
    window = QWidget()
    dialog = ui.AdvancedSettingsDialog(window)
    tab = dialog.provider_tab
    endpoint = f"http://127.0.0.1:{fixture.server_port}/v1"

    def finish_probe():
        deadline = time.monotonic() + 15
        while tab._worker is not None and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert tab._worker is None, "The Settings test thread did not finish"
        assert tab.provider_combo.isEnabled(), "Controls did not re-enable"

    try:
        for slug in ui.PROVIDER_KEY_ENV:
            tab.provider_combo.setCurrentIndex(tab.provider_combo.findData(slug))
            tab.model_edit.setCurrentText("fixture-model")
            tab.custom_url_edit.setText(endpoint)
            tab.key_edit.setText("fixture-secret-for-" + slug)
            tab.test_button.click()
            assert not tab.test_button.isEnabled(), "Probe did not start asynchronously"
            dialog.reject()
            assert tab._worker is not None, "Closing Settings destroyed a running probe"
            finish_probe()
            assert "round trip passed" in tab.status.text(), (slug, tab.status.text(), warnings)
            tab.apply()
            assert ui.load_provider_config()["active_provider"] == slug
            assert ui.configured_secret(slug) == "fixture-secret-for-" + slug
            assert b"fixture-secret" not in ui.PROVIDER_SECRETS.read_bytes()
        assert len(requests) == 2 * len(ui.PROVIDER_KEY_ENV), len(requests)
        assert not warnings, warnings

        tab.custom_url_edit.setText(endpoint.replace("/v1", "/reject/v1"))
        tab.test_button.click()
        finish_probe()
        assert "401" in tab.status.text() and warnings
        assert ui.load_provider_config()["base_urls"]["custom"] == endpoint, "Failed draft test changed saved settings"
        tab.custom_url_edit.setText(endpoint)

        # Test the actual button dispatch and all save hooks; real process
        # replacement is exercised separately by Test-NativeRuntime.py.
        import app.runtime_restart as restart

        launched = []
        restart.request_restart = lambda project: launched.append(project)
        tab.model_edit.setCurrentText("applied-model")
        dialog.restart_button.click()
        application.processEvents()
        assert launched == [root]
        assert ui.load_provider_config()["models"]["custom"] == "applied-model"
        assert ui.configured_secret("custom") == "fixture-secret-for-custom"
        print(f"PROVIDER_SETTINGS_SMOKE=PASS ({len(ui.PROVIDER_KEY_ENV)} providers; real HTTP, DPAPI, failure state, apply/restart)")
    finally:
        dialog.close()
        window.close()
        fixture.shutdown()
        fixture.server_close()


if __name__ == "__main__":
    main()
