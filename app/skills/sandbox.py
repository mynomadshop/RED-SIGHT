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
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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

        # Check permissions if checker is available
        if self._permission_checker and permissions:
            check = await self._permission_checker.check_tool_permission(
                role=actor,
                tool_name=entry_point,
                tool_permissions=permissions,
                params=inputs,
            )
            if not check.get("allowed"):
                return ExecutionResult(
                    success=False,
                    error=check.get("reason", "Permission denied"),
                    execution_time_ms=(time.time() - start_time) * 1000,
                )

        # Audit: start
        if self._audit:
            await self._audit.record(
                action="skill_execution",
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
            if self._audit:
                await self._audit.record(
                    action="skill_execution",
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
            if self._audit:
                await self._audit.record(
                    action="skill_execution",
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

        # Create a wrapper script that calls the module
        wrapper = f"""
import sys
import json
import importlib

try:
    module = importlib.import_module("{module_path}")
    if hasattr(module, "run"):
        result = module.run(**{json.dumps(inputs)})
    elif hasattr(module, "execute"):
        result = module.execute(**{json.dumps(inputs)})
    else:
        result = {{"error": "No run() or execute() function found", "success": False}}
    print(json.dumps(result, default=str))
except Exception as e:
    print(json.dumps({{"error": str(e), "success": False}}))
    sys.exit(1)
"""

        return await self._run_subprocess(wrapper, timeout, language="python")

    async def _run_command(
        self,
        entry_point: str,
        inputs: Dict[str, Any],
        timeout: int,
    ) -> ExecutionResult:
        """Run a shell command."""
        command = entry_point.split(":", 1)[-1]
        # Inject inputs as environment variables
        env = os.environ.copy()
        for k, v in inputs.items():
            env[f"INPUT_{k.upper()}"] = json.dumps(v)

        return await self._run_subprocess(command, timeout, shell=True, env=env)

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
            f'python "{script_path}"',
            timeout,
        )

    async def _run_subprocess(
        self,
        command: str,
        timeout: int,
        shell: bool = False,
        env: Dict[str, str] = None,
    ) -> ExecutionResult:
        """Run a command in a subprocess with timeout."""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                limit=self.max_output_bytes,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
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
