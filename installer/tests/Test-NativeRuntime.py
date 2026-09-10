"""Windows CI: boot the installed laptop stack and perform dependent actions.

Only the remote model is replaced with a loopback HTTP fixture. The installed
launcher, DPAPI settings, backend, gateway, memory, and file tools are real.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import httpx
    import psutil
    import redsight_bootstrap as bootstrap

    from app.security.local_api import auth_headers
    from app.ui.action_palette_stage106 import provider_defaults, save_provider_config

    settings = Path(os.environ["LOCALAPPDATA"]) / "RedSight/settings"
    paths = [settings / name for name in ("provider.json", "provider-secrets.json", "native-runtime.json")]
    backups = {path: path.read_bytes() if path.exists() else None for path in paths}
    sockets, owned_pids = [], set()
    fixture = None
    try:
        # Start genuinely unconfigured, then plug in a provider while services run.
        save_provider_config(provider_defaults())
        paths[-1].unlink(missing_ok=True)
        for port in (8000, 8765):
            blocker = socket.socket()
            try:
                blocker.bind(("127.0.0.1", port))
                blocker.listen()
                sockets.append(blocker)
            except OSError:
                blocker.close()  # An existing listener already tests the collision.

        launch = ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                  "-File", str(root / "START-REDSIGHT-NATIVE.ps1"), "-NoUi"]
        subprocess.run(launch, cwd=root, check=True, timeout=330)
        profile = json.loads(paths[-1].read_text())
        assert profile["backend_port"] not in {8000, 8765}
        assert profile["gateway_port"] not in {8000, 8765, profile["backend_port"]}
        headers = auth_headers()
        api = profile["environment"]["REDSIGHT_API_BASE_URL"]
        gateway = profile["environment"]["REDSIGHT_GATEWAY_URL"]

        with httpx.Client(headers=headers, trust_env=False, timeout=90) as client:
            for endpoint in (api + "/api/v1/health", gateway + "/health"):
                response = client.get(endpoint)
                response.raise_for_status()
                health = response.json()
                assert health["instance_id"] == profile["instance_id"]
                owned_pids.add(int(health["pid"]))
            response = client.post(api + "/api/v1/chat", json={"messages": [{"role": "user", "content": "hello"}]})
            assert response.status_code == 503, response.text
            client.get(gateway + "/memory/status").raise_for_status()
            client.get(gateway + "/tools").raise_for_status()

            demo = Path(tempfile.mkdtemp(prefix="agent-smoke-", dir=root / "outputs"))
            source, destination = demo / "input.txt", demo / "copied.txt"
            source.write_text("verified laptop agent payload", encoding="utf-8")
            calls = []

            class ProviderFixture(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    calls.append(payload)
                    latest = payload["messages"][-1]
                    if "local action planner" in payload["messages"][0]["content"]:
                        tool, params = "filesystem__search", {"root": str(demo), "pattern": "input.txt"}
                    elif latest["role"] == "user":
                        assert str(source).replace("\\", "\\\\") in latest["content"]
                        tool, params = "filesystem__read", {"path": str(source)}
                    elif latest.get("name") == "filesystem__read":
                        assert "verified laptop agent payload" in latest["content"]
                        tool, params = "filesystem__write", {"path": str(destination), "content": source.read_text()}
                    else:
                        tool, params = None, None
                    message = {"content": "Copied the verified file."}
                    if tool:
                        message = {"content": None, "tool_calls": [{"id": f"call_{len(calls)}", "type": "function",
                                    "function": {"name": tool, "arguments": json.dumps(params)}}]}
                    body = json.dumps({"choices": [{"message": message}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            fixture = ThreadingHTTPServer(("127.0.0.1", 0), ProviderFixture)
            threading.Thread(target=fixture.serve_forever, daemon=True).start()
            config = provider_defaults()
            config["active_provider"] = "custom"
            config["models"]["custom"] = "fixture-agent"
            config["base_urls"]["custom"] = f"http://127.0.0.1:{fixture.server_port}/v1"
            save_provider_config(config, api_key="ci-test-key-not-a-real-credential")

            goal = f"Find input.txt in {demo}, read it, and copy its contents to copied.txt."
            response = client.post(gateway + "/agent/plan", json={"goal": goal})
            response.raise_for_status()
            plan = response.json()
            assert plan["steps"][0]["tool"] == "filesystem.search", plan
            response = client.post(gateway + "/agent/execute", json={"goal": goal, "plan": plan["steps"], "approved": False})
            response.raise_for_status()
            pending = response.json()
            assert pending.get("requires_approval") and not destination.exists(), pending
            assert len(pending["results"]) == 2, pending
            response = client.post(gateway + "/agent/execute", json={
                "goal": goal, "plan": pending["plan"], "run_id": pending["run_id"], "approved": True,
            })
            response.raise_for_status()
            result = response.json()
            assert result["ok"] and len(result["results"]) == 3, result
            assert destination.read_text() == source.read_text()
            assert len(calls) == 4, len(calls)

            # A second launcher must reuse this installation's running services.
            subprocess.run(launch, cwd=root, check=True, timeout=60)
            again = json.loads(paths[-1].read_text())
            assert (again["backend_port"], again["gateway_port"]) == (profile["backend_port"], profile["gateway_port"])
            assert client.get(api + "/api/v1/health").json()["pid"] in owned_pids
        print("NATIVE_LAPTOP_SMOKE=PASS (occupied ports, live settings, memory, real dependent file actions, no replay)")
    finally:
        # Terminate only services started by this CI test, verified by identity.
        for pid in owned_pids:
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=10)
            except (psutil.Error, OSError):
                pass
        if fixture:
            fixture.shutdown()
            fixture.server_close()
        for blocker in sockets:
            blocker.close()
        for path, contents in backups.items():
            if contents is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(contents)


if __name__ == "__main__":
    main()
