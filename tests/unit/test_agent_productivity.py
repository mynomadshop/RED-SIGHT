"""Observable provider, skill and installation-regression contracts."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models.cloud_providers import OpenAIProvider, _BaseProvider
from app.models.provider_probe import probe_provider
from app.runtime_restart import owned_service
from app.skills.bundled import list_bundled_skills
from redsight_actions.agent_runtime import AgentRuntime
from redsight_actions.productivity import extract, merge, profile


def mock_provider(monkeypatch, handler):
    def client(provider):
        if provider._client is None:
            provider._client = httpx.AsyncClient(base_url=provider.base_url, headers=provider._headers(),
                                                transport=httpx.MockTransport(handler))
        return provider._client

    monkeypatch.setattr(_BaseProvider, "_get_client", client)


@pytest.mark.parametrize("slug", ["openai", "anthropic", "gemini", "xai", "openrouter", "groq",
                                  "mistral", "together", "deepseek", "cerebras", "custom", "lmstudio"])
@pytest.mark.asyncio
async def test_provider_probe_exercises_response_and_tool_round_trip(monkeypatch, slug):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        body = json.loads(request.content)
        if slug == "anthropic":
            assert request.headers["x-api-key"] == "test-key"
            if len(requests) == 2:
                return httpx.Response(200, json={"content": [
                    {"type": "tool_use", "id": "probe-1", "name": "redsight_probe", "input": {"value": "READY"}}]})
            assert body["messages"][-1]["content"][0]["tool_use_id"] == "probe-1"
            return httpx.Response(200, json={"content": [{"type": "text", "text": "READY"}]})
        if slug == "gemini":
            assert request.headers["x-goog-api-key"] == "test-key"
            assert str(request.url).endswith("/models/test-model:generateContent")
            if len(requests) == 2:
                parts = [{"functionCall": {"name": "redsight_probe", "args": {"value": "READY"}},
                          "thoughtSignature": "must-return-exactly"}]
            else:
                assert body["contents"][-2]["parts"][0]["thoughtSignature"] == "must-return-exactly"
                assert body["contents"][-1]["parts"][0]["functionResponse"]["name"] == "redsight_probe"
                parts = [{"text": "READY"}]
            return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})
        assert request.headers["Authorization"] == "Bearer test-key"
        assert str(request.url).endswith("/chat/completions")
        if len(requests) == 2:
            message = {"tool_calls": [{"id": "probe-1", "type": "function", "function": {
                "name": "redsight_probe", "arguments": '{"value":"READY"}'}}]}
        else:
            assert body["messages"][-1]["tool_call_id"] == "probe-1"
            message = {"content": "READY"}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    mock_provider(monkeypatch, handle)
    result = await probe_provider(slug, "test-key", "https://provider.test/v1", "test-model")
    assert result.ok and result.native_tools and len(requests) == 3, result
    assert result.models == ["test-model"]


@pytest.mark.asyncio
async def test_model_listing_is_not_a_successful_response_test(monkeypatch):
    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "a-model"}]})
        return httpx.Response(401, json={"error": "do not print secret-key"})

    mock_provider(monkeypatch, handle)
    result = await probe_provider("openai", "secret-key", "https://provider.test/v1", "a-model")
    assert not result.ok and "401" in result.message and "secret-key" not in result.message
    assert result.models == ["a-model"]


@pytest.mark.asyncio
async def test_custom_endpoint_without_models_or_tools_still_tests_real_chat(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404)
        body = json.loads(request.content)
        if body.get("tools"):
            return httpx.Response(422)
        return httpx.Response(200, json={"choices": [{"message": {"content": "READY"}}]})

    mock_provider(monkeypatch, handle)
    result = await probe_provider("custom", "", "http://localhost:1234/v1", "local")
    assert result.ok and result.native_tools is False and len(requests) == 3


@pytest.mark.asyncio
async def test_probe_does_not_accept_an_empty_completion(monkeypatch):
    mock_provider(monkeypatch, lambda request: httpx.Response(200, json={"data": [], "choices": []}))
    result = await probe_provider("groq", "key", "https://provider.test/v1", "test-model")
    assert not result.ok


@pytest.mark.asyncio
async def test_gemini_model_discovery_follows_pages_and_excludes_embeddings(monkeypatch):
    def handle(request):
        assert request.method == "GET"
        if request.url.params.get("pageToken"):
            return httpx.Response(200, json={"models": [{"name": "models/second", "supportedGenerationMethods": ["generateContent"]}]})
        return httpx.Response(200, json={"nextPageToken": "next", "models": [
            {"name": "models/first", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]})

    mock_provider(monkeypatch, handle)
    result = await probe_provider("gemini", "key", "https://provider.test/v1", "", test_response=False)
    assert result.ok and result.models == ["first", "second"] and result.native_tools is None


@pytest.mark.asyncio
async def test_openai_token_budget_uses_current_chat_parameter(monkeypatch):
    def handle(request):
        payload = json.loads(request.content)
        assert "max_tokens" not in payload and payload["max_completion_tokens"] == 2048
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    mock_provider(monkeypatch, handle)
    provider = OpenAIProvider(api_key="test")
    try:
        await provider.chat([{"role": "user", "content": "hi"}], model_id="gpt-5", max_tokens=2048)
    finally:
        await provider.close()


def validator(raw, *, write=False):
    return Path(raw)


def test_data_profile_and_merge_preserve_ids_count_duplicates_and_publish_atomically(tmp_path):
    a, b, output = (tmp_path / name for name in ("a.csv", "b.tsv", "out.csv"))
    a.write_text("id,name\n001,A\n002,\n001,A\n", encoding="utf-8")
    b.write_text("id\tname\n003\t=HYPERLINK(test)\n", encoding="utf-8")
    report = profile({"path": str(a)}, validator)
    assert report["rows_scanned"] == 3 and report["duplicate_rows"] == 1
    assert report["blank_cells"]["name"] == 1 and not report["truncated"]
    result = merge({"paths": [str(a), str(b)], "output_path": str(output), "deduplicate": True}, validator)
    assert result["output_rows"] == 3 and result["duplicates_removed"] == 1
    assert result["formula_like_cells_escaped"] == 1
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[1][0] == "001" and rows[3][1].startswith("'=")
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        merge({"paths": [str(a)], "output_path": str(output)}, validator)
    assert output.read_bytes() == original


def test_bad_schema_and_row_limit_never_publish_partial_merge(tmp_path):
    a, b, out = (tmp_path / name for name in ("a.csv", "b.csv", "out.csv"))
    a.write_text("id,name\n1,A\n2,B\n")
    b.write_text("name,id\nC,3\n")
    for params in ({"paths": [str(a), str(b)]}, {"paths": [str(a)], "max_rows": 1}):
        with pytest.raises(ValueError):
            merge({**params, "output_path": str(out)}, validator)
        assert not out.exists()
        assert set(tmp_path.iterdir()) == {a, b}


def test_merge_preserves_signed_numbers_and_escapes_formula_headers(tmp_path):
    source, output = tmp_path / "input.csv", tmp_path / "output.csv"
    source.write_text("=header,amount\n001,-12.50\n002,+2.5e-3\n003,-SUM(A1:A2)\n")
    result = merge({"paths": [str(source)], "output_path": str(output)}, validator)
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [["'=header", "amount"], ["001", "-12.50"], ["002", "+2.5e-3"], ["003", "'-SUM(A1:A2)"]]
    assert result["formula_like_cells_escaped"] == 2


def test_profile_limits_report_partial_coverage(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id,name\n1,A\n2,B\n")
    result = profile({"path": str(path), "max_rows": 1}, validator)
    assert result["rows_scanned"] == 1 and result["truncated"]


def test_xlsx_profiles_and_docx_extraction_use_real_files(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    docx = pytest.importorskip("docx")
    workbook = openpyxl.Workbook()
    workbook.active.append(["id", "calculation"])
    workbook.active.append(["0001", "=1+1"])
    sheet = tmp_path / "book.xlsx"
    workbook.save(sheet)
    report = profile({"path": str(sheet)}, validator)
    assert report["sample_rows"][0] == {"id": "0001", "calculation": "=1+1"}
    document = docx.Document()
    document.add_paragraph("Verified content")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Verified table"
    path = tmp_path / "report.docx"
    document.save(path)
    text = extract({"path": str(path)}, validator)["text"]
    assert "Verified content" in text and "Verified table" in text


def test_pdf_extraction_reports_pages_and_truncation(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        for text in ["FIRST PAGE", "SECOND PAGE"]:
            document.new_page().insert_text((72, 72), text)
        document.save(path)
    result = extract({"path": str(path), "max_pages": 1}, validator)
    assert result["pages"] == 2 and result["truncated"] and "FIRST PAGE" in result["text"]
    assert "SECOND PAGE" not in result["text"]


def test_bundled_skills_are_discoverable_and_self_contained():
    skills = list_bundled_skills()
    assert len(skills) >= 12
    assert len({skill["name"] for skill in skills}) == len(skills)
    assert all(skill["description"] and skill["example"] and Path(skill["path"]).is_file() for skill in skills)


@pytest.mark.asyncio
async def test_failed_read_recovers_from_observations_and_skips_old_dependents():
    specs = {"read": {"agent": True, "risk": "read", "description": "read", "params": "path:str"},
             "write": {"agent": True, "risk": "write", "description": "write", "params": ""}}
    calls = []

    async def execute(tool, params, **kwargs):
        calls.append((tool, params))
        return {"ok": params.get("path") == "found", "error": "Missing file"}

    async def chat(messages, **kwargs):
        if len(calls) == 1:
            assert "Missing file" in messages[-1]["content"] and "skipped" in messages[-1]["content"]
            return '{"steps":[{"tool":"read","params":{"path":"found"}}]}'
        return "Read the alternate source successfully."

    engine = AgentRuntime(chat=chat, execute=execute, tool_specs=lambda: specs,
                          allowed=lambda tool: tool in specs, requires_approval=lambda tool: tool == "write")
    result = await engine.run("read and act", [{"tool": "read", "params": {"path": "missing"}},
                                               {"tool": "write", "params": {}}], approved=True)
    assert result["ok"] and result["recovery_attempts"] == 1
    assert [tool for tool, _ in calls] == ["read", "read"]


@pytest.mark.asyncio
async def test_unresolved_failure_and_uncertain_write_are_never_successful():
    for risk in ("read", "write"):
        specs = {"operation": {"agent": True, "risk": risk, "description": "operation", "params": ""}}
        chat = AsyncMock(return_value="Done")
        engine = AgentRuntime(chat=chat, execute=AsyncMock(side_effect=OSError("secret detail")),
                              tool_specs=lambda specs=specs: specs, allowed=lambda tool, specs=specs: tool in specs,
                              requires_approval=lambda tool, risk=risk: risk == "write")
        result = await engine.run("act", [{"tool": "operation", "params": {}}], approved=True)
        assert not result["ok"] and len(result["results"]) == 1 and "secret detail" not in str(result)
        if risk == "write":
            chat.assert_not_awaited()


@pytest.mark.parametrize("change", ["none", "identity", "executable", "command"])
def test_restart_only_recognizes_this_installations_services(tmp_path, monkeypatch, change):
    from app.runtime_profile import instance_id

    health = {"pid": 123, "service": "redsight", "instance_id": instance_id(tmp_path)}
    if change == "identity":
        health["instance_id"] = "another-install"
    opener = SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(json.dumps(health).encode()))
    monkeypatch.setattr("app.runtime_restart.urllib.request.build_opener", lambda *args: opener)
    process = SimpleNamespace(
        exe=lambda: str(tmp_path / ("foreign/python.exe" if change == "executable" else ".venv-ui/Scripts/python.exe")),
        cmdline=lambda: ["python", "-m", "some.other.app" if change == "command" else "app.server:app"],
    )
    monkeypatch.setattr("app.runtime_restart.psutil.Process", lambda pid: process)
    assert (owned_service(tmp_path, 8000, "redsight") is process) == (change == "none")
