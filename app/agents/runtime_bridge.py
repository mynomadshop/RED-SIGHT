"""Run specialized agents through the same authenticated desktop action service."""

from __future__ import annotations

import os

import httpx

from app.security.local_api import auth_headers


async def execute_goal(goal: str) -> dict:
    async with httpx.AsyncClient(
        base_url=os.environ.get("REDSIGHT_GATEWAY_URL", "http://127.0.0.1:8765"),
        headers=auth_headers(), trust_env=False,
        timeout=httpx.Timeout(600, connect=3),
    ) as client:
        response = await client.post("/agent/plan", json={"goal": goal})
        response.raise_for_status()
        plan = response.json()
        if not plan.get("steps"):
            return {"ok": not bool(plan.get("error") or plan.get("raw")),
                    "response": plan.get("summary", ""), "plan": plan}
        response = await client.post("/agent/execute", json={
            "goal": goal, "plan": plan["steps"], "approved": False,
        })
        response.raise_for_status()
        return response.json()


async def execute_tool(name: str, parameters: dict) -> dict:
    async with httpx.AsyncClient(
        base_url=os.environ.get("REDSIGHT_GATEWAY_URL", "http://127.0.0.1:8765"),
        headers=auth_headers(), trust_env=False,
        timeout=httpx.Timeout(600, connect=3),
    ) as client:
        response = await client.post("/tool/execute", json={
            "tool": name, "params": parameters, "approved": False,
        })
        response.raise_for_status()
        return response.json()
