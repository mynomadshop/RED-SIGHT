"""
RedSight - High-Performance Local AI Intelligence Platform
Test Runner

Validates tool and skill behavior before promoting to production.
Runs unit tests, integration tests, and regression tests.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    duration_ms: float = 0.0
    error: Optional[str] = None
    output: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "output": self.output[:2000],
        }


@dataclass
class TestSuite:
    """Result of a test suite run."""
    __test__ = False

    name: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    results: List[TestResult] = field(default_factory=list)
    duration_ms: float = 0.0
    success: bool = True

    def summarize(self) -> "TestSuite":
        """Synchronize aggregate counters with detailed validation results."""
        self.total = len(self.results)
        self.passed = sum(result.passed for result in self.results)
        self.failed = self.total - self.passed
        self.success = self.total > 0 and self.failed == 0
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "results": [r.to_dict() for r in self.results],
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
        }


class TestRunner:
    """
    Test Runner - Validates tool and skill behavior.

    Supports:
    - Unit tests (pytest)
    - Integration tests
    - Tool-specific validation
    - Skill-specific validation
    - Regression testing
    """
    __test__ = False

    def __init__(self, project_root: str = "."):
        self._project_root = Path(project_root)
        self._test_suites: Dict[str, List[str]] = {}
        self._regression_results: Dict[str, List[TestResult]] = {}

    def register_suite(self, name: str, test_paths: List[str]) -> None:
        """Register a test suite."""
        self._test_suites[name] = test_paths
        logger.info(f"Test suite registered: {name} ({len(test_paths)} tests)")

    async def run_suite(self, name: str) -> TestSuite:
        """Run a registered test suite."""
        if name not in self._test_suites:
            return TestSuite(
                name=name,
                total=1,
                failed=1,
                results=[TestResult(
                    name="suite_exists",
                    passed=False,
                    error=f"Suite '{name}' not found",
                )],
                success=False,
            )

        start_time = time.time()
        suite = TestSuite(name=name)

        try:
            # Pass each node/path directly to pytest. Avoid a shell so suite
            # registration cannot become command execution.
            test_paths = self._test_suites[name]
            if not test_paths or any(not path or path.startswith("-") for path in test_paths):
                raise ValueError("Test suites require one or more non-option pytest paths")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", *test_paths, "-v", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(self._project_root),
                check=False,
            )

            # Parse results
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            lines = output.split("\n")

            for line in lines:
                if "PASSED" in line:
                    suite.passed += 1
                    suite.total += 1
                    # Extract test name
                    parts = line.split(" PASSED")
                    if parts:
                        test_name = parts[0].split("::")[-1] if "::" in parts[0] else parts[0]
                        suite.results.append(TestResult(
                            name=test_name.strip(),
                            passed=True,
                        ))
                elif "FAILED" in line:
                    suite.failed += 1
                    suite.total += 1
                    parts = line.split(" FAILED")
                    if parts:
                        test_name = parts[0].split("::")[-1] if "::" in parts[0] else parts[0]
                        suite.results.append(TestResult(
                            name=test_name.strip(),
                            passed=False,
                            error="Test failed",
                        ))
                elif "SKIPPED" in line:
                    suite.skipped += 1
                    suite.total += 1

            if result.returncode != 0 and suite.failed == 0:
                suite.failed = 1
                suite.total += 1
                suite.results.append(TestResult(
                    name="pytest",
                    passed=False,
                    error=f"pytest exited with status {result.returncode}",
                    output=output,
                ))
            suite.success = result.returncode == 0 and suite.failed == 0

        except subprocess.TimeoutExpired:
            suite.success = False
            suite.failed += 1
            suite.total += 1
            suite.results.append(TestResult(
                name=name,
                passed=False,
                error="Test suite timed out",
            ))
        except Exception as e:
            suite.success = False
            suite.failed += 1
            suite.total += 1
            suite.results.append(TestResult(
                name=name,
                passed=False,
                error=str(e),
            ))

        suite.duration_ms = (time.time() - start_time) * 1000
        return suite

    async def validate_tool(self, tool_name: str, params: Dict[str, Any]) -> TestSuite:
        """Validate a specific tool with test parameters."""
        start_time = time.time()
        suite = TestSuite(name=f"validate_tool:{tool_name}")

        try:
            from app.server import tool_registry
            if not tool_registry:
                suite.results.append(TestResult(
                    name="registry_check",
                    passed=False,
                    error="Tool registry not initialized",
                ))
                return suite.summarize()

            contract = tool_registry.get(tool_name)
            if inspect.isawaitable(contract):
                contract = await contract
            if not contract:
                suite.results.append(TestResult(
                    name="tool_exists",
                    passed=False,
                    error=f"Tool {tool_name} not found",
                ))
                return suite.summarize()

            # Test 1: Contract validation
            suite.results.append(TestResult(
                name="contract_validation",
                passed=True,
            ))

            # Test 2: Parameter validation
            is_valid, error = contract.validate_params(params)
            if is_valid:
                suite.results.append(TestResult(
                    name="param_validation",
                    passed=True,
                ))
            else:
                suite.results.append(TestResult(
                    name="param_validation",
                    passed=False,
                    error=error,
                ))

            # Test 3: Execution
            result = await tool_registry.execute(
                tool_name,
                params,
                permissions=["read_only"],
                actor="user",
            )
            if result.get("success"):
                suite.results.append(TestResult(
                    name="execution",
                    passed=True,
                ))
            else:
                suite.results.append(TestResult(
                    name="execution",
                    passed=False,
                    error=result.get("error"),
                ))

        except Exception as e:
            suite.results.append(TestResult(
                name="validation",
                passed=False,
                error=str(e),
            ))

        suite.duration_ms = (time.time() - start_time) * 1000
        return suite.summarize()

    async def validate_skill(self, skill_id: str) -> TestSuite:
        """Validate a specific skill."""
        start_time = time.time()
        suite = TestSuite(name=f"validate_skill:{skill_id}")

        try:
            from app.server import skill_registry
            if not skill_registry:
                suite.results.append(TestResult(
                    name="registry_check",
                    passed=False,
                    error="Skill registry not initialized",
                ))
                return suite.summarize()

            manifest = await skill_registry.get(skill_id)
            if not manifest:
                suite.results.append(TestResult(
                    name="skill_exists",
                    passed=False,
                    error=f"Skill {skill_id} not found",
                ))
                return suite.summarize()

            # Test 1: Manifest validation
            is_valid, errors = manifest.validate()
            if is_valid:
                suite.results.append(TestResult(
                    name="manifest_validation",
                    passed=True,
                ))
            else:
                suite.results.append(TestResult(
                    name="manifest_validation",
                    passed=False,
                    error="; ".join(errors),
                ))

            # Test 2: Sandbox execution
            from app.server import sandbox
            if sandbox:
                result = await sandbox.execute(
                    entry_point=manifest.entry_point,
                    inputs={},
                    actor="test_runner",
                    skill_id=skill_id,
                )
                if result.success:
                    suite.results.append(TestResult(
                        name="sandbox_execution",
                        passed=True,
                    ))
                else:
                    suite.results.append(TestResult(
                        name="sandbox_execution",
                        passed=False,
                        error=result.error,
                    ))

        except Exception as e:
            suite.results.append(TestResult(
                name="validation",
                passed=False,
                error=str(e),
            ))

        suite.duration_ms = (time.time() - start_time) * 1000
        return suite.summarize()

    async def run_all(self) -> Dict[str, TestSuite]:
        """Run all registered test suites."""
        results = {}
        for name in self._test_suites:
            results[name] = await self.run_suite(name)
        return results

    def save_regression_result(self, suite_name: str, results: List[TestResult]) -> None:
        """Save regression test results for comparison."""
        self._regression_results[suite_name] = results
        logger.info(f"Regression results saved for: {suite_name}")

    def compare_regression(self, suite_name: str) -> Dict[str, Any]:
        """Compare current results with regression baseline."""
        if suite_name not in self._regression_results:
            return {"error": "No regression baseline for suite"}

        baseline = self._regression_results[suite_name]
        # This would need current results passed in
        return {
            "baseline_tests": len(baseline),
            "baseline_passed": sum(1 for r in baseline if r.passed),
            "baseline_failed": sum(1 for r in baseline if not r.passed),
        }

    def get_suite_names(self) -> List[str]:
        """Get all registered suite names."""
        return list(self._test_suites.keys())
