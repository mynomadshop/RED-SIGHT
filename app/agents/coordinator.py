"""
RedSight - High-Performance Local AI Intelligence Platform
Agent Runtime - Coordinator Agent

Owns the user request, decomposes work, chooses tools/skills,
and maintains task state.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent execution states."""
    INITIALIZED = "initialized"
    PLANNING = "planning"
    EXECUTING = "executing"
    EVALUATING = "evaluating"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ToolCall:
    """A tool call made by the agent."""
    tool_name: str
    parameters: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class AgentStep:
    """A single step in agent execution."""
    step_number: int
    action: str
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass
class AgentTask:
    """A task managed by the coordinator agent."""
    task_id: str
    user_request: str
    state: AgentState = AgentState.INITIALIZED
    plan: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    steps: List[AgentStep] = field(default_factory=list)
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_request": self.user_request,
            "state": self.state.value,
            "plan": self.plan,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "steps": [s.to_dict() for s in self.steps],
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class CoordinatorAgent:
    """
    Coordinator Agent - Orchestrates task execution.
    
    Owns the user request, decomposes work, chooses tools/skills,
    and maintains task state.
    """
    
    def __init__(self):
        self._tasks: Dict[str, AgentTask] = {}
        self._max_steps = 50
    
    async def create_task(self, user_request: str) -> str:
        """
        Create a new task from user request.
        
        Returns task_id.
        """
        task_id = str(uuid.uuid4())[:8]
        task = AgentTask(
            task_id=task_id,
            user_request=user_request,
            state=AgentState.INITIALIZED,
        )
        self._tasks[task_id] = task
        logger.info(f"Task {task_id} created: {user_request[:50]}...")
        return task_id
    
    async def plan_task(self, task_id: str, plan: List[Dict[str, Any]]) -> None:
        """
        Set the execution plan for a task.
        
        Plan is a list of steps with tool/skill names and parameters.
        """
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        task.state = AgentState.PLANNING
        task.plan = plan
        task.steps.append(AgentStep(
            step_number=len(task.steps) + 1,
            action="planning",
            details={"plan": plan},
        ))
        logger.info(f"Task {task_id} planned: {len(plan)} steps")
    
    async def execute_step(self, task_id: str, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a single step in a task.
        
        Returns the result of the step execution.
        """
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        if task.state not in (AgentState.PLANNING, AgentState.EXECUTING):
            raise ValueError(f"Task {task_id} is not in executing state (state={task.state.value})")
        
        task.state = AgentState.EXECUTING
        step_num = len(task.steps) + 1
        
        # Record step start
        task.steps.append(AgentStep(
            step_number=step_num,
            action=step.get("action", "unknown"),
            details=step.get("details", {}),
        ))
        
        # Execute tool call if specified
        if "tool_call" in step:
            tool_call = step["tool_call"]
            tc = ToolCall(
                tool_name=tool_call["name"],
                parameters=tool_call.get("parameters", {}),
                started_at=time.time(),
            )
            tc.started_at = time.time()
            
            # TODO: Actually execute the tool
            # For now, simulate
            tc.result = {"status": "simulated", "tool": tool_call["name"]}
            tc.completed_at = time.time()
            tc.error = None
            
            task.tool_calls.append(tc)
        
        return {"step_number": step_num, "status": "completed"}
    
    async def complete_task(self, task_id: str, result: Any) -> None:
        """Mark a task as complete."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        task.state = AgentState.COMPLETE
        task.result = result
        task.completed_at = time.time()
        
        logger.info(f"Task {task_id} completed in {task.completed_at - task.created_at:.1f}s")
    
    async def fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as failed."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        task.state = AgentState.FAILED
        task.error = error
        task.completed_at = time.time()
        
        logger.error(f"Task {task_id} failed: {error}")
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task details."""
        task = self._tasks.get(task_id)
        if not task:
            return None
        return task.to_dict()
    
    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all tasks."""
        tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]
