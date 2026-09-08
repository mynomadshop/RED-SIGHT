"""Optional cloud model providers behind a single governed registry."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import httpx


class CloudProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    XAI = "xai"
    OPENROUTER = "openrouter"
    GROQ = "groq"
    MISTRAL = "mistral"
    TOGETHER = "together"
    DEEPSEEK = "deepseek"
    CEREBRAS = "cerebras"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class CloudModelInfo:
    id: str
    name: str
    provider: CloudProvider
    context_size: int = 0
    supports_streaming: bool = True
    supports_tools: bool = True
    is_embedding: bool = False
    is_vision: bool = False
    is_reasoning: bool = False


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _one_chunk(text: str) -> AsyncIterator[str]:
    async def generate() -> AsyncIterator[str]:
        if text:
            yield text

    return generate()


class _BaseProvider:
    provider: CloudProvider
    base_url: str
    models: tuple[CloudModelInfo, ...] = ()

    def __init__(self, api_key: str, timeout: float = 180.0) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers=self._headers(),
                trust_env=False,
            )
        return self._client

    async def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            response = await _maybe_await(self._get_client().get(self._health_path()))
            return 200 <= int(response.status_code) < 300
        except Exception:
            return False

    def _health_path(self) -> str:
        return "/models"

    def list_models(self) -> list[CloudModelInfo]:
        return list(self.models)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _validated_base_url(value: str, label: str) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} base URL must use http:// or https://")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} base URL must not contain credentials")
    return endpoint


def _openai_message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        payload: dict[str, Any] = {"tool_calls": tool_calls}
        if isinstance(content, str) and content:
            payload["content"] = content
        return json.dumps(payload, ensure_ascii=False)
    return content if isinstance(content, str) else ""


class OpenAIProvider(_BaseProvider):
    provider = CloudProvider.OPENAI
    base_url = "https://api.openai.com/v1"
    models = (
        # Keep the shipped GPT-4o contract available to upgraded installs and
        # saved model selections while exposing the newer defaults below.
        CloudModelInfo(
            "gpt-4o",
            "GPT-4o",
            provider,
            context_size=128_000,
            is_vision=True,
            is_reasoning=True,
        ),
        CloudModelInfo(
            "gpt-4o-mini",
            "GPT-4o mini",
            provider,
            context_size=128_000,
            is_vision=True,
        ),
        CloudModelInfo(
            "gpt-5.6-terra",
            "GPT-5.6 Terra",
            provider,
            context_size=1_050_000,
            is_vision=True,
            is_reasoning=True,
        ),
        CloudModelInfo(
            "gpt-5.6-luna",
            "GPT-5.6 Luna",
            provider,
            context_size=1_050_000,
            is_vision=True,
        ),
        CloudModelInfo(
            "text-embedding-3-large",
            "Text Embedding 3 Large",
            provider,
            context_size=8_191,
            supports_streaming=False,
            supports_tools=False,
            is_embedding=True,
        ),
    )

    def __init__(
        self,
        api_key: str,
        timeout: float = 180.0,
        base_url: str | None = None,
        model_id: str = "",
    ) -> None:
        if base_url:
            self.base_url = _validated_base_url(base_url, self.provider.value)
        if model_id.strip():
            selected = model_id.strip()
            self.models = (CloudModelInfo(selected, selected, self.provider),)
        super().__init__(api_key=api_key, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {**super()._headers(), "Authorization": f"Bearer {self.api_key}"}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[str] | str:
        payload = {
            "model": model_id or self.models[0].id,
            "messages": messages,
            **{key: value for key, value in kwargs.items() if value is not None},
        }
        response = await _maybe_await(self._get_client().post("/chat/completions", json=payload))
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        text = _openai_message_text(choices[0].get("message")) if choices else ""
        return _one_chunk(text) if stream else text


class XAIProvider(OpenAIProvider):
    """xAI's OpenAI-compatible chat endpoint."""

    provider = CloudProvider.XAI
    base_url = "https://api.x.ai/v1"
    models = (
        CloudModelInfo(
            "grok-4.6",
            "Grok 4.6",
            provider,
            context_size=131_072,
            is_reasoning=True,
        ),
    )


class OpenAICompatibleProvider(OpenAIProvider):
    """Configurable adapter for providers implementing OpenAI chat semantics."""

    def __init__(
        self,
        *,
        provider: CloudProvider | str,
        api_key: str,
        base_url: str,
        model_id: str,
        timeout: float = 180.0,
    ) -> None:
        selected_provider = provider if isinstance(provider, CloudProvider) else CloudProvider(provider)
        if selected_provider in {CloudProvider.OPENAI, CloudProvider.ANTHROPIC, CloudProvider.GOOGLE}:
            raise ValueError(f"{selected_provider.value} requires its native adapter")
        self.provider = selected_provider
        self.base_url = _validated_base_url(base_url, selected_provider.value)
        selected_model = str(model_id or "").strip()
        if not selected_model:
            raise ValueError(f"A model is required for {selected_provider.value}")
        self.models = (CloudModelInfo(selected_model, selected_model, selected_provider),)
        _BaseProvider.__init__(self, api_key=api_key, timeout=timeout)


class CustomOpenAIProvider(OpenAICompatibleProvider):
    """A user-configured OpenAI-compatible endpoint."""

    provider = CloudProvider.CUSTOM

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_id: str = "",
        timeout: float = 180.0,
    ) -> None:
        super().__init__(
            provider=CloudProvider.CUSTOM,
            api_key=api_key,
            base_url=base_url,
            model_id=str(model_id or "default").strip(),
            timeout=timeout,
        )

    def _headers(self) -> dict[str, str]:
        headers = _BaseProvider._headers(self)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class AnthropicProvider(_BaseProvider):
    provider = CloudProvider.ANTHROPIC
    base_url = "https://api.anthropic.com/v1"
    models = (
        CloudModelInfo(
            "claude-sonnet-5",
            "Claude Sonnet 5",
            provider,
            context_size=1_000_000,
            is_vision=True,
            is_reasoning=True,
        ),
        CloudModelInfo(
            "claude-3-5-haiku-latest",
            "Claude 3.5 Haiku",
            provider,
            context_size=200_000,
            is_vision=True,
        ),
    )

    def __init__(
        self,
        api_key: str,
        timeout: float = 180.0,
        base_url: str | None = None,
        model_id: str = "",
    ) -> None:
        if base_url:
            self.base_url = _validated_base_url(base_url, "Anthropic")
        if model_id.strip():
            selected = model_id.strip()
            self.models = (CloudModelInfo(selected, selected, self.provider),)
        super().__init__(api_key=api_key, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            **super()._headers(),
            "anthropic-version": "2023-06-01",
            "x-api-key": self.api_key,
        }

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[str] | str:
        system_parts = [str(item.get("content", "")) for item in messages if item.get("role") == "system"]
        chat_messages: list[dict[str, Any]] = []

        def append_message(role: str, content: Any) -> None:
            if chat_messages and chat_messages[-1]["role"] == role:
                previous = chat_messages[-1]["content"]
                if isinstance(previous, str) and isinstance(content, str):
                    chat_messages[-1]["content"] = previous + "\n\n" + content
                    return
                previous_blocks = (
                    previous
                    if isinstance(previous, list)
                    else [{"type": "text", "text": str(previous)}]
                )
                new_blocks = (
                    content
                    if isinstance(content, list)
                    else [{"type": "text", "text": str(content)}]
                )
                chat_messages[-1]["content"] = [*previous_blocks, *new_blocks]
                return
            chat_messages.append({"role": role, "content": content})

        for item in messages:
            role = item.get("role")
            if role == "system":
                continue
            if role == "tool":
                append_message(
                    "user",
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(item.get("tool_call_id") or ""),
                            "content": str(item.get("content", "")),
                        }
                    ],
                )
                continue
            if role == "assistant" and isinstance(item.get("tool_calls"), list):
                blocks: list[dict[str, Any]] = []
                if item.get("content"):
                    blocks.append({"type": "text", "text": str(item["content"])})
                for call in item["tool_calls"]:
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        arguments = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": str(call.get("id") or ""),
                            "name": str(function.get("name") or ""),
                            "input": arguments,
                        }
                    )
                append_message("assistant", blocks)
                continue
            append_message(str(role), item.get("content", ""))
        tools = kwargs.pop("tools", None)
        tool_choice = kwargs.pop("tool_choice", None)
        selected_model = model_id or self.models[0].id
        if selected_model.startswith(("claude-sonnet-5", "claude-opus-5", "claude-fable-5")):
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)
            kwargs.pop("top_k", None)
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": chat_messages,
            "max_tokens": kwargs.pop("max_tokens", None) or 1_024,
            **{key: value for key, value in kwargs.items() if value is not None},
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools and tool_choice != "none":
            payload["tools"] = [
                {
                    "name": item.get("function", {}).get("name", ""),
                    "description": item.get("function", {}).get("description", ""),
                    "input_schema": item.get("function", {}).get("parameters", {"type": "object"}),
                }
                for item in tools
                if isinstance(item, dict) and item.get("type") == "function"
            ]
            if tool_choice == "auto":
                payload["tool_choice"] = {"type": "auto"}
            elif tool_choice == "required":
                payload["tool_choice"] = {"type": "any"}
            elif isinstance(tool_choice, dict):
                function = tool_choice.get("function", {})
                name = str(function.get("name") or "") if isinstance(function, dict) else ""
                if name:
                    payload["tool_choice"] = {"type": "tool", "name": name}
        response = await _maybe_await(self._get_client().post("/messages", json=payload))
        response.raise_for_status()
        blocks = response.json().get("content", [])
        text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict))
        tool_calls = [
            {
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                },
            }
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        if tool_calls:
            payload: dict[str, Any] = {"tool_calls": tool_calls}
            if text:
                payload["content"] = text
            text = json.dumps(payload, ensure_ascii=False)
        return _one_chunk(text) if stream else text


class GoogleGeminiProvider(_BaseProvider):
    provider = CloudProvider.GOOGLE
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    models = (
        CloudModelInfo(
            "gemini-3.8-flash",
            "Gemini 3.8 Flash",
            provider,
            context_size=1_048_576,
            is_vision=True,
            is_reasoning=True,
        ),
        CloudModelInfo(
            "gemini-2.5-flash",
            "Gemini 2.5 Flash",
            provider,
            context_size=1_048_576,
            is_vision=True,
        ),
    )

    def __init__(
        self,
        api_key: str,
        timeout: float = 180.0,
        base_url: str | None = None,
        model_id: str = "",
    ) -> None:
        if base_url:
            self.base_url = _validated_base_url(base_url, "Gemini")
        if model_id.strip():
            selected = model_id.strip()
            self.models = (CloudModelInfo(selected, selected, self.provider),)
        super().__init__(api_key=api_key, timeout=timeout)

    def _health_path(self) -> str:
        return "/models"

    def _headers(self) -> dict[str, str]:
        return {**super()._headers(), "x-goog-api-key": self.api_key}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[str] | str:
        model = model_id or self.models[0].id
        system_parts = [str(item.get("content", "")) for item in messages if item.get("role") == "system"]
        contents: list[dict[str, Any]] = []

        def append_content(role: str, parts: list[dict[str, Any]]) -> None:
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": role, "parts": parts})

        for item in messages:
            role = item.get("role")
            if role == "system":
                continue
            if role == "tool":
                append_content(
                    "user",
                    [
                        {
                            "functionResponse": {
                                "name": str(item.get("name") or "tool"),
                                "response": {"result": item.get("content", "")},
                            }
                        }
                    ],
                )
                continue
            parts: list[dict[str, Any]] = []
            if item.get("content"):
                parts.append({"text": str(item["content"])})
            if role == "assistant" and isinstance(item.get("tool_calls"), list):
                for call in item["tool_calls"]:
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        arguments = {}
                    parts.append(
                        {
                            "functionCall": {
                                "name": str(function.get("name") or ""),
                                "args": arguments,
                            }
                        }
                    )
            append_content(
                "model" if role == "assistant" else "user",
                parts or [{"text": ""}],
            )
        tools = kwargs.pop("tools", None)
        tool_choice = kwargs.pop("tool_choice", None)
        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if tools:
            declarations = [
                {
                    "name": item.get("function", {}).get("name", ""),
                    "description": item.get("function", {}).get("description", ""),
                    "parameters": item.get("function", {}).get("parameters", {"type": "object"}),
                }
                for item in tools
                if isinstance(item, dict) and item.get("type") == "function"
            ]
            if declarations:
                payload["tools"] = [{"functionDeclarations": declarations}]
                mode = {"required": "ANY", "none": "NONE"}.get(str(tool_choice), "AUTO")
                calling: dict[str, Any] = {"mode": mode}
                if isinstance(tool_choice, dict):
                    function = tool_choice.get("function", {})
                    name = str(function.get("name") or "") if isinstance(function, dict) else ""
                    if name:
                        calling = {"mode": "ANY", "allowedFunctionNames": [name]}
                payload["toolConfig"] = {"functionCallingConfig": calling}
        generation_config = {
            "temperature": kwargs.pop("temperature", None),
            "maxOutputTokens": kwargs.pop("max_tokens", None),
            **kwargs,
        }
        generation_config = {
            key: value for key, value in generation_config.items() if value is not None
        }
        if generation_config:
            payload["generationConfig"] = generation_config
        path = f"/models/{model}:generateContent"
        response = await _maybe_await(self._get_client().post(path, json=payload))
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        tool_calls = [
            {
                "type": "function",
                "function": {
                    "name": part.get("functionCall", {}).get("name", ""),
                    "arguments": json.dumps(
                        part.get("functionCall", {}).get("args", {}), ensure_ascii=False
                    ),
                },
            }
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("functionCall"), dict)
        ]
        if tool_calls:
            payload: dict[str, Any] = {"tool_calls": tool_calls}
            if text:
                payload["content"] = text
            text = json.dumps(payload, ensure_ascii=False)
        return _one_chunk(text) if stream else text


class CloudProviderRegistry:
    """Registered providers plus a stable model-to-provider lookup."""

    def __init__(self) -> None:
        self._providers: dict[CloudProvider, _BaseProvider] = {}
        self._custom_models: dict[str, CloudModelInfo] = {}

    def register(self, provider: _BaseProvider) -> None:
        self._providers[provider.provider] = provider

    def get(self, provider: CloudProvider | str) -> _BaseProvider | None:
        try:
            key = provider if isinstance(provider, CloudProvider) else CloudProvider(provider)
        except ValueError:
            return None
        return self._providers.get(key)

    def add_model(self, model: CloudModelInfo) -> None:
        self._custom_models[model.id] = model

    def list_models(self) -> list[CloudModelInfo]:
        models = {model.id: model for provider in self._providers.values() for model in provider.list_models()}
        models.update(self._custom_models)
        return list(models.values())

    def get_model(self, model_id: str) -> CloudModelInfo | None:
        return next((model for model in self.list_models() if model.id == model_id), None)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[str] | str:
        model = self.get_model(model_id) if model_id else next(iter(self.list_models()), None)
        if model is None:
            raise RuntimeError("No cloud model is registered")
        provider = self.get(model.provider)
        if provider is None:
            raise RuntimeError(f"Cloud provider is not registered for model {model.id}")
        return await provider.chat(messages, model.id, stream=stream, **kwargs)

    async def close(self) -> None:
        await asyncio.gather(*(provider.close() for provider in self._providers.values()))
