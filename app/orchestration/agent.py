"""
RedSight - High-Performance Local AI Intelligence Platform
Agent Orchestrator

Selects and executes skills/tools based on user queries.
Uses semantic discovery, permission checks, and audit logging.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.skills.manifest import SkillManifest
from app.tools.contract import ToolContract

logger = logging.getLogger(__name__)


@dataclass
class OrchestrationResult:
    """Result of an orchestration run."""
    query: str
    selected_skill: Optional[str] = None
    selected_tool: Optional[str] = None
    steps: List[Dict[str, Any]] = field(default_factory=list)
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "selected_skill": self.selected_skill,
            "selected_tool": self.selected_tool,
            "steps": self.steps,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "success": self.success,
        }


class AgentOrchestrator:
    """
    Agent Orchestrator - Selects and executes skills/tools.

    Given a user query, it:
    1. Uses semantic discovery to find relevant skills
    2. Selects the best skill/tool based on relevance and permissions
    3. Executes via sandbox with timeout and audit logging
    4. Returns structured results with provenance
    """

    def __init__(
        self,
        skill_discovery=None,
        skill_registry=None,
        tool_registry=None,
        sandbox=None,
        permission_checker=None,
        audit_logger=None,
    ):
        self._discovery = skill_discovery
        self._skill_registry = skill_registry
        self._tool_registry = tool_registry
        self._sandbox = sandbox
        self._permission_checker = permission_checker
        self._audit = audit_logger
        self._role = "agent"  # Default execution role

    async def orchestrate(self, query: str, role: str = "agent") -> OrchestrationResult:
        """
        Orchestrate skill/tool execution for a query.

        1. Discover relevant skills
        2. Select best match
        3. Check permissions
        4. Execute via sandbox
        5. Audit log
        """
        start_time = time.time()
        self._role = role

        result = OrchestrationResult(query=query)

        try:
            # Step 1: Discover relevant skills
            if self._discovery:
                skills = self._discovery.search(query, limit=5)
                if skills:
                    best_skill, score = skills[0]
                    if score > 0.3:  # Minimum relevance threshold
                        result.selected_skill = best_skill.skill_id
                        result.steps.append({
                            "step": 1,
                            "action": "skill_discovery",
                            "skill_id": best_skill.skill_id,
                            "score": round(score, 3),
                        })

            # Step 2: Select tool if no skill matched
            if not result.selected_skill and self._tool_registry:
                tool = await self._select_tool(query)
                if tool:
                    result.selected_tool = tool

            # Step 3: Execute
            if result.selected_skill and self._sandbox:
                manifest = self._discovery.get_skill(result.selected_skill)
                if manifest:
                    result.steps.append({
                        "step": 2,
                        "action": "skill_execution",
                        "skill_id": result.selected_skill,
                    })

                    exec_result = await self._sandbox.execute(
                        entry_point=manifest.entry_point,
                        inputs={"query": query},
                        permissions=manifest.allowed_tools,
                        actor=role,
                        skill_id=result.selected_skill,
                    )

                    result.output = exec_result.output if exec_result.success else None
                    result.error = exec_result.error
                    result.success = exec_result.success

            elif result.selected_tool and self._tool_registry:
                result.steps.append({
                    "step": 2,
                    "action": "tool_execution",
                    "tool": result.selected_tool,
                })

                # Get the tool's required permissions
                tool_contract = await self._tool_registry.get(result.selected_tool)
                required_perms = tool_contract.permissions if tool_contract else ["read_only"]

                exec_result = await self._tool_registry.execute(
                    tool_name=result.selected_tool,
                    params={"query": query},
                    permissions=required_perms,
                )

                result.output = exec_result
                result.success = exec_result.get("success", False)
                result.error = exec_result.get("error")

            else:
                result.error = "No suitable skill or tool found for query"

        except Exception as e:
            result.error = str(e)
            result.success = False
            logger.error(f"Orchestration failed: {e}", exc_info=True)

        result.execution_time_ms = (time.time() - start_time) * 1000

        # Audit log
        if self._audit:
            from app.core.interfaces import AuditEvent, AuditAction
            await self._audit.record(AuditEvent(
                event_id=f"orch_{int(time.time())}",
                action=AuditAction.SKILL_EXECUTION,
                timestamp=time.time(),
                actor=role,
                details=result.to_dict(),
                result="success" if result.success else "error",
                error=result.error,
            ))

        return result

    async def _select_tool(self, query: str) -> Optional[str]:
        """Select the best tool for a query."""
        if not self._tool_registry:
            return None

        query_lower = query.lower()
        tools = self._tool_registry.list_all()

        # Simple keyword matching for tool selection
        tool_scores = {}
        for tool in tools:
            score = 0
            desc = tool.description.lower()
            name = tool.name.lower()
            # Check description
            if "file" in query_lower and "read" in query_lower:
                if "read" in desc:
                    score += 3
                if "file" in desc:
                    score += 2
            if "write" in query_lower:
                if "write" in desc:
                    score += 3
            if "search" in query_lower:
                if "search" in desc:
                    score += 3
            if "command" in query_lower or "run" in query_lower:
                if "command" in desc:
                    score += 3

            # Fallback: match query words against tool name/description
            query_words = set(query_lower.split())
            desc_words = set(desc.split())
            name_words = set(name.split())
            word_matches = len(query_words & desc_words) + len(query_words & name_words)
            if word_matches > score:
                score = word_matches

            if score > 0:
                tool_scores[tool.name] = score

        if tool_scores:
            best_tool = max(tool_scores, key=tool_scores.get)
            return best_tool

        return None

    async def list_available_skills(self) -> List[Dict[str, Any]]:
        """List all available skills with descriptions."""
        if not self._discovery:
            return []
        skills = self._discovery.list_all()
        return [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "permissions": s.allowed_tools,
            }
            for s in skills
        ]

    async def list_available_tools(self) -> List[Dict[str, Any]]:
        """List all available tools with descriptions."""
        if not self._tool_registry:
            return []
        tools = self._tool_registry.list_all()
        return [
            {
                "name": t.name,
                "description": t.description,
                "permissions": t.permissions,
                "timeout": t.timeout_seconds,
            }
            for t in tools
        ]

    def set_role(self, role: str) -> None:
        """Set the execution role."""
        self._role = role

    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        stats = {
            "role": self._role,
            "has_discovery": self._discovery is not None,
            "has_tool_registry": self._tool_registry is not None,
            "has_sandbox": self._sandbox is not None,
            "has_permission_checker": self._permission_checker is not None,
            "has_audit": self._audit is not None,
        }
        if self._discovery:
            stats["discovery_stats"] = self._discovery.get_stats()
        return stats
