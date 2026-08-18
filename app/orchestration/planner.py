"""
RedSight - High-Performance Local AI Intelligence Platform
Task Planner

Decomposes user requests into executable plans with tool/skill steps.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskPlanner:
    """
    Task Planner - Decomposes user requests into executable plans.
    
    Analyzes the user request and creates a structured plan with
    steps, tool calls, and expected outcomes.
    """
    
    def __init__(self, project_root: Optional[str] = None):
        self._templates: Dict[str, List[Dict[str, Any]]] = {}
        self._project_root = project_root or str(Path(__file__).resolve().parent.parent.parent)
        self._plans: Dict[str, Dict[str, Any]] = {}
    
    def register_template(self, task_type: str, template: List[Dict[str, Any]]) -> None:
        """Register a task template for a specific task type."""
        self._templates[task_type] = template
        logger.info(f"Task template registered: {task_type}")
    
    async def plan(self, user_request: str, task_type: Optional[str] = None,
                  context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Create an execution plan for a user request.
        
        Args:
            user_request: The user's request/question
            task_type: Optional task type hint
            context: Optional context from previous interactions
        
        Returns a list of steps to execute.
        """
        context = context or {}
        
        # If we have a template for this task type, use it
        if task_type and task_type in self._templates:
            plan = self._templates[task_type].copy()
            # Inject context into plan
            for step in plan:
                if "context" in step:
                    step["context"].update(context)
            logger.info(f"Plan created from template: {task_type}")
            return plan
        
        # Otherwise, create a basic plan
        plan = self._create_basic_plan(user_request, context)
        logger.info(f"Basic plan created for: {user_request[:50]}...")
        return plan
    
    def _create_basic_plan(self, user_request: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create a basic plan with standard steps."""
        plan = [
            {
                "step": 1,
                "action": "analyze_request",
                "details": {"request": user_request},
            },
            {
                "step": 2,
                "action": "retrieve_context",
                "details": {
                    "query": user_request,
                    "collections": ["knowledge_docs", "project_code"],
                    "top_k": 10,
                },
            },
            {
                "step": 3,
                "action": "generate_response",
                "details": {
                    "model": "fast_chat",
                    "temperature": 0.7,
                },
            },
        ]
        
        # Add context-dependent steps
        if any(kw in user_request.lower() for kw in ["code", "function", "class", "bug"]):
            plan.insert(2, {
                "step": 2,
                "action": "analyze_code",
                "details": {"query": user_request},
            })
        
        return plan
    
    async def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get a plan by ID from persistent storage."""
        # Try to load from SQLite if available
        try:
            import sqlite3
            db_path = Path(self._project_root) / "data" / "redsight.db"
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                cursor = conn.execute(
                    "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
                )
                row = cursor.fetchone()
                conn.close()
                if row:
                    return {
                        "plan_id": row[0],
                        "user_request": row[1],
                        "task_type": row[2],
                        "steps": row[3],  # JSON string
                        "created_at": row[4],
                        "status": row[5],
                    }
        except Exception as e:
            logger.debug(f"Could not load plan from DB: {e}")
        
        # Fall back to in-memory cache
        return self._plans.get(plan_id)
