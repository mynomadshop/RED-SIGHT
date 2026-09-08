"""Regression tests for configuration, providers, and validation tooling."""

from __future__ import annotations

import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.chat import ChatRequest, _provider_chat, chat_completion
from app.api.routes.skills_tools import PermissionCheckRequest, ToolExecuteRequest
from app.config.settings import Settings
from app.core.interfaces import AuditAction, Capability, GpuInfo
from app.models.cloud_providers import (
    AnthropicProvider,
    CloudProvider,
    CloudProviderRegistry,
    CustomOpenAIProvider,
    GoogleGeminiProvider,
    XAIProvider,
)
from app.models.lmstudio import LmStudioProvider
from app.retrieval.embedding_loader import EmbeddingModelLoader
from app.retrieval.qdrant_client import QdrantClientWrapper
from app.security.audit import AuditLogger
from app.security.local_api import configure_local_api_security
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
from redsight_actions import mcp_native_stage111 as native_mcp
from redsight_actions.tool_planning import (
    build_agent_tool_schemas,
    decode_native_tool_steps,
)


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


def test_settings_cloud_providers_cover_xai_and_custom_endpoints():
    registry = CloudProviderRegistry()
    xai = XAIProvider(api_key="xai-key")
    custom = CustomOpenAIProvider(
        api_key="custom-key",
        base_url="https://models.example.test/v1/",
        model_id="private-model",
    )
    registry.register(xai)
    registry.register(custom)

    assert registry.get(CloudProvider.XAI) is xai
    assert registry.get(CloudProvider.CUSTOM) is custom
    assert xai._headers()["Authorization"] == "Bearer xai-key"
    assert custom.base_url == "https://models.example.test/v1"
    assert custom.list_models()[0].id == "private-model"
    assert "Authorization" not in CustomOpenAIProvider(
        api_key="",
        base_url="https://models.example.test/v1",
    )._headers()

    with pytest.raises(ValueError, match="http"):
        CustomOpenAIProvider(api_key="key", base_url="file:///tmp/provider")


def test_chat_route_allows_provider_free_startup_and_uses_saved_model(monkeypatch):
    fake_server = ModuleType("app.server")
    fake_server.get_chat_provider = lambda: (None, None, "none")
    monkeypatch.setitem(sys.modules, "app.server", fake_server)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(chat_completion({"messages": [{"role": "user", "content": "hello"}]}))
    assert exc_info.value.status_code == 503
    assert "Settings" in str(exc_info.value.detail)

    seen: dict[str, object] = {}

    class Provider:
        async def chat(self, **kwargs):
            seen.update(kwargs)
            return "configured response"

    fake_server.get_chat_provider = lambda: (Provider(), "saved-model", "openai")
    response = asyncio.run(
        chat_completion({"messages": [{"role": "user", "content": "hello"}]})
    )
    assert response["message"] == "configured response"
    assert response["model"] == "saved-model"
    assert seen["model_id"] == "saved-model"


def test_chat_request_accepts_standard_null_content_tool_call_turn():
    request = ChatRequest.model_validate(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "content": "ready", "tool_call_id": "call-1"},
            ]
        }
    )

    assert request.messages[0].content is None
    assert request.messages[1].tool_call_id == "call-1"


def test_optional_native_tools_fall_back_for_older_local_models():
    class Provider:
        def __init__(self):
            self.calls = []

        async def chat(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                request = httpx.Request("POST", "http://lm.test/v1/chat/completions")
                response = httpx.Response(400, request=request)
                upstream = httpx.HTTPStatusError("unsupported tools", request=request, response=response)
                raise RuntimeError("local model rejected tools") from upstream
            return '{"steps":[]}'

    provider = Provider()
    result = asyncio.run(
        _provider_chat(
            provider,
            {
                "messages": [{"role": "user", "content": "plan"}],
                "tools": [{"type": "function", "function": {"name": "read_file"}}],
                "tool_choice": "auto",
            },
        )
    )

    assert result == '{"steps":[]}'
    assert len(provider.calls) == 2
    assert "tools" in provider.calls[0]
    assert "tools" not in provider.calls[1]


def test_lmstudio_embedding_loader_batches_concurrently_and_preserves_order():
    calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={"data": [{"id": "chat-model"}, {"id": "nomic-embed-text"}]},
            )
        payload = json.loads(request.content)
        batch = payload["input"]
        calls.append(batch)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(value.removeprefix("t"))]}
                    for index, value in reversed(list(enumerate(batch)))
                ]
            },
        )

    async def exercise():
        loader = EmbeddingModelLoader(lmstudio_url="http://lm.test/v1")
        loader._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            assert await loader._load_lmstudio() is True
            return await loader.embed([f"t{index}" for index in range(25)])
        finally:
            await loader.close()

    vectors = asyncio.run(exercise())
    assert vectors == [[float(index)] for index in range(25)]
    assert sorted(map(len, calls)) == [5, 10, 10]


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


def test_local_api_requires_token_restricts_cors_and_bounds_requests(monkeypatch):
    monkeypatch.setenv("REDSIGHT_LOCAL_API_TOKEN", "test-local-token")
    app = FastAPI()
    configure_local_api_security(
        app,
        public_paths={"/health"},
        max_request_bytes=8,
    )

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/protected")
    async def protected():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.post("/protected").status_code == 401
    accepted = client.post(
        "/protected",
        headers={"X-RedSight-Token": "test-local-token", "Origin": "http://localhost:3000"},
    )
    assert accepted.status_code == 200
    assert accepted.headers["access-control-allow-origin"] == "http://localhost:3000"
    rejected_origin = client.post(
        "/protected",
        headers={"X-RedSight-Token": "test-local-token", "Origin": "https://attacker.invalid"},
    )
    assert "access-control-allow-origin" not in rejected_origin.headers
    oversized = client.post(
        "/protected",
        content=b"123456789",
        headers={"X-RedSight-Token": "test-local-token"},
    )
    assert oversized.status_code == 413


def test_native_mcp_stdio_lists_and_calls_tools(tmp_path):
    server = tmp_path / "fake_mcp.py"
    server.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if 'id' not in request:\n"
        "        continue\n"
        "    method = request.get('method')\n"
        "    if method == 'initialize':\n"
        "        result = {'protocolVersion': '2025-06-18', 'capabilities': "
        "{'tools': {}}, 'serverInfo': {'name': 'fixture', 'version': '1'}}\n"
        "    elif method == 'tools/list':\n"
        "        result = {'tools': [{'name': 'echo', 'description': 'Echo input', "
        "'inputSchema': {'type': 'object'}}]}\n"
        "    else:\n"
        "        params = request.get('params', {})\n"
        "        result = {'content': [{'type': 'text', 'text': "
        "str(params.get('arguments', {}).get('text', ''))}]}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], "
        "'result': result}), flush=True)\n",
        encoding="utf-8",
    )
    config = tmp_path / "mcp-native.json"
    config.write_text(
        json.dumps(
            {
                "mcp_servers": {
                    "fixture": {
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": [str(server)],
                        "env": {"PRIVATE_VALUE": "${MCP_FIXTURE_SECRET}"},
                        "timeout": 5,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    tested = asyncio.run(native_mcp.test_server("fixture", config_path=config))
    called = asyncio.run(
        native_mcp.call_tool(
            "fixture",
            "echo",
            {"text": "ready"},
            config_path=config,
        )
    )

    assert tested["tool_count"] == 1
    assert tested["tools"][0]["name"] == "echo"
    assert called["result"]["content"][0]["text"] == "ready"
    assert "env" not in native_mcp.sanitized_server_definitions(config)[0]


def test_native_agent_tool_schemas_and_calls_keep_governance():
    specs = {
        "filesystem.read": {
            "description": "Read one file",
            "params": "path:str, max_chars?:int<=50000",
            "agent": True,
        },
        "filesystem.write": {
            "description": "Write one file",
            "params": "path:str, content:str",
            "agent": True,
        },
        "system.hidden": {"description": "Hidden", "params": "", "agent": False},
    }
    schemas = build_agent_tool_schemas(specs)
    assert {item["function"]["name"] for item in schemas} == {
        "filesystem__read",
        "filesystem__write",
    }
    read_schema = next(
        item["function"]["parameters"]
        for item in schemas
        if item["function"]["name"] == "filesystem__read"
    )
    assert read_schema["required"] == ["path"]
    assert read_schema["properties"]["max_chars"]["maximum"] == 50_000

    raw = json.dumps(
        {
            "content": "Read the requested file.",
            "tool_calls": [
                {
                    "function": {
                        "name": "filesystem__read",
                        "arguments": json.dumps({"path": "C:/notes.txt"}),
                    }
                },
                {"function": {"name": "invented__tool", "arguments": "{}"}},
            ],
        }
    )
    decoded = decode_native_tool_steps(
        raw,
        specs,
        agent_allowed=lambda name: name in specs and bool(specs[name]["agent"]),
        requires_approval=lambda name: name.endswith("write"),
    )
    assert decoded is not None
    steps, summary = decoded
    assert summary == "Read the requested file."
    assert steps == [
        {
            "tool": "filesystem.read",
            "params": {"path": "C:/notes.txt"},
            "reason": "Selected through native provider tool calling.",
            "requires_approval": False,
        }
    ]


def test_native_provider_tool_payloads_are_translated():
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if "anthropic" in request.url.host:
            captured["anthropic"] = payload
            return httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "text", "text": "checking"},
                        {"type": "tool_use", "id": "call-1", "name": "lookup", "input": {"q": "x"}}
                    ]
                },
            )
        assert request.headers["x-goog-api-key"] == "key"
        assert "key" not in request.url.params
        captured["gemini"] = payload
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [
                        {"text": "checking"},
                        {"functionCall": {"name": "lookup", "args": {"q": "x"}}},
                    ]}}
                ]
            },
        )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up data",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
        }
    ]

    async def exercise():
        anthropic = AnthropicProvider(api_key="key", base_url="https://anthropic.test/v1")
        gemini = GoogleGeminiProvider(api_key="key", base_url="https://gemini.test/v1beta")
        anthropic._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=anthropic.base_url
        )
        gemini._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=gemini.base_url,
            headers=gemini._headers(),
        )
        try:
            anthropic_result = await anthropic.chat(
                [{"role": "user", "content": "use a tool"}],
                tools=tools,
                tool_choice="required",
                max_tokens=200,
            )
            gemini_result = await gemini.chat(
                [{"role": "user", "content": "use a tool"}],
                tools=tools,
                tool_choice="required",
                max_tokens=200,
                temperature=0.2,
            )
        finally:
            await anthropic.close()
            await gemini.close()
        return anthropic_result, gemini_result

    anthropic_result, gemini_result = asyncio.run(exercise())
    anthropic_message = json.loads(anthropic_result)
    assert anthropic_message["content"] == "checking"
    assert anthropic_message["tool_calls"][0]["function"]["name"] == "lookup"
    assert captured["anthropic"]["tools"][0]["input_schema"]["type"] == "object"
    assert captured["anthropic"]["tool_choice"] == {"type": "any"}
    gemini_message = json.loads(gemini_result)
    assert gemini_message["content"] == "checking"
    assert gemini_message["tool_calls"][0]["function"]["name"] == "lookup"
    assert captured["gemini"]["generationConfig"] == {
        "temperature": 0.2,
        "maxOutputTokens": 200,
    }
    assert captured["gemini"]["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
