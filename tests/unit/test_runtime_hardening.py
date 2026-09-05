"""Regression tests for configuration, providers, and validation tooling."""

from __future__ import annotations

import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.api.routes.skills_tools import PermissionCheckRequest, ToolExecuteRequest
from app.config.settings import Settings
from app.core.interfaces import AuditAction, Capability, GpuInfo
from app.models.lmstudio import LmStudioProvider
from app.retrieval.qdrant_client import QdrantClientWrapper
from app.security.audit import AuditLogger
from app.security.permissions import PermissionChecker, PermissionPolicy
from app.skills.sandbox import SkillSandbox
from app.tools.builtin import (
    ToolRegistry,
    _handle_get_env,
    _handle_list_directory,
    _handle_read_file,
    _handle_search_files,
    _handle_search_text,
)
from app.tools.contract import ToolContract
from app.tools.test_runner import TestRunner


def test_settings_accept_canonical_nested_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_SIGHT_PLATFORM__MODE", "local_only")
    monkeypatch.setenv("RED_SIGHT_PLATFORM__DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("RED_SIGHT_LMSTUDIO__BASE_URL", "http://localhost:4321/v1")
    monkeypatch.setenv("RED_SIGHT_RETRIEVAL__VECTOR_BACKEND_EMBEDDED", "true")
    monkeypatch.setenv("RED_SIGHT_ROUTING__VRAM_HEADROOM_GB_PER_GPU", "4.5")

    settings = Settings(_env_file=None)

    assert settings.platform.mode == "local_only"
    assert settings.data_root_path == tmp_path.resolve()
    assert settings.lmstudio.base_url == "http://localhost:4321/v1"
    assert settings.retrieval.vector_backend_embedded is True
    assert settings.routing.vram_headroom_gb_per_gpu == 4.5


def test_settings_keeps_legacy_launcher_environment_compatible(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_SIGHT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("VECTOR_BACKEND_EMBEDDED", "true")
    monkeypatch.setenv("GPU_VRAM_HEADROOM_GB", "2.5")
    monkeypatch.setenv("ENABLE_EMBEDDINGS", "yes")

    settings = Settings(_env_file=None)

    assert settings.data_root_path == tmp_path.resolve()
    assert settings.lmstudio.base_url == "http://localhost:1234/v1"
    assert settings.retrieval.vector_backend_url == "http://localhost:6333"
    assert settings.retrieval.vector_backend_embedded is True
    assert settings.retrieval.enable_embeddings is True
    assert settings.routing.vram_headroom_gb_per_gpu == 2.5


def test_canonical_environment_wins_over_legacy_alias(monkeypatch):
    monkeypatch.setenv("RED_SIGHT_MODE", "cloud_allowed")
    monkeypatch.setenv("RED_SIGHT_PLATFORM__MODE", "local_only")

    assert Settings(_env_file=None).platform.mode == "local_only"


def test_service_urls_reject_non_http_schemes_and_embedded_credentials(monkeypatch):
    monkeypatch.setenv("RED_SIGHT_LMSTUDIO__BASE_URL", "file:///tmp/models.json")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    monkeypatch.setenv("RED_SIGHT_LMSTUDIO__BASE_URL", "http://user:password@localhost:1234/v1")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_lmstudio_provider_chat_stream_embedding_and_rerank():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "nomic-embed-text", "max_context_length": 8192},
                        {"id": "qwen-coder-local", "max_context_length": 32768},
                    ]
                },
            )
        if request.url.path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            assert payload["model"] == "qwen-coder-local"
            if payload["stream"]:
                stream = (
                    'data: {"choices":[{"delta":{"content":"red"}}]}\n\n'
                    'data: {"choices":[{"delta":{"content":"sight"}}]}\n\n'
                    "data: [DONE]\n\n"
                )
                return httpx.Response(200, content=stream.encode())
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ready"}}]},
            )
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [3, 4]},
                        {"index": 0, "embedding": [1, 2]},
                    ]
                },
            )
        if request.url.path.endswith("/rerank"):
            return httpx.Response(
                200,
                json={"results": [{"index": 1, "relevance_score": 0.9}]},
            )
        return httpx.Response(404)

    async def exercise() -> None:
        provider = LmStudioProvider(base_url="http://lm.test/v1", timeout=1)
        provider.max_retries = 1
        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=provider.base_url,
        )
        try:
            assert await provider.health_check() is True
            models = await provider.list_models()
            assert Capability.EMBEDDING in models[0].capabilities
            assert Capability.CODING in models[1].capabilities

            assert await provider.chat([{"role": "user", "content": "status"}]) == "ready"
            stream = await provider.chat(
                [{"role": "user", "content": "stream"}],
                stream=True,
            )
            assert "".join([chunk async for chunk in stream]) == "redsight"
            assert await provider.embed(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]
            assert await provider.rerank("q", ["a", "b"]) == [0.0, 0.9]
        finally:
            await provider.close()

    asyncio.run(exercise())
    assert any(request.url.path.endswith("/chat/completions") for request in requests)


def test_qdrant_url_is_not_combined_with_host(monkeypatch):
    captured: list[dict] = []

    class FakeClient:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def get_collections(self):
            return SimpleNamespace(collections=[])

    fake_module = ModuleType("qdrant_client")
    fake_module.QdrantClient = FakeClient
    fake_module.models = SimpleNamespace(Distance=SimpleNamespace(COSINE="cosine"))
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)

    wrapper = QdrantClientWrapper(
        url="http://qdrant:6333",
        host="should-not-be-used",
        port=9999,
    )
    assert asyncio.run(wrapper.connect()) is True
    assert captured == [{"url": "http://qdrant:6333"}]


def test_gpu_info_serializes_used_memory_not_free_memory():
    info = GpuInfo(
        index=0,
        name="GPU",
        total_vram_mb=24_000,
        free_vram_mb=18_000,
        used_vram_mb=6_000,
        utilization_percent=50,
        temperature_c=60,
        process_count=2,
    )

    assert info.to_dict()["used_vram_mb"] == 6_000


def test_test_runner_reports_missing_and_rejects_pytest_options(monkeypatch):
    runner = TestRunner()
    missing = asyncio.run(runner.run_suite("missing"))
    assert missing.success is False
    assert missing.failed == 1
    assert "not found" in (missing.results[0].error or "")

    called = False

    def unexpected_run(*args, **kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.tools.test_runner.subprocess.run", unexpected_run)
    runner.register_suite("unsafe", ["--collect-only"])
    result = asyncio.run(runner.run_suite("unsafe"))

    assert called is False
    assert result.success is False
    assert result.failed == 1
    assert "non-option" in (result.results[0].error or "")


def test_test_runner_supports_synchronous_tool_registry_lookup(monkeypatch):
    import app.server as server

    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="echo",
            description="Echo text",
            schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        lambda params, contract: {"success": True, "text": params["text"]},
    )
    monkeypatch.setattr(server, "tool_registry", registry)

    result = asyncio.run(TestRunner().validate_tool("echo", {"text": "ready"}))

    assert result.success is True
    assert all(item.passed for item in result.results)


def test_test_runner_supports_asynchronous_tool_registry_lookup(monkeypatch):
    import app.server as server

    class AsyncLookupRegistry(ToolRegistry):
        async def get(self, tool_name):
            return super().get(tool_name)

    registry = AsyncLookupRegistry()
    registry.register(
        ToolContract(
            name="echo",
            description="Echo text",
            schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        lambda params, contract: {"success": True, "text": params["text"]},
    )
    monkeypatch.setattr(server, "tool_registry", registry)

    result = asyncio.run(TestRunner().validate_tool("echo", {"text": "ready"}))

    assert result.success is True


def test_tool_registry_does_not_trust_caller_supplied_permissions():
    policy = PermissionPolicy()
    policy.add_role("user", ["read_only"])
    registry = ToolRegistry(policy=policy)
    executed = False

    def destructive_handler(params, contract):
        nonlocal executed
        executed = True
        return {"success": True}

    registry.register(
        ToolContract(
            name="destructive_test",
            description="Must not execute",
            schema={"type": "object", "properties": {}},
            permissions=["destructive"],
            is_destructive=True,
        ),
        destructive_handler,
    )

    result = asyncio.run(
        registry.execute(
            "destructive_test",
            {},
            permissions=["destructive"],
            actor="user",
        )
    )

    assert result["success"] is False
    assert executed is False


def test_tool_registry_denies_omitted_required_permissions():
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="protected",
            description="Requires read permission",
            schema={"type": "object", "properties": {}},
            permissions=["read_only"],
        ),
        lambda params, contract: {"success": True},
    )

    result = asyncio.run(registry.execute("protected", {}))

    assert result["success"] is False


def test_environment_tool_never_returns_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("RED_SIGHT_PLATFORM__MODE", "local_only")

    all_values = _handle_get_env({}, None)
    secret_value = _handle_get_env({"name": "OPENAI_API_KEY"}, None)

    assert all_values["success"] is True
    assert "OPENAI_API_KEY" not in all_values["env"]
    assert all_values["env"]["RED_SIGHT_PLATFORM__MODE"] == "local_only"
    assert secret_value["success"] is False


def test_file_policy_normalizes_secret_paths_and_root_boundaries(tmp_path):
    allowed_root = tmp_path / "allowed"
    sibling = tmp_path / "allowed-other"
    allowed_root.mkdir()
    sibling.mkdir()
    safe_file = allowed_root / "notes.txt"
    secret_file = allowed_root / "nested" / ".." / ".env"

    policy = PermissionPolicy()
    policy.set_file_read_roots([str(allowed_root)])

    assert policy.is_file_read_allowed(str(safe_file)) is True
    assert policy.is_file_read_allowed(str(secret_file)) is False
    assert policy.is_file_read_allowed(str(allowed_root / "secrets")) is False
    assert policy.is_file_read_allowed(str(sibling / "notes.txt")) is False


def test_network_policy_rejects_hostname_prefix_bypass():
    policy = PermissionPolicy()
    policy.set_network_allow_domains(["localhost", "example.com"])

    assert policy.is_network_allowed("http://localhost:8000") is True
    assert policy.is_network_allowed("api.example.com") is True
    assert policy.is_network_allowed("localhost.attacker.invalid") is False
    assert policy.is_network_allowed("example.com.attacker.invalid") is False


def test_tool_registry_blocks_secret_file_reads(tmp_path):
    secret_file = tmp_path / ".env"
    secret_file.write_text("OPENAI_API_KEY=must-not-leak", encoding="utf-8")

    policy = PermissionPolicy()
    policy.add_role("user", ["read_only"])
    registry = ToolRegistry(policy=policy)
    registry.register(
        ToolContract(
            name="read_file",
            description="Read a file",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            permissions=["read_only"],
        ),
        _handle_read_file,
    )

    result = asyncio.run(
        registry.execute("read_file", {"path": str(secret_file)}, actor="user")
    )

    assert result["success"] is False
    assert "not allowed" in result["error"].lower()


def test_recursive_read_tools_filter_secret_files(tmp_path):
    (tmp_path / "public.txt").write_text("visible", encoding="utf-8")
    (tmp_path / ".env").write_text("must-not-leak", encoding="utf-8")
    (tmp_path / "credentials.json").write_text("must-not-leak", encoding="utf-8")

    listing = _handle_list_directory({"path": str(tmp_path)}, None)
    search = _handle_search_files({"path": str(tmp_path), "pattern": "*"}, None)
    content = _handle_search_text(
        {"path": str(tmp_path), "pattern": "must-not-leak"},
        None,
    )

    assert {entry["name"] for entry in listing["entries"]} == {"public.txt"}
    assert {item["path"] for item in search["matches"]} == {str(tmp_path / "public.txt")}
    assert content["matches"] == []


def test_permission_audit_records_round_trip_as_typed_events(tmp_path):
    audit_path = tmp_path / "audit" / "events.jsonl"
    audit = AuditLogger(log_path=str(audit_path))
    policy = PermissionPolicy()
    policy.add_role("user", ["read_only"])
    checker = PermissionChecker(policy, audit_logger=audit)

    result = asyncio.run(
        checker.check_tool_permission("user", "read_file", ["read_only"], {"path": "notes.txt"})
    )

    assert result["allowed"] is True
    reloaded = AuditLogger(log_path=str(audit_path))
    events = asyncio.run(reloaded.query(action=AuditAction.PERMISSION_CHECK))
    assert len(events) == 1
    assert events[0].action is AuditAction.PERMISSION_CHECK


def test_skill_sandbox_passes_json_as_data_and_redacts_audit(tmp_path, monkeypatch):
    module_path = tmp_path / "sandbox_fixture.py"
    module_path.write_text(
        "def run(enabled, missing, api_key):\n"
        "    return {'enabled': enabled, 'missing': missing, 'received': bool(api_key)}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    audit = AuditLogger()

    result = asyncio.run(
        SkillSandbox(audit_logger=audit).execute(
            "python:sandbox_fixture",
            {"enabled": True, "missing": None, "api_key": "must-not-leak"},
            actor="user",
        )
    )

    assert result.success is True
    assert result.output == {"enabled": True, "missing": None, "received": True}
    events = asyncio.run(audit.query(action=AuditAction.SKILL_EXECUTION))
    started = next(event for event in events if event.result == "started")
    assert started.details["inputs"]["api_key"] == "[REDACTED]"


def test_public_execution_models_reject_privileged_roles():
    with pytest.raises(ValidationError):
        ToolExecuteRequest(tool_name="read_file", role="admin")
    with pytest.raises(ValidationError):
        PermissionCheckRequest(tool_name="read_file", role="agent")
