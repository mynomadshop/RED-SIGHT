"""Restart an installed desktop and only the native services owned by that install."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil

from app.runtime_profile import instance_id


def owned_service(root: Path, port: int, service: str) -> psutil.Process | None:
    """Require health identity, PID, executable and command to agree before stopping."""
    if not 1 <= port <= 65535:
        return None
    route = "/api/v1/health" if service == "redsight" else "/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}{route}", timeout=2) as response:
            health = json.loads(response.read(16384))
        if health.get("service") != service or health.get("instance_id") != instance_id(root):
            return None
        process = psutil.Process(int(health["pid"]))
        executable = Path(process.exe()).resolve()
        environments = [root / ".venv-ui", root / ".venv-actions", root / "runtime/python"]
        if not any(executable.is_relative_to(path.resolve()) for path in environments):
            return None
        command = process.cmdline()
        marker = "app.server:app" if service == "redsight" else "redsight_actions.gateway_stage10:app"
        start_script = str((root / "scripts/start.py").resolve())
        if marker not in command and not (service == "redsight" and start_script in command):
            return None
        return process
    except (OSError, ValueError, KeyError, psutil.Error):
        return None


def request_restart(root: Path) -> None:
    root = root.resolve()
    launcher = root / "scripts/windows/Start-RedSight.ps1"
    if os.name != "nt" or not launcher.is_file():
        raise RuntimeError("A Windows installation is required for desktop restart")
    python = root / ".venv-ui/Scripts/python.exe"
    if not python.is_file():
        raise FileNotFoundError("Installed RedSight Python was not found")
    log_dir = Path(os.environ["LOCALAPPDATA"]) / "RedSight/logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    command = [str(python), "-m", "app.runtime_restart", "--root", str(root),
               "--wait-pid", str(os.getpid()), "--wait-created", str(psutil.Process().create_time())]
    with (log_dir / "restart.log").open("a", encoding="utf-8") as log:
        subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                         close_fds=True)


def restart(root: Path, wait_pid: int, wait_created: float, *, no_ui: bool = False) -> None:
    root = root.resolve()
    try:
        if wait_pid > 0:
            ui = psutil.Process(wait_pid)
            if abs(ui.create_time() - wait_created) < 0.01:
                ui.wait(timeout=30)
    except psutil.NoSuchProcess:
        pass
    # If the UI cannot close, leave the services alone and log a clear failure.
    state_path = Path(os.environ["LOCALAPPDATA"]) / "RedSight/settings/native-runtime.json"
    if os.environ.get("REDSIGHT_RUNTIME_MODE", "native") == "native":
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        if state and state.get("instance_id") != instance_id(root):
            raise RuntimeError("Runtime state belongs to a different installation")
        for key, service in [("gateway_port", "redsight-action-gateway"), ("backend_port", "redsight")]:
            process = owned_service(root, int(state.get(key, 0)), service)
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except psutil.TimeoutExpired:
                    # psutil verifies process identity before kill (PID reuse safe).
                    process.kill()
                    process.wait(timeout=10)
    else:
        # This only restarts the application's service; its persistent volumes
        # and the vector database container are retained.
        subprocess.run(["docker", "compose", "restart", "redsight"], cwd=root,
                       check=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
    powershell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    command = [str(powershell), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(root / "scripts/windows/Start-RedSight.ps1"), "-ProjectRoot", str(root)]
    if no_ui:
        command.append("-NoUi")
    environment = dict(os.environ)
    # A changed data root, endpoint or removed key must not survive through the
    # helper's inherited environment. The normal launcher reapplies saved state.
    from app.ui.action_palette_stage106 import PROVIDER_KEY_ENV

    for name in list(environment):
        if (name in PROVIDER_KEY_ENV.values() or name.startswith(("REDSIGHT_", "RED_SIGHT_", "LM_", "VECTOR_BACKEND_"))):
            environment.pop(name, None)
    child = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
    if no_ui and child.wait(timeout=330) != 0:
        raise RuntimeError("The restarted services did not become ready")
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} Restart launcher started", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--wait-created", type=float, required=True)
    parser.add_argument("--no-ui", action="store_true")
    args = parser.parse_args()
    restart(args.root, args.wait_pid, args.wait_created, no_ui=args.no_ui)


if __name__ == "__main__":
    main()
