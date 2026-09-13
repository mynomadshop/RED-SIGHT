"""Exercise the full planner chain with skill discovery and native tool calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("gateway-state")))
        from redsight_actions import gateway_stage10

        yield gateway_stage10
        gateway_stage10.base.SCHEDULER.shutdown(wait=False)


@pytest.fixture
def planner(gateway, tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "DB_PATH", tmp_path / "memory.sqlite")
    gateway.init_db()
    # File-related catalog matches must remain available to the model, without
    # turning descriptions of optional capabilities into requested actions.
    monkeypatch.setattr(gateway.base, "load_skill_catalog", lambda: [{
        "Name": "File knowledge",
        "Description": "Read file contents, scan the entire system, index files, or research online.",
    }])
    provider = AsyncMock(return_value=json.dumps({"tool_calls": [{
        "id": "call_search", "type": "function", "function": {
            "name": "filesystem__search",
            "arguments": json.dumps({"root": str(tmp_path), "pattern": "input.txt"}),
        },
    }]}))
    monkeypatch.setattr(gateway.base, "redsight_chat", provider)
    return gateway, provider


@pytest.mark.asyncio
async def test_skill_descriptions_do_not_add_actions_to_file_copy(planner):
    gateway, provider = planner
    goal = r"Find input.txt in C:\RedSight Test\outputs, read it, and copy its contents to copied.txt."
    result = await gateway.base.agent_plan(gateway.base.AgentPlanRequest(goal=goal))
    assert result["ok"]
    assert [step["tool"] for step in result["steps"]] == ["filesystem.search"]
    messages = provider.call_args.args[0]
    assert messages[-1] == {"role": "user", "content": goal}
    assert "File knowledge" in messages[0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("goal", "expected"), [
    ("Learn from files in OneDrive", "rag.index"),
    ("Scan my files", "system.scan.full"),
    ("Research the latest information about files", "web.search"),
])
async def test_explicit_user_requests_keep_deterministic_actions(planner, goal, expected):
    gateway, _ = planner
    result = await gateway.base.create_agent_plan(goal)
    assert [step["tool"] for step in result["steps"]] == [expected, "filesystem.search"]


@pytest.mark.asyncio
async def test_continue_keeps_the_active_task_intent(planner):
    gateway, _ = planner
    sid = gateway.ensure_active_session()
    gateway.set_active_task("Learn from files in OneDrive", sid)
    result = await gateway.base.create_agent_plan("continue")
    assert result["steps"][0]["tool"] == "rag.index"
    assert result["steps"][0]["params"]["paths"] == ["onedrive"]
