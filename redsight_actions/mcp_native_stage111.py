"""Bounded native MCP client used by the RED-SIGHT action gateway.

Servers are opt-in and can only be loaded from the private settings file.  The
gateway exposes tool listing/testing as read operations and places actual tool
calls behind its normal approval gate.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx


_LOCAL_APP_DATA = Path(
    os.environ.get("LOCALAPPDATA")
    or os.environ.get("XDG_STATE_HOME")
    or (Path.home() / ".local" / "state")
)
PRIVATE_CONFIG = _LOCAL_APP_DATA / "RedSight" / "private" / "mcp-native.json"

_PROTOCOL_VERSION = "2025-06-18"
_MAX_CONFIG_BYTES = 1_000_000
_MAX_MESSAGE_BYTES = 2_000_000
_MAX_ARGUMENT_BYTES = 500_000
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ENV_REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


class McpError(RuntimeError):
    """An MCP server or protocol error safe to report to the local user."""


def _server_map(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    for key in ("mcp_servers", "mcpServers", "servers"):
        if isinstance(raw.get(key), dict):
            raw = raw[key]
            break
    return {
        str(name): dict(value)
        for name, value in raw.items()
        if isinstance(value, dict)
    }


def load_server_definitions(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load explicitly configured MCP servers without returning any secrets."""
    config_path = path or PRIVATE_CONFIG
    try:
        if not config_path.is_file() or config_path.stat().st_size > _MAX_CONFIG_BYTES:
            return {}
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}

    definitions: dict[str, dict[str, Any]] = {}
    for name, value in _server_map(raw).items():
        if not _NAME_PATTERN.fullmatch(name):
            continue
        try:
            definitions[name] = _validate_definition(value)
        except ValueError:
            continue
    return definitions


def sanitized_server_definitions(path: Path | None = None) -> list[dict[str, Any]]:
    result = []
    for name, definition in load_server_definitions(path).items():
        if definition["transport"] == "stdio":
            result.append(
                {
                    "name": name,
                    "transport": "stdio",
                    "command": definition["command"],
                    "argument_count": len(definition["args"]),
                }
            )
        else:
            parsed = urlsplit(definition["url"])
            result.append(
                {
                    "name": name,
                    "transport": "http",
                    "endpoint": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                }
            )
    return result


def _validate_definition(value: dict[str, Any]) -> dict[str, Any]:
    transport = str(value.get("transport") or ("http" if value.get("url") else "stdio"))
    transport = transport.strip().lower()
    timeout = max(1.0, min(float(value.get("timeout", 60)), 300.0))

    if transport in {"http", "streamable-http", "streamable_http", "sse"}:
        url = str(value.get("url") or "").strip()
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MCP HTTP URL must use http:// or https://")
        if parsed.username or parsed.password or len(url) > 4_096:
            raise ValueError("MCP HTTP URL is invalid")
        headers = _string_mapping(value.get("headers"), max_items=50)
        return {
            "transport": "http",
            "url": url,
            "headers": headers,
            "timeout": timeout,
        }

    if transport != "stdio":
        raise ValueError("Unsupported MCP transport")
    command = str(value.get("command") or "").strip()
    if not command or len(command) > 4_096 or "\x00" in command:
        raise ValueError("MCP stdio command is invalid")
    raw_args = value.get("args") or []
    if not isinstance(raw_args, list) or len(raw_args) > 64:
        raise ValueError("MCP stdio args must be a bounded list")
    args = [str(item) for item in raw_args]
    if any(len(item) > 4_096 or "\x00" in item for item in args):
        raise ValueError("MCP stdio argument is invalid")
    cwd = str(value.get("cwd") or "").strip()
    if cwd and (len(cwd) > 4_096 or not Path(cwd).expanduser().is_dir()):
        raise ValueError("MCP stdio working directory does not exist")
    return {
        "transport": "stdio",
        "command": command,
        "args": args,
        "cwd": cwd,
        "env": _string_mapping(value.get("env"), max_items=100),
        "timeout": timeout,
    }


def _string_mapping(value: Any, *, max_items: int) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > max_items:
        raise ValueError("MCP configuration mapping is invalid")
    result: dict[str, str] = {}
    for key, item in value.items():
        name = str(key).strip()
        text = str(item)
        if not name or len(name) > 256 or len(text) > 16_384:
            raise ValueError("MCP configuration value is invalid")
        if "\r" in name or "\n" in name or "\r" in text or "\n" in text:
            raise ValueError("MCP configuration values cannot contain newlines")
        result[name] = text
    return result


def _resolved_value(value: str) -> str:
    match = _ENV_REFERENCE.fullmatch(value)
    return os.environ.get(match.group(1), "") if match else value


def _stdio_environment(configured: dict[str, str]) -> dict[str, str]:
    allowed = {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LANG",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    env = {name: value for name, value in os.environ.items() if name.upper() in allowed}
    env.update({name: _resolved_value(value) for name, value in configured.items()})
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _stdio_argv(definition: dict[str, Any]) -> list[str]:
    command = definition["command"]
    resolved = command if Path(command).is_file() else shutil.which(command)
    if not resolved:
        raise McpError(f"Configured MCP executable was not found: {command}")
    argv = [resolved, *definition["args"]]
    if os.name == "nt" and Path(resolved).suffix.lower() in {".bat", ".cmd"}:
        command_processor = os.environ.get("COMSPEC", "cmd.exe")
        return [command_processor, "/d", "/s", "/c", subprocess.list2cmdline(argv)]
    return argv


async def _read_stdio_response(
    process: asyncio.subprocess.Process,
    request_id: int,
    timeout: float,
) -> dict[str, Any]:
    if process.stdout is None:
        raise McpError("MCP server stdout is unavailable")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise McpError("MCP server response timed out")
        line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
        if not line:
            raise McpError("MCP server exited before replying")
        if len(line) > _MAX_MESSAGE_BYTES:
            raise McpError("MCP server response exceeded the size limit")
        try:
            message = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return message


async def _write_stdio(process: asyncio.subprocess.Process, payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise McpError("MCP server stdin is unavailable")
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_MESSAGE_BYTES:
        raise McpError("MCP request exceeded the size limit")
    process.stdin.write(encoded + b"\n")
    await process.stdin.drain()


async def _drain_stderr(process: asyncio.subprocess.Process) -> None:
    if process.stderr is None:
        return
    consumed = 0
    while consumed < _MAX_MESSAGE_BYTES:
        chunk = await process.stderr.read(min(65_536, _MAX_MESSAGE_BYTES - consumed))
        if not chunk:
            break
        consumed += len(chunk)


def _rpc_result(message: dict[str, Any]) -> Any:
    if isinstance(message.get("error"), dict):
        error = message["error"]
        raise McpError(str(error.get("message") or "MCP server returned an error")[:2_000])
    if "result" not in message:
        raise McpError("MCP server returned no result")
    return message["result"]


def _initialize_request(request_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "RED-SIGHT", "version": "11.6.0"},
        },
    }


async def _stdio_request(
    definition: dict[str, Any],
    method: str,
    params: dict[str, Any],
) -> Any:
    process = await asyncio.create_subprocess_exec(
        *_stdio_argv(definition),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=definition["cwd"] or None,
        env=_stdio_environment(definition["env"]),
        limit=_MAX_MESSAGE_BYTES,
    )
    stderr_task = asyncio.create_task(_drain_stderr(process))
    try:
        await _write_stdio(process, _initialize_request(1))
        _rpc_result(await _read_stdio_response(process, 1, definition["timeout"]))
        await _write_stdio(
            process,
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        await _write_stdio(
            process,
            {"jsonrpc": "2.0", "id": 2, "method": method, "params": params},
        )
        return _rpc_result(await _read_stdio_response(process, 2, definition["timeout"]))
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        await stderr_task


def _http_messages(response: httpx.Response) -> list[dict[str, Any]]:
    if response.status_code == 202 or not response.content:
        return []
    if len(response.content) > _MAX_MESSAGE_BYTES:
        raise McpError("MCP server response exceeded the size limit")
    content_type = response.headers.get("content-type", "").lower()
    candidates: list[Any] = []
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                try:
                    candidates.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    continue
    else:
        try:
            value = response.json()
            candidates.extend(value if isinstance(value, list) else [value])
        except json.JSONDecodeError as exc:
            raise McpError("MCP server returned invalid JSON") from exc
    return [item for item in candidates if isinstance(item, dict)]


async def _http_request(
    definition: dict[str, Any],
    method: str,
    params: dict[str, Any],
) -> Any:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        **{name: _resolved_value(value) for name, value in definition["headers"].items()},
    }
    timeout = httpx.Timeout(definition["timeout"], connect=min(10.0, definition["timeout"]))
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        initialize = await client.post(definition["url"], headers=headers, json=_initialize_request(1))
        initialize.raise_for_status()
        messages = _http_messages(initialize)
        matching = next((item for item in messages if item.get("id") == 1), None)
        if matching is None:
            raise McpError("MCP HTTP server returned no initialize result")
        _rpc_result(matching)
        session_id = initialize.headers.get("mcp-session-id")
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        initialized = await client.post(
            definition["url"],
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        initialized.raise_for_status()
        response = await client.post(
            definition["url"],
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": method, "params": params},
        )
        response.raise_for_status()
        matching = next((item for item in _http_messages(response) if item.get("id") == 2), None)
        if matching is None:
            raise McpError("MCP HTTP server returned no tool result")
        return _rpc_result(matching)


async def request(
    server_name: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    config_path: Path | None = None,
) -> Any:
    if method not in {"tools/list", "tools/call"}:
        raise ValueError("Only MCP tool listing and calling are supported")
    definitions = load_server_definitions(config_path)
    definition = definitions.get(str(server_name).strip())
    if definition is None:
        raise ValueError(f"Configured MCP server was not found: {server_name}")
    arguments = params or {}
    encoded = json.dumps(arguments, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) > _MAX_ARGUMENT_BYTES:
        raise ValueError("MCP arguments exceeded the size limit")
    if definition["transport"] == "stdio":
        return await _stdio_request(definition, method, arguments)
    return await _http_request(definition, method, arguments)


async def test_server(server_name: str, *, config_path: Path | None = None) -> dict[str, Any]:
    result = await request(server_name, "tools/list", {}, config_path=config_path)
    tools = result.get("tools", []) if isinstance(result, dict) else []
    summaries = [
        {
            "name": str(item.get("name", ""))[:128],
            "description": str(item.get("description", ""))[:500],
        }
        for item in tools[:500]
        if isinstance(item, dict)
    ]
    return {"ok": True, "server": server_name, "tool_count": len(tools), "tools": summaries}


async def call_tool(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    tool = str(tool_name).strip()
    if not _NAME_PATTERN.fullmatch(tool):
        raise ValueError("A valid MCP tool name is required")
    result = await request(
        server_name,
        "tools/call",
        {"name": tool, "arguments": arguments or {}},
        config_path=config_path,
    )
    return {"ok": True, "server": server_name, "tool": tool, "result": result}
