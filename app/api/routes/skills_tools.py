"""
RedSight - High-Performance Local AI Intelligence Platform
API Routes - Skills & Tools (Phase 3)

Endpoints for skill discovery, tool execution, permission checks,
audit trail, and agent orchestration.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

router = APIRouter()


# ─── Request/Response Models ──────────────────────────────────────

class SkillSearchRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
    limit: int = Field(default=10, description="Max results")


class SkillSearchResult(BaseModel):
    skill_id: str
    name: str
    description: str
    version: str
    score: float


class ToolExecuteRequest(BaseModel):
    tool_name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    role: str = Field(default="user", description="Execution role")


class ToolExecuteResult(BaseModel):
    success: bool
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0


class OrchestrateRequest(BaseModel):
    query: str = Field(..., description="User query")
    role: str = Field(default="agent", description="Execution role")


class AuditQueryRequest(BaseModel):
    actor: Optional[str] = None
    action: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    limit: int = Field(default=100)


class TestValidateRequest(BaseModel):
    tool_name: str
    params: Dict[str, Any] = Field(default_factory=dict)


# ─── Skill Discovery Endpoints ────────────────────────────────────

@router.post("/skills/search")
async def search_skills(request: SkillSearchRequest):
    """Search for relevant skills by natural language query."""
    from app.server import skill_discovery
    if not skill_discovery:
        raise HTTPException(status_code=503, detail="Skill discovery not initialized")

    results = skill_discovery.search(request.query, limit=request.limit)
    return {
        "query": request.query,
        "results": [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "score": round(score, 3),
            }
            for s, score in results
        ],
        "count": len(results),
    }


@router.get("/skills")
async def list_skills():
    """List all available skills."""
    from app.server import skill_discovery
    if not skill_discovery:
        raise HTTPException(status_code=503, detail="Skill discovery not initialized")

    skills = skill_discovery.list_all()
    return {
        "skills": [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "permissions": s.allowed_tools,
            }
            for s in skills
        ],
        "count": len(skills),
    }


# ─── Tool Execution Endpoints ─────────────────────────────────────

@router.post("/tools/execute")
async def execute_tool(request: ToolExecuteRequest):
    """Execute a tool with given parameters."""
    from app.server import tool_registry
    if not tool_registry:
        raise HTTPException(status_code=503, detail="Tool registry not initialized")

    result = await tool_registry.execute(
        tool_name=request.tool_name,
        params=request.params,
        permissions=[request.role],
        actor=request.role,
    )
    return result


@router.get("/tools")
async def list_tools():
    """List all available tools."""
    from app.server import tool_registry
    if not tool_registry:
        raise HTTPException(status_code=503, detail="Tool registry not initialized")

    tools = tool_registry.list_all()
    return {
        "tools": [t.to_dict() for t in tools],
        "count": len(tools),
    }


# ─── Agent Orchestration Endpoint ─────────────────────────────────

@router.post("/orchestrate")
async def orchestrate(request: OrchestrateRequest):
    """
    Orchestrate skill/tool execution for a query.

    The agent discovers relevant skills, selects the best match,
    checks permissions, executes via sandbox, and returns results.
    """
    from app.server import agent_orchestrator
    if not agent_orchestrator:
        raise HTTPException(status_code=503, detail="Agent orchestrator not initialized")

    result = await agent_orchestrator.orchestrate(
        query=request.query,
        role=request.role,
    )
    return result.to_dict()


@router.get("/orchestrator/stats")
async def orchestrator_stats():
    """Get orchestrator statistics."""
    from app.server import agent_orchestrator
    if not agent_orchestrator:
        raise HTTPException(status_code=503, detail="Agent orchestrator not initialized")

    return agent_orchestrator.get_stats()


# ─── Audit Trail Endpoints ────────────────────────────────────────

@router.post("/audit/query")
async def query_audit(request: AuditQueryRequest):
    """Query audit events with filters."""
    from app.server import audit_logger
    if not audit_logger:
        raise HTTPException(status_code=503, detail="Audit logger not initialized")

    from app.core.interfaces import AuditAction
    action_enum = None
    if request.action:
        try:
            action_enum = AuditAction(request.action)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")

    events = await audit_logger.query(
        actor=request.actor,
        action=action_enum,
        start_time=request.start_time,
        end_time=request.end_time,
        limit=request.limit,
    )
    return {
        "events": [e.to_dict() for e in events],
        "count": len(events),
    }


@router.get("/audit/stats")
async def audit_stats():
    """Get audit statistics."""
    from app.server import audit_logger
    if not audit_logger:
        raise HTTPException(status_code=503, detail="Audit logger not initialized")

    tool_stats = await audit_logger.get_tool_stats()
    skill_stats = await audit_logger.get_skill_stats()
    return {
        "tool_calls": tool_stats,
        "skill_executions": skill_stats,
    }


# ─── Permission Check Endpoint ────────────────────────────────────

class PermissionCheckRequest(BaseModel):
    tool_name: str
    role: str = Field(default="user")
    params: Dict[str, Any] = Field(default_factory=dict)


@router.post("/permissions/check")
async def check_permission(request: PermissionCheckRequest):
    """Check if a role can execute a tool."""
    from app.server import permission_checker, tool_registry
    if not permission_checker:
        raise HTTPException(status_code=503, detail="Permission checker not initialized")

    contract = tool_registry.get(request.tool_name) if tool_registry else None
    if not contract:
        raise HTTPException(status_code=404, detail=f"Tool {request.tool_name} not found")

    result = await permission_checker.check_tool_permission(
        role=request.role,
        tool_name=request.tool_name,
        tool_permissions=contract.permissions,
        params=request.params,
    )
    return result


# ─── Test Runner Endpoint ─────────────────────────────────────────

@router.post("/tools/validate")
async def validate_tool(request: TestValidateRequest):
    """Validate a tool with test parameters."""
    from app.tools.test_runner import TestRunner
    runner = TestRunner(project_root=".")
    result = await runner.validate_tool(request.tool_name, request.params)
    return result.to_dict()


@router.post("/skills/validate")
async def validate_skill(skill_id: str):
    """Validate a skill."""
    from app.tools.test_runner import TestRunner
    runner = TestRunner(project_root=".")
    result = await runner.validate_skill(skill_id)
    return result.to_dict()
