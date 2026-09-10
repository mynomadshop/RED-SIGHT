"""Fast native startup sizing and collision-aware loopback service allocation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import tempfile
import urllib.request
from pathlib import Path


def instance_id(root: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()[:20]


def resource_budget(cpu_count: int, available_gb: float) -> dict:
    """Leave CPU and memory for Windows, the browser, and foreground apps."""
    cpus = max(1, cpu_count)
    memory_cap = 1 if available_gb < 4 else 2 if available_gb < 8 else 4
    threads = max(1, min(8, cpus // 2, memory_cap * 2))
    return {
        "cpu_threads": cpus,
        "available_memory_gb": round(available_gb, 2),
        "worker_threads": threads,
        "concurrent_jobs": max(1, min(memory_cap, cpus // 2)),
    }


def scan_resources() -> dict:
    # No GPU model load, network request, disk crawl, or WMI subprocess.
    cpus = os.cpu_count() or 1
    available_gb = 2.0
    try:
        import psutil

        available_gb = psutil.virtual_memory().available / 1024**3
        try:
            cpus = len(psutil.Process().cpu_affinity()) or cpus
        except (AttributeError, psutil.Error):
            pass
    except ImportError:
        pass
    return resource_budget(cpus, available_gb)


def service_matches(port: int, service: str, identity: str) -> bool:
    path = "/api/v1/health" if service == "redsight" else "/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=0.5) as response:
            data = json.loads(response.read(16384))
        return data.get("service") == service and data.get("instance_id") == identity
    except (OSError, ValueError, AttributeError):
        return False


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def select_port(preferred: int, service: str, identity: str, excluded: set[int]) -> int:
    if not 1 <= preferred <= 65535:
        raise ValueError("Service ports must be between 1 and 65535")
    if preferred not in excluded:
        if port_available(preferred) or service_matches(preferred, service, identity):
            return preferred
    # Probe a small deterministic range, then ask the OS for an ephemeral port.
    for port in range(preferred + 1, min(preferred + 33, 65536)):
        if port not in excluded and port_available(port):
            return port
    for _ in range(10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port not in excluded:
            return port
    raise RuntimeError("No loopback service port is available")


def build_profile(root: Path, state_path: Path, backend_port: int = 0, gateway_port: int = 0) -> dict:
    identity = instance_id(root)
    try:
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or saved.get("instance_id") != identity:
            saved = {}
    except (OSError, ValueError):
        saved = {}
    def saved_port(name: str, default: int) -> int:
        try:
            port = int(saved.get(name, default))
            return port if 1 <= port <= 65535 else default
        except (ValueError, TypeError):
            return default

    api_port = select_port(backend_port or saved_port("backend_port", 8000), "redsight", identity, set())
    action_port = select_port(gateway_port or saved_port("gateway_port", 8765), "redsight-action-gateway", identity, {api_port})
    budget = scan_resources()
    api = f"http://127.0.0.1:{api_port}"
    gateway = f"http://127.0.0.1:{action_port}"
    environment = {
        "REDSIGHT_API_URL": api,
        "REDSIGHT_API_BASE_URL": api,
        "API_BASE_URL": api,
        "REDSIGHT_GATEWAY_URL": gateway,
        "REDSIGHT_GATEWAY_PORT": str(action_port),
        "REDSIGHT_INSTANCE_ID": identity,
        "REDSIGHT_RUNTIME_MODE": "native",
        "VECTOR_BACKEND_EMBEDDED": "true",
        "OMP_NUM_THREADS": str(budget["worker_threads"]),
        "MKL_NUM_THREADS": str(budget["worker_threads"]),
        "OPENBLAS_NUM_THREADS": str(budget["worker_threads"]),
        "TOKENIZERS_PARALLELISM": "false",
        "RED_SIGHT_ROUTING__MAX_CONCURRENT_JOBS": str(budget["concurrent_jobs"]),
        "REDSIGHT_AGENT_CONCURRENCY": str(budget["concurrent_jobs"]),
    }
    return {"version": 1, "instance_id": identity, "backend_port": api_port,
            "gateway_port": action_port, "resources": budget, "environment": environment}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--backend-port", type=int, default=0)
    parser.add_argument("--gateway-port", type=int, default=0)
    args = parser.parse_args()
    state = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "RedSight/settings/native-runtime.json"
    profile = build_profile(args.root, state, args.backend_port, args.gateway_port)
    state.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=state.parent, delete=False) as handle:
        json.dump(profile, handle, indent=2)
        temporary = handle.name
    os.replace(temporary, state)
    print(json.dumps(profile))


if __name__ == "__main__":
    main()
