"""Exercise native startup and real, dependent tool execution without paid APIs."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agents.coordinator import CoordinatorAgent
from app.models.cloud_providers import AnthropicProvider, GoogleGeminiProvider, OpenAIProvider
from app.models.provider_settings import SavedProviderSelection, provider_from_environment
from app.orchestration.multi_agent import AgentRole, MultiAgentOrchestrator
from app.runtime_profile import build_profile, resource_budget, select_port
from redsight_actions.agent_runtime import AgentRuntime

SPECS = {
    "files.find": {"agent": True, "description": "Find file", "params": "query:str"},
    "files.read": {"agent": True, "description": "Read file", "params": "path:str"},
    "files.write": {"agent": True, "description": "Write file", "params": "path:str, content:str"},
    "skills.read": {"agent": True, "description": "Read guidance", "params": "skill:str"},
}


def runtime(chat, execute, **kwargs):
    return AgentRuntime(chat=chat, execute=execute, tool_specs=lambda: SPECS,
                        allowed=lambda tool: tool in SPECS,
                        requires_approval=lambda tool: tool == "files.write", **kwargs)


def call(tool, **arguments):
    return json.dumps({"tool_calls": [{"id": "call_test", "type": "function",
                                       "function": {"name": tool.replace(".", "__"),
                                                    "arguments": json.dumps(arguments)}}]})


@pytest.mark.parametrize(("cpus", "memory", "workers", "jobs"), [
    (2, 2, 1, 1), (8, 3, 2, 1), (8, 6, 4, 2), (32, 32, 8, 4), (0, 0, 1, 1),
])
def test_budget_leaves_foreground_capacity(cpus, memory, workers, jobs):
    profile = resource_budget(cpus, memory)
    assert profile["worker_threads"] == workers
    assert profile["concurrent_jobs"] == jobs


def test_occupied_ports_get_distinct_alternatives(tmp_path, monkeypatch):
    monkeypatch.setattr("app.runtime_profile.service_matches", lambda *args: False)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        result = build_profile(tmp_path, tmp_path / "state.json", port, port)
        assert len({port, result["backend_port"], result["gateway_port"]}) == 3
        assert result["environment"]["REDSIGHT_GATEWAY_URL"].endswith(str(result["gateway_port"]))


def test_reuses_only_matching_installation_service(monkeypatch):
    monkeypatch.setattr("app.runtime_profile.port_available", lambda port: port != 8000)
    monkeypatch.setattr("app.runtime_profile.service_matches", lambda port, service, identity: identity == "ours")
    assert select_port(8000, "redsight", "ours", set()) == 8000
    assert select_port(8000, "redsight", "another", set()) == 8001


@pytest.mark.asyncio
async def test_find_read_then_write_uses_actual_results_and_resumes_once(tmp_path):
    source = tmp_path / "unpredictable-filename.txt"
    source.write_text("actual payload")
    target = tmp_path / "result.txt"
    executed = []

    async def execute(tool, params, **kwargs):
        executed.append(tool)
        if tool == "files.find":
            return {"ok": True, "path": str(source)}
        if tool == "files.read":
            return {"ok": True, "content": Path(params["path"]).read_text()}
        assert kwargs["approved"] is True
        Path(params["path"]).write_text(params["content"])
        return {"ok": True, "path": params["path"]}

    async def chat(messages, **kwargs):
        observation = messages[-1]
        if observation["role"] == "user":
            assert str(source) in observation["content"]
            return call("files.read", path=str(source))
        assert observation["role"] == "tool"
        if observation["name"] == "files__read":
            assert "actual payload" in observation["content"]
            return call("files.write", path=str(target), content="actual payload")
        return "Wrote the verified payload to result.txt."

    engine = runtime(chat, execute, concurrency=1)
    result = await engine.run("Find and copy", [{"tool": "files.find", "params": {"query": "source"}}])
    assert result["requires_approval"] and not target.exists()
    assert executed == ["files.find", "files.read"]
    resumed = await engine.run(result["goal"], result["plan"], run_id=result["run_id"], approved=True)
    assert resumed["ok"] and target.read_text() == "actual payload"
    assert executed == ["files.find", "files.read", "files.write"]
    assert not (await engine.run(result["goal"], result["plan"], run_id=result["run_id"], approved=True))["ok"]


@pytest.mark.asyncio
async def test_approval_is_scoped_to_exact_reviewed_mutation():
    execute = AsyncMock(return_value={"ok": True})
    engine = runtime(AsyncMock(return_value=call("files.write", path="new", content="new")), execute)
    result = await engine.run("write two files", [{"tool": "files.write", "params": {"path": "old", "content": "old"}}], approved=True)
    assert result["requires_approval"] and execute.await_count == 1
    altered = [{"tool": "files.write", "params": {"path": "altered"}}]
    rejected = await engine.run(result["goal"], altered, run_id=result["run_id"], approved=True)
    assert not rejected["ok"] and execute.await_count == 1


@pytest.mark.asyncio
async def test_tool_failure_never_reports_success_or_runs_dependents():
    execute = AsyncMock(return_value={"ok": False, "error": "File unavailable"})
    chat = AsyncMock()
    result = await runtime(chat, execute).run("inspect", [
        {"tool": "files.find", "params": {}}, {"tool": "files.read", "params": {}},
    ])
    assert not result["ok"] and len(result["results"]) == 1
    assert execute.await_count == 1 and chat.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    '{"tool_calls":[{"function":{"name":"files__read","arguments":"INVALID"}}]}',
    '{"tool_calls":[{"function":{"name":"system__hidden","arguments":"{}"}}]}',
    '{"steps": [{"tool": "not.a.tool", "params": {}}]}',
    '{"steps": INVALID}',
    '',
])
async def test_invalid_provider_actions_fail_closed(raw):
    execute = AsyncMock()
    result = await runtime(AsyncMock(return_value=raw), execute).run("task", [])
    assert not result["ok"] and execute.await_count == 0


@pytest.mark.asyncio
async def test_step_budget_stops_without_false_completion():
    execute = AsyncMock(return_value={"ok": True})
    result = await runtime(AsyncMock(return_value=call("files.find", query="again")), execute,
                           max_steps=2).run("task", [])
    assert not result["ok"] and execute.await_count == 2


@pytest.mark.asyncio
async def test_skill_guidance_is_available_to_dependent_actions():
    async def chat(messages, **kwargs):
        assert "Follow these report steps" in messages[0]["content"]
        return "Completed using the skill and recorded result."

    result = await runtime(chat, AsyncMock(return_value={"ok": True})).run(
        "report", [{"tool": "files.read", "params": {"path": "source"}}],
        guidance="Follow these report steps", exclude={"skills.execute", "skills.invoke"},
        metadata={"skill": "reporting"},
    )
    assert result["ok"] and result["skill"] == "reporting"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_class", [GoogleGeminiProvider, AnthropicProvider, OpenAIProvider])
async def test_native_provider_round_trip_preserves_opaque_history(provider_class):
    captured = []
    google_parts = [{"functionCall": {"name": "files__read", "args": {"path": "source"}},
                     "thoughtSignature": "opaque-signature-exact"}]
    anthropic_blocks = [{"type": "thinking", "thinking": "opaque", "signature": "signed"},
                        {"type": "tool_use", "id": "call_a", "name": "files__read", "input": {"path": "source"}}]

    def handle(request):
        captured.append(json.loads(request.content))
        if provider_class is GoogleGeminiProvider:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": google_parts}}]})
        if provider_class is AnthropicProvider:
            return httpx.Response(200, json={"content": anthropic_blocks})
        return httpx.Response(200, json={"choices": [{"message": {
            "tool_calls": [{"id": "call_a", "type": "function", "function": {
                "name": "files__read", "arguments": '{"path":"source"}'}}],
            "reasoning_content": "reasoning continuation", "content": None,
        }}]})

    provider = provider_class(api_key="test-key")
    provider._client = httpx.AsyncClient(base_url=provider.base_url, transport=httpx.MockTransport(handle))
    try:
        raw = await provider.chat([{"role": "user", "content": "read"}])
        reply = json.loads(raw)
        reply["role"] = "assistant"
        reply["tool_calls"][0].setdefault("id", "call_a")
        await provider.chat([{"role": "user", "content": "read"}, reply,
                             {"role": "tool", "tool_call_id": "call_a", "name": "files__read", "content": "actual file content"}])
        sent = captured[1]
        if provider_class is GoogleGeminiProvider:
            assert sent["contents"][1]["parts"] == google_parts
            assert sent["contents"][2]["parts"][0]["functionResponse"]["name"] == "files__read"
        elif provider_class is AnthropicProvider:
            assert sent["messages"][1]["content"] == anthropic_blocks
            assert sent["messages"][2]["content"][0]["tool_use_id"] == "call_a"
        else:
            assert sent["messages"][1]["reasoning_content"] == "reasoning continuation"
    finally:
        await provider.close()


@pytest.mark.parametrize("slug", ["openai", "anthropic", "gemini", "xai", "openrouter", "groq",
                                  "mistral", "together", "deepseek", "cerebras", "custom"])
def test_every_configured_provider_constructs_without_optional_sdks(slug):
    key_name = "GOOGLE_API_KEY" if slug == "gemini" else f"{slug.upper()}_API_KEY"
    if slug == "custom":
        key_name = "REDSIGHT_CUSTOM_API_KEY"
    provider, model, active = provider_from_environment({
        "REDSIGHT_ACTIVE_PROVIDER": slug, "REDSIGHT_PROVIDER_MODEL": "user-model",
        key_name: "test-key", f"REDSIGHT_{slug.upper()}_BASE_URL": "https://example.test/v1",
    })
    assert provider is not None and model == "user-model" and active == slug


@pytest.mark.asyncio
async def test_provider_key_save_and_remove_apply_without_restart(tmp_path, monkeypatch):
    config, secrets = tmp_path / "provider.json", tmp_path / "secrets.json"
    config.write_text("configured")
    secrets.write_text("first")
    values = {"REDSIGHT_ACTIVE_PROVIDER": "openai", "OPENAI_API_KEY": "first"}
    monkeypatch.setitem(sys.modules, "redsight_bootstrap", SimpleNamespace(
        PROVIDER_CONFIG_PATH=config, PROVIDER_SECRETS_PATH=secrets,
        provider_environment=lambda: dict(values),
    ))
    selection = SavedProviderSelection()
    first = selection.get()[0]
    values["OPENAI_API_KEY"] = "updated"
    secrets.write_text("updated-secret")
    assert selection.get()[0].api_key == "updated"
    assert selection.get()[0] is not first
    values.pop("OPENAI_API_KEY")
    secrets.write_text("removed-secret")
    assert selection.get()[0] is None
    await selection.close()


@pytest.mark.asyncio
async def test_multi_agent_passes_dependencies_and_does_not_replay_prior_runs():
    calls = []

    async def execute(description):
        calls.append(description)
        return {"ok": True, "response": "verified source fact"}

    engine = MultiAgentOrchestrator(executor=execute)
    engine.register_agent("researcher", AgentRole.RESEARCHER, [])
    tasks = [{"task_id": "a", "description": "research"},
             {"task_id": "b", "description": "summarize", "dependencies": ["a"]}]
    result = await engine.orchestrate("goal", ["researcher"], tasks)
    assert result.success and "verified source fact" in calls[1]
    await engine.orchestrate("new goal", ["researcher"], [{"description": "new task"}])
    assert len(calls) == 3
    assert all(task["status"] == "completed" for task in result.tasks)


@pytest.mark.asyncio
async def test_failed_dependency_blocks_downstream_agents():
    execute = AsyncMock(return_value={"ok": False, "error": "Provider unavailable"})
    engine = MultiAgentOrchestrator(executor=execute)
    engine.register_agent("r", AgentRole.RESEARCHER, [])
    result = await engine.orchestrate("goal", ["r"], [
        {"task_id": "a", "description": "first"},
        {"task_id": "b", "description": "second", "dependencies": ["a"]},
    ])
    assert not result.success and execute.await_count == 1
    assert "dependency failed" in result.tasks[1]["error"]


@pytest.mark.asyncio
async def test_coordinator_executes_actual_tool_and_propagates_failure():
    execute = AsyncMock(return_value={"ok": False, "error": "Cannot read"})
    coordinator = CoordinatorAgent(tool_executor=execute)
    task = await coordinator.create_task("read")
    await coordinator.plan_task(task, [])
    result = await coordinator.execute_step(task, {"tool_call": {"name": "files.read", "parameters": {"path": "missing"}}})
    assert result["status"] == "failed"
    execute.assert_awaited_once_with("files.read", {"path": "missing"})
