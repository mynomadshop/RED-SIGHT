"""Optional cloud model providers behind a single governed registry."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx


class CloudProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


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


class OpenAIProvider(_BaseProvider):
    provider = CloudProvider.OPENAI
    base_url = "https://api.openai.com/v1"
    models = (
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
            "text-embedding-3-large",
            "Text Embedding 3 Large",
            provider,
            context_size=8_191,
            supports_streaming=False,
            supports_tools=False,
            is_embedding=True,
        ),
    )

    def _headers(self) -> dict[str, str]:
        return {**super()._headers(), "Authorization": f"Bearer {self.api_key}"}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[str] | str:
        payload = {"model": model_id or self.models[0].id, "messages": messages, **kwargs}
        response = await _maybe_await(self._get_client().post("/chat/completions", json=payload))
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        return _one_chunk(text) if stream else text


class AnthropicProvider(_BaseProvider):
    provider = CloudProvider.ANTHROPIC
    base_url = "https://api.anthropic.com/v1"
    models = (
        CloudModelInfo(
            "claude-sonnet-4-20250514",
            "Claude Sonnet 4",
            provider,
            context_size=200_000,
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
        chat_messages = [item for item in messages if item.get("role") != "system"]
        payload: dict[str, Any] = {
            "model": model_id or self.models[0].id,
            "messages": chat_messages,
            "max_tokens": kwargs.pop("max_tokens", None) or 1_024,
            **kwargs,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        response = await _maybe_await(self._get_client().post("/messages", json=payload))
        response.raise_for_status()
        blocks = response.json().get("content", [])
        text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict))
        return _one_chunk(text) if stream else text


class GoogleGeminiProvider(_BaseProvider):
    provider = CloudProvider.GOOGLE
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    models = (
        CloudModelInfo(
            "gemini-2.5-pro",
            "Gemini 2.5 Pro",
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

    def _health_path(self) -> str:
        return f"/models?key={self.api_key}"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[str] | str:
        model = model_id or self.models[0].id
        contents = [
            {
                "role": "model" if item.get("role") == "assistant" else "user",
                "parts": [{"text": str(item.get("content", ""))}],
            }
            for item in messages
            if item.get("role") != "system"
        ]
        payload: dict[str, Any] = {"contents": contents}
        if kwargs:
            payload["generationConfig"] = kwargs
        path = f"/models/{model}:generateContent?key={self.api_key}"
        response = await _maybe_await(self._get_client().post(path, json=payload))
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
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
        for provider in self._providers.values():
            await provider.close()
