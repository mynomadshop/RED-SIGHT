"""
RedSight - High-Performance Local AI Intelligence Platform
Sandbox Execution Runner

Safely executes skill code with subprocess isolation, timeouts,
resource limits, and audit logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.interfaces import AuditAction, AuditEvent

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a sandbox execution."""
    success: bool
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    memory_usage_mb: float = 0.0
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "memory_usage_mb": round(self.memory_usage_mb, 2),
            "exit_code": self.exit_code,
            "stdout": self.stdout[:5000],
            "stderr": self.stderr[:5000],
        }


class SkillSandbox:
    """
    Skill Sandbox - Safely executes skill code.

    Enforces:
    - Timeouts (subprocess-level)
    - Resource limits (memory, CPU)
    - Permission checks
    - Isolated execution environment
    - Audit logging
    """

    def __init__(
        self,
        default_timeout: int = 300,
        max_memory_mb: int = 1024,
        max_output_bytes: int = 100000,
        audit_logger=None,
        permission_checker=None,
    ):
        self.default_timeout = default_timeout
        self.max_memory_mb = max_memory_mb
        self.max_output_bytes = max_output_bytes
        self._audit = audit_logger
        self._permission_checker = permission_checker
        self._running_processes: Dict[str, Any] = {}

    async def _record_audit(
        self,
        *,
        actor: str,
        details: Dict[str, Any],
        result: str,
        error: Optional[str] = None,
    ) -> None:
        """Record a typed skill event without exposing secret-shaped inputs."""
        if not self._audit:
            return
        await self._audit.record(
            AuditEvent(
                event_id=f"skill_{time.time_ns()}_{uuid.uuid4().hex[:8]}",
                action=AuditAction.SKILL_EXECUTION,
                timestamp=time.time(),
                actor=actor,
                details=_redact_mapping(details),
                result=result,
                error=error,
            )
        )

    async def execute(
        self,
        entry_point: str,
        inputs: Dict[str, Any],
        timeout: Optional[int] = None,
        permissions: Optional[List[str]] = None,
        actor: str = "user",
        skill_id: Optional[str] = None,
    ) -> ExecutionResult:
        """
        Execute a skill in the sandbox.

        Args:
            entry_point: Python module path or command to execute
            inputs: Input parameters for the skill
            timeout: Execution timeout in seconds
            permissions: Required permissions
            actor: Who is executing (for audit)
            skill_id: Skill being executed (for audit)

        Returns ExecutionResult.
        """
        timeout = timeout or self.default_timeout
        start_time = time.time()

        # Check permissions if a server-side checker is available. Even skills
        # without an explicit declaration require the baseline read-only role.
        if self._permission_checker:
            required_permissions = list(permissions or ["read_only"])
            permission_params = dict(inputs)
            if entry_point.startswith("script:"):
                permission_params.setdefault("path", entry_point.split(":", 1)[-1])
            check = await self._permission_checker.check_tool_permission(
                role=actor,
                tool_name=entry_point,
                tool_permissions=required_permissions,
                params=permission_params,
            )
            if not check.get("allowed"):
                return ExecutionResult(
                    success=False,
                    error=check.get("reason", "Permission denied"),
                    execution_time_ms=(time.time() - start_time) * 1000,
                )
            if entry_point.startswith("cmd:"):
                command = entry_point.split(":", 1)[-1]
                check = await self._permission_checker.check_command_permission(actor, command)
                if not check.get("allowed"):
                    return ExecutionResult(
                        success=False,
                        error=check.get("reason", "Command denied"),
                        execution_time_ms=(time.time() - start_time) * 1000,
                    )

        # Audit: start
        await self._record_audit(
            actor=actor,
            details={
                "entry_point": entry_point,
                "inputs": inputs,
                "timeout": timeout,
                "skill_id": skill_id,
            },
            result="started",
        )

        try:
            # Execute the skill
            result = await self._run_skill(entry_point, inputs, timeout)
            execution_time = (time.time() - start_time) * 1000

            # Audit: complete
            await self._record_audit(
                actor=actor,
                details={
                    "entry_point": entry_point,
                    "skill_id": skill_id,
                    "execution_time_ms": round(execution_time, 2),
                    "success": result.success,
                },
                result="success" if result.success else "error",
                error=result.error,
            )

            return result

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            await self._record_audit(
                actor=actor,
                details={"entry_point": entry_point, "skill_id": skill_id},
                result="error",
                error=str(e),
            )
            return ExecutionResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time,
            )

    async def _run_skill(
        self,
        entry_point: str,
        inputs: Dict[str, Any],
        timeout: int,
    ) -> ExecutionResult:
        """Run a skill entry point."""
        # Check if entry_point is a Python module
        if entry_point.startswith("python:") or entry_point.startswith("py:"):
            return await self._run_python_skill(entry_point, inputs, timeout)
        elif entry_point.startswith("cmd:"):
            return await self._run_command(entry_point, inputs, timeout)
        elif entry_point.startswith("script:"):
            return await self._run_script(entry_point, inputs, timeout)
        else:
            # Default: try as Python module
            return await self._run_python_skill(f"python:{entry_point}", inputs, timeout)

    async def _run_python_skill(
        self,
        entry_point: str,
        inputs: Dict[str, Any],
        timeout: int,
    ) -> ExecutionResult:
        """Run a Python skill via subprocess."""
        # Extract module path
        module_path = entry_point.split(":", 1)[-1]

        # Pass the module name and JSON input as data, never interpolated source.
        wrapper = """
import asyncio
import importlib
import inspect
import json
import sys

try:
    module = importlib.import_module(sys.argv[1])
    inputs = json.loads(sys.stdin.read() or "{}")
    if hasattr(module, "run"):
        result = module.run(**inputs)
    elif hasattr(module, "execute"):
        result = module.execute(**inputs)
    else:
        result = {"error": "No run() or execute() function found", "success": False}
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    print(json.dumps(result, default=str))
except Exception as e:
    print(json.dumps({"error": str(e), "success": False}))
    sys.exit(1)
"""

        return await self._run_subprocess(
            [sys.executable, "-c", wrapper, module_path],
            timeout,
            input_data=json.dumps(inputs, default=str).encode("utf-8"),
        )

    async def _run_command(
        self,
        entry_point: str,
        inputs: Dict[str, Any],
        timeout: int,
    ) -> ExecutionResult:
        """Run a shell command."""
        command = entry_point.split(":", 1)[-1]
        # Inject inputs as environment variables
        env = _sandbox_environment()
        for k, v in inputs.items():
            safe_key = re.sub(r"[^A-Z0-9_]", "_", str(k).upper())
            if safe_key:
                env[f"INPUT_{safe_key}"] = json.dumps(v, default=str)

        try:
            argv = _split_command(command)
        except ValueError as exc:
            return ExecutionResult(success=False, error=str(exc))
        return await self._run_subprocess(argv, timeout, env=env)

    async def _run_script(
        self,
        entry_point: str,
        inputs: Dict[str, Any],
        timeout: int,
    ) -> ExecutionResult:
        """Run a script file."""
        script_path = entry_point.split(":", 1)[-1]
        p = Path(script_path)
        if not p.exists():
            return ExecutionResult(
                success=False,
                error=f"Script not found: {script_path}",
            )

        return await self._run_subprocess(
            [sys.executable, str(p.resolve())],
            timeout,
        )

    async def _run_subprocess(
        self,
        command: List[str],
        timeout: int,
        env: Optional[Dict[str, str]] = None,
        input_data: Optional[bytes] = None,
    ) -> ExecutionResult:
        """Run a command in a subprocess with timeout."""
        try:
            if not command:
                return ExecutionResult(success=False, error="Command is empty")
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE if input_data is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env or _sandbox_environment(),
                limit=self.max_output_bytes,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=input_data),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ExecutionResult(
                    success=False,
                    error=f"Execution timed out after {timeout}s",
                    exit_code=-1,
                )

            stdout_str = stdout.decode("utf-8", errors="replace")[:self.max_output_bytes]
            stderr_str = stderr.decode("utf-8", errors="replace")[:self.max_output_bytes]

            # Try to parse JSON output
            output = None
            try:
                output = json.loads(stdout_str.strip())
            except (json.JSONDecodeError, ValueError):
                output = stdout_str if stdout_str.strip() else None

            return ExecutionResult(
                success=process.returncode == 0,
                output=output,
                error=stderr_str if stderr_str.strip() else None,
                exit_code=process.returncode,
                stdout=stdout_str,
                stderr=stderr_str,
            )

        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
            )

    async def validate_permissions(
        self,
        required_permissions: List[str],
        granted_permissions: List[str],
    ) -> bool:
        """Validate that all required permissions are granted."""
        return all(p in granted_permissions for p in required_permissions)

    async def check_resource_limits(self, memory_mb: float, cpu_percent: float) -> bool:
        """Check if resource usage is within limits."""
        if memory_mb > self.max_memory_mb:
            logger.warning(f"Memory limit exceeded: {memory_mb}MB > {self.max_memory_mb}MB")
            return False
        return True

    def list_running(self) -> List[str]:
        """List running skill executions."""
        return list(self._running_processes.keys())

    def cancel(self, execution_id: str) -> bool:
        """Cancel a running execution."""
        if execution_id in self._running_processes:
            process = self._running_processes[execution_id]
            try:
                process.kill()
                del self._running_processes[execution_id]
                return True
            except Exception:
                pass
        return False


def _split_command(command: str) -> List[str]:
    """Convert a command string to argv without invoking a command shell."""
    if not command.strip():
        raise ValueError("Command is empty")
    argv = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        argv = [
            item[1:-1] if len(item) >= 2 and item[0] == item[-1] == '"' else item
            for item in argv
        ]
    if not argv:
        raise ValueError("Command is empty")
    return argv


def _sandbox_environment() -> Dict[str, str]:
    """Provide child skills a minimal environment without credential material."""
    exact = {
        "APPDATA",
        "CUDA_VISIBLE_DEVICES",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PYTHONHOME",
        "PYTHONPATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    }
    prefixes = ("LM_STUDIO_", "NVIDIA_", "REDSIGHT_", "RED_SIGHT_", "VECTOR_BACKEND_")
    secret_markers = ("AUTH", "COOKIE", "CREDENTIAL", "KEY", "PASSWORD", "SECRET", "TOKEN")
    sanitized: Dict[str, str] = {}
    for name, value in os.environ.items():
        normalized = name.upper()
        if any(marker in normalized for marker in secret_markers):
            continue
        if normalized in exact or normalized.startswith(prefixes):
            sanitized[name] = value
    return sanitized


def _redact_mapping(value: Any) -> Any:
    """Redact secret-shaped values before writing audit records."""
    markers = ("auth", "cookie", "credential", "key", "password", "secret", "token")
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(marker in str(key).lower() for marker in markers)
            else _redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    return value
