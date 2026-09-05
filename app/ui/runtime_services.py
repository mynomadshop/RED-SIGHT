"""Small, testable runtime helpers for the RedSight desktop UI.

This module deliberately has no Qt imports so parsing and service probes can be
unit tested without a display server. Slow functions are intended to be called
with ``asyncio.to_thread`` by the qasync-powered desktop runtime.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import urllib.request
from typing import Any


def extract_chat_response(data: Any) -> str:
    """Normalize common local/cloud chat response shapes into display text."""
    if not isinstance(data, dict):
        return "No response"

    direct_message = data.get("message")
    if isinstance(direct_message, str) and direct_message.strip():
        return direct_message

    for key in ("response", "content"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value

    if isinstance(direct_message, dict):
        value = direct_message.get("content")
        if isinstance(value, str) and value.strip():
            return value

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                value = message.get("content")
                if isinstance(value, str) and value.strip():
                    return value
            value = first.get("text")
            if isinstance(value, str) and value.strip():
                return value

    return "No response"


def parse_nvidia_smi_csv(output: str) -> list[dict[str, float | str]]:
    """Parse the CSV emitted by the launcher's nvidia-smi query."""
    rows: list[dict[str, float | str]] = []
    reader = csv.reader(io.StringIO(output))

    def number(value: str, default: float = 0.0) -> float:
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return default

    for raw in reader:
        if len(raw) < 7:
            continue

        values = [value.strip() for value in raw]
        used = number(values[3])
        total = number(values[4])
        vram_percent = (used / total * 100.0) if total > 0 else 0.0

        rows.append(
            {
                "index": values[0],
                "name": values[1],
                "util": number(values[2]),
                "used": used,
                "total": total,
                "vram_percent": vram_percent,
                "temp": number(values[5]),
                "power": number(values[6]),
            }
        )

    return rows


def query_nvidia(timeout: float = 4.0) -> list[dict[str, float | str]]:
    """Return NVIDIA GPU telemetry without opening a console window on Windows."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=creationflags,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "nvidia-smi failed")
    return parse_nvidia_smi_csv(result.stdout)


def get_lm_model(timeout: float = 3.0) -> str:
    """Return the first LM Studio model id, or a concise offline status."""
    from app.config.settings import get_settings

    base_url = get_settings().lmstudio.base_url.rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/models",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        models = data.get("data", []) if isinstance(data, dict) else []
        if models and isinstance(models[0], dict):
            return str(models[0].get("id") or "available")
        return "server online / no model listed"
    except Exception as exc:  # Service availability is a UI status, not a crash.
        return f"OFFLINE: {exc}"
