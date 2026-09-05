"""
RedSight - High-Performance Local AI Intelligence Platform
Built-in Tools

Real, working tool implementations that the agent can call.
Each tool has a JSON Schema contract, permission checks, and audit logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.interfaces import AuditAction, AuditEvent
from app.security.permissions import DEFAULT_FILE_DENY_PATTERNS, _path_is_allowed
from app.tools.contract import ToolContract

logger = logging.getLogger(__name__)


def _is_discoverable_path(path: Path) -> bool:
    """Keep default secret paths out of recursive tool results."""
    return _path_is_allowed(str(path), [], list(DEFAULT_FILE_DENY_PATTERNS))


class ToolRegistry:
    """
    Tool Registry - Manages tool contracts and real execution.

    Provides typed tool interface with permission checks,
    sandbox execution, and audit logging.
    """

    def __init__(self, policy=None, audit_logger=None):
        self._tools: Dict[str, ToolContract] = {}
        self._handlers: Dict[str, callable] = {}
        self._policy = policy
        self._audit = audit_logger

    def register(self, contract: ToolContract, handler: callable = None) -> str:
        """Register a tool with its execution handler."""
        self._tools[contract.name] = contract
        if handler:
            self._handlers[contract.name] = handler
        logger.info(f"Tool registered: {contract.name}")
        return contract.name

    async def unregister(self, tool_name: str) -> bool:
        """Unregister a tool."""
        if tool_name not in self._tools:
            return False
        del self._tools[tool_name]
        self._handlers.pop(tool_name, None)
        logger.info(f"Tool unregistered: {tool_name}")
        return True

    def get(self, tool_name: str) -> Optional[ToolContract]:
        """Get a tool by name."""
        return self._tools.get(tool_name)

    def list_all(self) -> List[ToolContract]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_names(self) -> List[str]:
        """List all tool names."""
        return list(self._tools.keys())

    async def execute(self, tool_name: str, params: Dict[str, Any],
                      permissions: Optional[List[str]] = None,
                      actor: str = "user") -> Dict[str, Any]:
        """
        Execute a tool with given parameters.

        Checks permissions, validates params, executes with timeout,
        and logs to audit trail.
        """
        contract = self._tools.get(tool_name)
        if not contract:
            return {"error": f"Tool {tool_name} not found", "success": False}

        # Resolve permissions from the server-side role policy when one exists.
        # Caller-supplied labels are never proof that an actor owns a role.
        available_permissions = set(permissions or [])
        if self._policy is not None:
            available_permissions = self._policy.get_role_permissions(actor)

        required = contract.permissions
        if not all(permission in available_permissions for permission in required):
            if self._audit:
                await self._audit.record(AuditEvent(
                    event_id=f"perm_{tool_name}_{int(time.time())}",
                    action=AuditAction.PERMISSION_CHECK,
                    timestamp=time.time(),
                    actor=actor,
                    details={
                        "tool": tool_name,
                        "required": required,
                        "have": sorted(available_permissions),
                    },
                    result="denied",
                ))
            return {
                "error": f"Insufficient permissions for {tool_name}. Required: {required}",
                "success": False,
            }

        if self._policy is not None:
            policy_error = self._check_resource_policy(tool_name, params, contract)
            if policy_error:
                return {"error": policy_error, "success": False}

        # Validate parameters
        is_valid, error = contract.validate_params(params)
        if not is_valid:
            return {"error": f"Invalid parameters: {error}", "success": False}

        # Check if confirmation is required
        if contract.requires_confirmation and not params.get("_confirmed"):
            return {
                "error": f"{tool_name} requires confirmation. Set _confirmed=True.",
                "success": False,
            }

        # Execute with timeout
        start_time = time.time()
        try:
            handler = self._handlers.get(tool_name)
            if not handler:
                return {"error": f"No handler for tool {tool_name}", "success": False}

            if asyncio.iscoroutinefunction(handler):
                result = await asyncio.wait_for(
                    handler(params, contract),
                    timeout=contract.timeout_seconds,
                )
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, lambda: handler(params, contract)
                )

            execution_time = time.time() - start_time

            # Audit log
            if self._audit:
                await self._audit.record(AuditEvent(
                    event_id=f"tool_{tool_name}_{int(time.time())}",
                    action=AuditAction.TOOL_CALL,
                    timestamp=time.time(),
                    actor=actor,
                    details={
                        "tool": tool_name,
                        "params": params,
                        "result": result,
                        "execution_time_ms": round(execution_time * 1000, 2),
                    },
                    result="success" if result.get("success") else "error",
                    error=result.get("error"),
                ))

            result["execution_time_ms"] = round(execution_time * 1000, 2)
            return result

        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            if self._audit:
                await self._audit.record(AuditEvent(
                    event_id=f"timeout_{tool_name}_{int(time.time())}",
                    action=AuditAction.TOOL_CALL,
                    timestamp=time.time(),
                    actor=actor,
                    details={"tool": tool_name, "params": params},
                    result="timeout",
                    error=f"Execution timed out after {contract.timeout_seconds}s",
                ))
            return {
                "error": f"Tool {tool_name} timed out after {contract.timeout_seconds}s",
                "success": False,
                "execution_time_ms": round(execution_time * 1000, 2),
            }

        except Exception as e:
            execution_time = time.time() - start_time
            if self._audit:
                await self._audit.record(AuditEvent(
                    event_id=f"err_{tool_name}_{int(time.time())}",
                    action=AuditAction.TOOL_CALL,
                    timestamp=time.time(),
                    actor=actor,
                    details={"tool": tool_name, "params": params},
                    result="error",
                    error=str(e),
                ))
            return {
                "error": str(e),
                "success": False,
                "execution_time_ms": round(execution_time * 1000, 2),
            }

    def _check_resource_policy(
        self,
        tool_name: str,
        params: Dict[str, Any],
        contract: ToolContract,
    ) -> Optional[str]:
        """Apply filesystem and command scopes at the execution boundary."""
        source = str(params.get("source") or "")
        destination = str(params.get("destination") or "")
        path = str(params.get("path") or "")
        mutating = bool(
            {"read_write", "write_only", "destructive"}.intersection(contract.permissions)
        )

        if source and not self._policy.is_file_read_allowed(source):
            return f"Read not allowed for path: {source}"
        if destination and not self._policy.is_file_write_allowed(destination):
            return f"Write not allowed for path: {destination}"
        if path:
            allowed = (
                self._policy.is_file_write_allowed(path)
                if mutating
                else self._policy.is_file_read_allowed(path)
            )
            if not allowed:
                action = "Write" if mutating else "Read"
                return f"{action} not allowed for path: {path}"

        command = str(params.get("command") or "")
        if command and not self._policy.is_command_allowed(command):
            return "Command is not permitted by the execution allowlist"
        return None

    def check_permission(self, tool_name: str, permissions: List[str]) -> bool:
        """Check if permissions are sufficient for a tool."""
        contract = self._tools.get(tool_name)
        if not contract:
            return False
        return all(p in permissions for p in contract.permissions)


# ─── Built-in Tool Handlers ─────────────────────────────────────────

def _handle_read_file(params: Dict, contract: ToolContract) -> Dict:
    """Read a file from the filesystem."""
    path = params.get("path", "")
    if not path:
        return {"error": "path is required", "success": False}

    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}", "success": False}
        if not p.is_file():
            return {"error": f"Not a file: {path}", "success": False}

        content = p.read_text(encoding="utf-8", errors="replace")
        return {
            "path": str(path),
            "content": content,
            "lines": len(content.split("\n")),
            "size_bytes": p.stat().st_size,
            "success": True,
        }
    except PermissionError:
        return {"error": f"Permission denied: {path}", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_write_file(params: Dict, contract: ToolContract) -> Dict:
    """Write content to a file."""
    path = params.get("path", "")
    content = params.get("content", "")
    if not path:
        return {"error": "path is required", "success": False}

    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {
            "path": str(path),
            "bytes_written": len(content.encode("utf-8")),
            "success": True,
        }
    except PermissionError:
        return {"error": f"Permission denied: {path}", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_list_directory(params: Dict, contract: ToolContract) -> Dict:
    """List contents of a directory."""
    path = params.get("path", ".")
    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"Path not found: {path}", "success": False}
        if not p.is_dir():
            return {"error": f"Not a directory: {path}", "success": False}

        entries = []
        for item in sorted(p.iterdir()):
            if not _is_discoverable_path(item):
                continue
            entry = {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            }
            entries.append(entry)

        return {
            "path": str(path),
            "entries": entries,
            "count": len(entries),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_search_files(params: Dict, contract: ToolContract) -> Dict:
    """Search for files by name pattern."""
    pattern = params.get("pattern", "*")
    path = params.get("path", ".")
    if not isinstance(pattern, str) or "/" in pattern.replace("\\", "/"):
        return {"error": "pattern must be a filename glob without path separators", "success": False}
    try:
        p = Path(path)
        results = []
        for m in p.glob(f"**/{pattern}"):
            if not _is_discoverable_path(m):
                continue
            results.append({
                "path": str(m),
                "type": "directory" if m.is_dir() else "file",
                "size": m.stat().st_size if m.is_file() else None,
            })
            if len(results) >= 100:
                break
        return {
            "pattern": pattern,
            "path": str(path),
            "matches": results,
            "count": len(results),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_run_command(params: Dict, contract: ToolContract) -> Dict:
    """Run an allowlisted command without invoking a command shell."""
    command = params.get("command", "")
    if not command:
        return {"error": "command is required", "success": False}

    try:
        timeout = contract.timeout_seconds if contract else 30
        argv = command if os.name == "nt" else shlex.split(command)
        if not argv:
            return {"error": "command is required", "success": False}
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout[:10000],  # Limit output
            "stderr": result.stderr[:10000],
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_read_directory(params: Dict, contract: ToolContract) -> Dict:
    """Read all files in a directory tree."""
    path = params.get("path", ".")
    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"Path not found: {path}", "success": False}

        files = []
        for f in p.rglob("*"):
            if f.is_file() and not f.name.startswith(".") and _is_discoverable_path(f):
                files.append(str(f))

        return {
            "path": str(path),
            "files": files[:200],  # Limit
            "count": len(files),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_get_file_info(params: Dict, contract: ToolContract) -> Dict:
    """Get metadata about a file."""
    path = params.get("path", "")
    if not path:
        return {"error": "path is required", "success": False}

    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"Path not found: {path}", "success": False}

        stat = p.stat()
        return {
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_list_processes(params: Dict, contract: ToolContract) -> Dict:
    """List running processes."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV"],
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            result = subprocess.run(
                ["ps", "aux"],
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
            )

        lines = result.stdout.strip().split("\n")
        processes = []
        for line in lines[1:]:  # Skip header
            if os.name == "nt":
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    processes.append({"name": parts[0], "pid": parts[1]})
            else:
                parts = line.split()
                if len(parts) >= 2:
                    processes.append({"user": parts[0], "pid": parts[1], "command": " ".join(parts[10:])})

        return {
            "processes": processes[:100],
            "count": len(processes),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_disk_usage(params: Dict, contract: ToolContract) -> Dict:
    """Get disk usage information."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["wmic", "logicaldisk", "get", "size,freespace,caption"],
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            result = subprocess.run(
                ["df", "-h"],
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
            )

        return {
            "output": result.stdout[:5000],
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_search_code(params: Dict, contract: ToolContract) -> Dict:
    """Search for text patterns in code files."""
    pattern = params.get("pattern", "")
    path = params.get("path", ".")
    file_types = params.get("file_types", [".py", ".js", ".ts", ".java", ".go", ".rs"])

    if not pattern:
        return {"error": "pattern is required", "success": False}
    if not isinstance(file_types, list) or any(
        not isinstance(extension, str)
        or not extension.startswith(".")
        or not extension[1:].isalnum()
        for extension in file_types
    ):
        return {"error": "file_types must contain simple extensions such as .py", "success": False}

    try:
        p = Path(path)
        matches = []

        for ext in file_types:
            for f in p.rglob(f"*{ext}"):
                if f.is_file() and _is_discoverable_path(f):
                    try:
                        content = f.read_text(encoding="utf-8", errors="ignore")
                        lines = content.split("\n")
                        for i, line in enumerate(lines, 1):
                            if pattern.lower() in line.lower():
                                matches.append({
                                    "file": str(f),
                                    "line": i,
                                    "content": line.strip()[:200],
                                })
                                if len(matches) >= 100:
                                    break
                    except Exception:
                        pass
                if len(matches) >= 100:
                    break
            if len(matches) >= 100:
                break

        return {
            "pattern": pattern,
            "path": str(path),
            "matches": matches[:100],
            "count": len(matches),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_read_json(params: Dict, contract: ToolContract) -> Dict:
    """Read and parse a JSON file."""
    path = params.get("path", "")
    if not path:
        return {"error": "path is required", "success": False}

    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}", "success": False}

        content = p.read_text(encoding="utf-8")
        data = json.loads(content)
        return {
            "path": str(path),
            "data": data,
            "type": type(data).__name__,
            "success": True,
        }
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_write_json(params: Dict, contract: ToolContract) -> Dict:
    """Write data to a JSON file."""
    path = params.get("path", "")
    data = params.get("data", {})
    if not path:
        return {"error": "path is required", "success": False}

    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, indent=2, default=str)
        p.write_text(content, encoding="utf-8")
        return {
            "path": str(path),
            "bytes_written": len(content.encode("utf-8")),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_delete_file(params: Dict, contract: ToolContract) -> Dict:
    """Delete a file."""
    path = params.get("path", "")
    if not path:
        return {"error": "path is required", "success": False}

    # Check confirmation for destructive operations
    if contract and contract.requires_confirmation and not params.get("_confirmed"):
        return {
            "error": "Deletion requires confirmation. Set _confirmed=True.",
            "success": False,
        }

    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"Path not found: {path}", "success": False}
        p.unlink()
        return {"path": str(path), "deleted": True, "success": True}
    except PermissionError:
        return {"error": f"Permission denied: {path}", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_copy_file(params: Dict, contract: ToolContract) -> Dict:
    """Copy a file."""
    src = params.get("source", "")
    dst = params.get("destination", "")
    if not src or not dst:
        return {"error": "source and destination are required", "success": False}

    try:
        import shutil
        s = Path(src)
        d = Path(dst)
        if not s.exists():
            return {"error": f"Source not found: {src}", "success": False}
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        return {
            "source": str(src),
            "destination": str(dst),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_move_file(params: Dict, contract: ToolContract) -> Dict:
    """Move/rename a file."""
    src = params.get("source", "")
    dst = params.get("destination", "")
    if not src or not dst:
        return {"error": "source and destination are required", "success": False}

    try:
        s = Path(src)
        d = Path(dst)
        if not s.exists():
            return {"error": f"Source not found: {src}", "success": False}
        d.parent.mkdir(parents=True, exist_ok=True)
        s.rename(d)
        return {
            "source": str(src),
            "destination": str(dst),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_search_text(params: Dict, contract: ToolContract) -> Dict:
    """Search for text in file contents."""
    pattern = params.get("pattern", "")
    path = params.get("path", ".")
    if not pattern:
        return {"error": "pattern is required", "success": False}

    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"Path not found: {path}", "success": False}

        matches = []
        files = [p] if p.is_file() else p.glob("**/*")

        inspected = 0
        for f in files:
            if f.is_file() and not f.name.startswith(".") and _is_discoverable_path(f):
                inspected += 1
                if inspected > 500:
                    break
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    lines = content.split("\n")
                    for i, line in enumerate(lines, 1):
                        if pattern.lower() in line.lower():
                            matches.append({
                                "file": str(f),
                                "line": i,
                                "content": line.strip()[:300],
                            })
                            if len(matches) >= 100:
                                break
                except Exception:
                    pass
            if len(matches) >= 100:
                break

        return {
            "pattern": pattern,
            "path": str(path),
            "matches": matches[:100],
            "count": len(matches),
            "success": True,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_get_env(params: Dict, contract: ToolContract) -> Dict:
    """Get non-secret diagnostic environment variables."""
    name = params.get("name", "")
    try:
        if name:
            if not _is_safe_environment_name(name):
                return {
                    "error": f"Environment variable is not available through this tool: {name}",
                    "success": False,
                }
            value = os.environ.get(name, "")
            return {"name": name, "value": value, "success": True}
        else:
            env = {
                key: value
                for key, value in sorted(os.environ.items())
                if _is_safe_environment_name(key)
            }
            return {"env": dict(list(env.items())[:50]), "count": len(env), "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


_SAFE_ENVIRONMENT_NAMES = {
    "CUDA_VISIBLE_DEVICES",
    "LANG",
    "LOG_LEVEL",
    "PATH",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "QT_AUTO_SCREEN_SCALE_FACTOR",
    "QT_SCALE_FACTOR_ROUNDING_POLICY",
}
_SAFE_ENVIRONMENT_PREFIXES = (
    "LM_STUDIO_",
    "NVIDIA_",
    "REDSIGHT_",
    "RED_SIGHT_",
    "VECTOR_BACKEND_",
)
_SENSITIVE_ENVIRONMENT_MARKERS = (
    "AUTH",
    "COOKIE",
    "CREDENTIAL",
    "KEY",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)


def _is_safe_environment_name(name: str) -> bool:
    normalized = str(name).strip().upper()
    if not normalized or any(marker in normalized for marker in _SENSITIVE_ENVIRONMENT_MARKERS):
        return False
    return normalized in _SAFE_ENVIRONMENT_NAMES or normalized.startswith(
        _SAFE_ENVIRONMENT_PREFIXES
    )


def _handle_list_skills(params: Dict, contract: ToolContract) -> Dict:
    """List available skills."""
    try:
        from app.server import skill_registry
        if skill_registry:
            skills = skill_registry.list_all()
            return {
                "skills": [s.to_dict() for s in skills],
                "count": len(skills),
                "success": True,
            }
        return {"error": "Skill registry not initialized", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_list_tools(params: Dict, contract: ToolContract) -> Dict:
    """List available tools."""
    try:
        from app.server import tool_registry
        if tool_registry:
            tools = tool_registry.list_all()
            return {
                "tools": [t.to_dict() for t in tools],
                "count": len(tools),
                "success": True,
            }
        return {"error": "Tool registry not initialized", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}
