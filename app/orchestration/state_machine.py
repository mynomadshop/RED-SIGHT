"""
RedSight - High-Performance Local AI Intelligence Platform
Task State Machine

Manages task lifecycle states and transitions.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    PLANNING = "planning"
    QUEUED = "queued"
    RUNNING = "running"
    EVALUATING = "evaluating"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidTransition(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class TaskStateMachine:
    """
    Task State Machine - Manages task lifecycle states.
    
    Enforces valid state transitions and prevents invalid state changes.
    """
    
    # Define valid transitions
    VALID_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
        TaskState.PENDING: {TaskState.PLANNING, TaskState.CANCELLED},
        TaskState.PLANNING: {TaskState.QUEUED, TaskState.FAILED, TaskState.CANCELLED},
        TaskState.QUEUED: {TaskState.RUNNING, TaskState.CANCELLED},
        TaskState.RUNNING: {TaskState.EVALUATING, TaskState.FAILED, TaskState.CANCELLED},
        TaskState.EVALUATING: {TaskState.COMPLETE, TaskState.FAILED, TaskState.RUNNING},
        TaskState.COMPLETE: set(),  # Terminal state
        TaskState.FAILED: set(),  # Terminal state
        TaskState.CANCELLED: set(),  # Terminal state
    }
    
    def __init__(self):
        self._states: Dict[str, TaskState] = {}  # task_id -> state
        self._metadata: Dict[str, Dict[str, Any]] = {}  # task_id -> metadata
    
    async def set_state(self, task_id: str, new_state: TaskState) -> bool:
        """
        Transition a task to a new state.
        
        Returns True if transition was valid and applied.
        Raises InvalidTransition if the transition is not allowed.
        """
        current_state = self._states.get(task_id)
        
        if current_state is None:
            # First state - must be PENDING
            if new_state != TaskState.PENDING:
                raise InvalidTransition(
                    f"Task {task_id} must start in PENDING state, got {new_state.value}"
                )
            self._states[task_id] = new_state
            self._metadata[task_id] = {"state_history": [new_state.value]}
            logger.info(f"Task {task_id} created in state {new_state.value}")
            return True
        
        # Check if transition is valid
        allowed = self.VALID_TRANSITIONS.get(current_state, set())
        if new_state not in allowed:
            raise InvalidTransition(
                f"Invalid transition for task {task_id}: "
                f"{current_state.value} -> {new_state.value} "
                f"(allowed: {[s.value for s in allowed] or ['none']})"
            )
        
        # Apply transition
        self._states[task_id] = new_state
        self._metadata[task_id]["state_history"].append(new_state.value)
        self._metadata[task_id]["last_transition"] = new_state.value
        
        logger.debug(f"Task {task_id}: {current_state.value} -> {new_state.value}")
        return True
    
    async def get_state(self, task_id: str) -> Optional[TaskState]:
        """Get the current state of a task."""
        return self._states.get(task_id)
    
    async def is_terminal(self, task_id: str) -> bool:
        """Check if a task is in a terminal state."""
        state = self._states.get(task_id)
        return state in (TaskState.COMPLETE, TaskState.FAILED, TaskState.CANCELLED)
    
    async def get_history(self, task_id: str) -> List[str]:
        """Get the state history for a task."""
        return self._metadata.get(task_id, {}).get("state_history", [])
    
    async def set_metadata(self, task_id: str, key: str, value: Any) -> None:
        """Set metadata for a task."""
        if task_id not in self._metadata:
            self._metadata[task_id] = {}
        self._metadata[task_id][key] = value
    
    async def get_metadata(self, task_id: str, key: str, default: Any = None) -> Any:
        """Get metadata for a task."""
        return self._metadata.get(task_id, {}).get(key, default)
    
    async def list_tasks(self, state: Optional[TaskState] = None) -> Dict[str, TaskState]:
        """List tasks, optionally filtered by state."""
        if state:
            return {
                tid: st for tid, st in self._states.items() if st == state
            }
        return dict(self._states)
