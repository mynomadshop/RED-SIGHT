"""
RedSight - High-Performance Local AI Intelligence Platform
Orchestration Package

Provides task orchestration and agent coordination:
- Agent orchestration and skill/tool selection
- Multi-agent coordination with dependency management
- Task planning and decomposition
- Model/tool routing based on capability and resources
- Task state machine for lifecycle management
"""

from app.orchestration.agent import AgentOrchestrator, OrchestrationResult
from app.orchestration.multi_agent import (
    MultiAgentOrchestrator,
    AgentRole,
    AgentState,
    AgentTask,
    AgentMessage,
    OrchestratorResult,
)
from app.orchestration.planner import TaskPlanner
from app.orchestration.router import ModelToolRouter
from app.orchestration.state_machine import TaskStateMachine, TaskState, InvalidTransition

__all__ = [
    "AgentOrchestrator",
    "OrchestrationResult",
    "MultiAgentOrchestrator",
    "AgentRole",
    "AgentState",
    "AgentTask",
    "AgentMessage",
    "OrchestratorResult",
    "TaskPlanner",
    "ModelToolRouter",
    "TaskStateMachine",
    "TaskState",
    "InvalidTransition",
]
