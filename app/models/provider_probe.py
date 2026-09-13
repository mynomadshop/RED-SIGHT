"""Exercise the same provider adapters used by chat, without touching saved keys."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

import httpx

from app.models.cloud_providers import CustomOpenAIProvider
from app.models.provider_settings import provider_from_environment


@dataclass
class ProbeResult:
    ok: bool = False
    message: str = ""
    models: list[str] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0
    native_tools: bool | None = None


PROBE_TOOL = {"type": "function", "function": {
    "name": "redsight_probe", "description": "Return the supplied connection-test value.",
    "parameters": {"type": "object", "properties": {"value": {"type": "string"}},
                   "required": ["value"]},
}}


def error_message(exc: Exception) -> str:
    # Never echo a response body, URL query, or exception containing an API key.
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        hint = {
            401: "Check the API key.", 403: "Check the key's model and project permissions.",
            404: "Check the model ID and base URL.", 429: "Check quota, billing, and rate limits.",
            400: "The model rejected the request. Check its supported API and parameters.",
            422: "The model rejected the request parameters.",
        }.get(code, "The provider is unavailable; try again later.")
        return f"Provider returned HTTP {code}. {hint}"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "The provider timed out. Check connectivity and model availability."
    if isinstance(exc, httpx.RequestError):
        return "Could not reach the provider. Check the endpoint and network connection."
    return f"Provider test failed ({type(exc).__name__}). Check the selected model and endpoint."


async def _discover(provider, slug: str) -> list[str]:
    models: list[str] = []
    params: dict = {}
    seen: set[str] = set()
    for _ in range(5):
        response = await provider._get_client().get("/models", params=params)
        response.raise_for_status()
        data = response.json()
        entries = data.get("data", data.get("models", []))
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            model = str(entry.get("id") or entry.get("name") or "").removeprefix("models/")
            methods = entry.get("supportedGenerationMethods", [])
            if model and (slug != "gemini" or not methods or "generateContent" in methods):
                models.append(model)
        token = data.get("nextPageToken") if slug == "gemini" else (
            data.get("last_id") if slug == "anthropic" and data.get("has_more") else None)
        if not token or str(token) in seen:
            break
        seen.add(str(token))
        params = {"pageToken" if slug == "gemini" else "after_id": token}
    return sorted(set(models))[:1000]


async def probe_provider(slug: str, api_key: str, base_url: str, model: str,
                         *, test_response: bool = True, timeout: float = 60) -> ProbeResult:
    result = ProbeResult(model=model.strip().removeprefix("models/") if slug == "gemini" else model.strip())
    if slug == "none":
        result.message = "Select an AI provider to test."
        return result
    if not api_key.strip() and slug not in {"custom", "lmstudio"}:
        result.message = "Enter an API key or keep the saved key for this provider."
        return result
    provider = None
    started = time.monotonic()
    try:
        if slug == "lmstudio":
            provider = CustomOpenAIProvider(api_key=api_key, base_url=base_url, model_id=result.model)
        else:
            key_name = "GOOGLE_API_KEY" if slug == "gemini" else f"{slug.upper()}_API_KEY"
            if slug == "custom":
                key_name = "REDSIGHT_CUSTOM_API_KEY"
            provider, _, _ = provider_from_environment({
                "REDSIGHT_ACTIVE_PROVIDER": slug, "REDSIGHT_PROVIDER_MODEL": result.model or "discover",
                key_name: api_key.strip(), f"REDSIGHT_{slug.upper()}_BASE_URL": base_url,
            })
        if provider is None:
            raise ValueError("Unknown provider")
        provider.timeout = min(timeout, 60)
        async with asyncio.timeout(timeout):
            try:
                result.models = await _discover(provider, slug)
            except httpx.HTTPStatusError as exc:
                # Some valid custom endpoints have no model-list API. Test the
                # exact model anyway; authentication failures must still stop.
                if not test_response or exc.response.status_code not in {403, 404, 405}:
                    raise
            if not test_response:
                result.ok = True
                result.message = f"Found {len(result.models)} models. Test a selected model to verify responses."
                return result
            if not result.model:
                result.message = "Choose a model from the list or enter its exact ID, then test again."
                return result
            messages = [{"role": "user", "content":
                         "Connection test: call redsight_probe with value READY, then reply READY."}]
            kwargs = {"model_id": result.model, "tools": [PROBE_TOOL], "tool_choice": "required"}
            try:
                raw = await provider.chat(messages, **kwargs)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {400, 404, 422}:
                    raise
                raw = await provider.chat([{"role": "user", "content": "Reply with the single word READY."}],
                                          model_id=result.model)
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = {}
            calls = parsed.get("tool_calls", []) if isinstance(parsed, dict) else []
            result.native_tools = bool(calls)
            if calls:
                if len(calls) != 1 or calls[0].get("function", {}).get("name") != "redsight_probe":
                    raise ValueError("Invalid probe tool call")
                call = calls[0]
                arguments = call["function"].get("arguments", "{}")
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if arguments != {"value": "READY"}:
                    raise ValueError("Invalid probe arguments")
                call["id"] = call.get("id") or "redsight_connection_test"
                messages.extend([{**parsed, "role": "assistant"},
                                 {"role": "tool", "tool_call_id": call["id"],
                                  "name": "redsight_probe", "content": '{"value":"READY"}'}])
                raw = await provider.chat(messages, model_id=result.model, tools=[PROBE_TOOL], tool_choice="none")
            if not isinstance(raw, str) or "READY" not in raw.strip().upper() or '"tool_calls"' in raw:
                raise ValueError("No usable completion from selected model")
            result.ok = True
            detail = "response and tool-result round trip passed" if result.native_tools else (
                "response passed; native tools were not verified (text-plan fallback is available)")
            result.message = f"{result.model}: {detail}."
    except Exception as exc:
        result.message = error_message(exc)
    finally:
        result.latency_ms = round((time.monotonic() - started) * 1000)
        if provider is not None:
            await provider.close()
    return result
