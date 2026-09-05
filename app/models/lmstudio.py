"""Async client for LM Studio's OpenAI-compatible local API."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config.settings import get_settings
from app.core.interfaces import Capability, ModelInfo

logger = logging.getLogger(__name__)

_NON_CHAT_MARKERS = (
    "embed",
    "bge-",
    "gte-",
    "e5-",
    "minilm",
    "nomic-embed",
    "rerank",
    "clip",
)


class LmStudioProvider:
    """Local-first model provider with bounded retries and SSE streaming."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        settings = get_settings().lmstudio
        configured_url = base_url or settings.base_url
        self.base_url = configured_url.rstrip("/")
        self.timeout = float(timeout or settings.timeout_seconds)
        self.max_retries = max(1, int(settings.max_retries))
        self.retry_delay = max(0.0, float(settings.retry_delay_seconds))
        self._client: httpx.AsyncClient | None = None
        self._resolved_model = ""

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers={"Accept": "application/json"},
                trust_env=False,
            )
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self._get_client().request(method, path, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {
                    408,
                    409,
                    425,
                    429,
                    500,
                    502,
                    503,
                    504,
                }
                if not retryable or attempt + 1 >= self.max_retries:
                    break
                await asyncio.sleep(self.retry_delay * (2**attempt))
        raise RuntimeError(f"LM Studio request failed: {last_error}") from last_error

    async def health_check(self) -> bool:
        """Return whether LM Studio answers its model endpoint."""
        try:
            await self._request("GET", "/models")
            return True
        except Exception as exc:
            logger.debug("LM Studio health check failed: %s", exc)
            return False

    async def list_models(self) -> list[ModelInfo]:
        response = await self._request("GET", "/models")
        payload = response.json()
        items = payload.get("data", []) if isinstance(payload, dict) else []
        models: list[ModelInfo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or item.get("model") or "").strip()
            if not model_id:
                continue
            models.append(
                ModelInfo(
                    model_id=model_id,
                    name=str(item.get("name") or model_id),
                    capabilities=self._infer_capabilities(model_id),
                    context_size=self._positive_int(
                        item.get("max_context_length") or item.get("context_length"),
                        default=0,
                    ),
                    is_loaded=True,
                    backend="lmstudio",
                )
            )
        return models

    async def _resolve_model_id(self, requested: str | None = None) -> str:
        if requested and requested.strip():
            return requested.strip()
        if self._resolved_model:
            return self._resolved_model

        configured = str(get_settings().lmstudio.model_id or "").strip()
        if configured:
            self._resolved_model = configured
            return configured

        models = await self.list_models()
        chosen = next(
            (
                model.model_id
                for model in models
                if not any(marker in model.model_id.lower() for marker in _NON_CHAT_MARKERS)
            ),
            models[0].model_id if models else "",
        )
        if not chosen:
            raise RuntimeError("LM Studio is online but no model is loaded")
        self._resolved_model = chosen
        return chosen

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str] | str:
        if not messages:
            raise ValueError("messages must not be empty")

        payload: dict[str, Any] = {
            "model": await self._resolve_model_id(model_id),
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        payload.update({key: value for key, value in kwargs.items() if value is not None})

        if stream:
            return self._stream_chat(payload)

        response = await self._request("POST", "/chat/completions", json=payload)
        return self._extract_chat_text(response.json())

    async def _stream_chat(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        client = self._get_client()
        try:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug("Ignoring malformed LM Studio stream event")
                        continue
                    token = self._extract_stream_text(event)
                    if token:
                        yield token
        except (httpx.HTTPError, OSError) as exc:
            raise RuntimeError(f"LM Studio streaming request failed: {exc}") from exc

    async def embed(
        self,
        texts: list[str],
        model_id: str | None = None,
        **kwargs: Any,
    ) -> list[list[float]]:
        if not texts:
            return []
        model = model_id or get_settings().lmstudio.embedding_model_id
        if not model:
            models = await self.list_models()
            model = next(
                (m.model_id for m in models if Capability.EMBEDDING in m.capabilities),
                None,
            )
        if not model:
            raise RuntimeError("No LM Studio embedding model is configured or loaded")

        payload = {"model": model, "input": texts, **kwargs}
        response = await self._request("POST", "/embeddings", json=payload)
        data = response.json().get("data", [])
        ordered = sorted(
            (item for item in data if isinstance(item, dict)),
            key=lambda item: self._positive_int(item.get("index"), 0),
        )
        return [list(map(float, item.get("embedding", []))) for item in ordered]

    async def rerank(
        self,
        query: str,
        documents: list[str],
        model_id: str | None = None,
        **kwargs: Any,
    ) -> list[float]:
        if not documents:
            return []
        payload = {"model": model_id or "default", "query": query, "documents": documents, **kwargs}
        response = await self._request("POST", "/rerank", json=payload)
        results = response.json().get("results", [])
        scores = [0.0] * len(documents)
        for item in results:
            if not isinstance(item, dict):
                continue
            index = self._positive_int(item.get("index"), -1)
            if 0 <= index < len(scores):
                scores[index] = float(item.get("relevance_score", item.get("score", 0.0)))
        return scores

    async def get_capability(self, capability: Capability) -> ModelInfo | None:
        return next(
            (model for model in await self.list_models() if capability in model.capabilities),
            None,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError):
            return default
        return result if result >= 0 else default

    @staticmethod
    def _extract_chat_text(payload: Any) -> str:
        if not isinstance(payload, dict):
            raise RuntimeError("LM Studio returned an invalid chat response")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("LM Studio returned no chat completion")
        first = choices[0]
        message = first.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(first.get("text"), str):
            return first["text"]
        raise RuntimeError("LM Studio chat completion contained no text")

    @staticmethod
    def _extract_stream_text(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return ""
        first = choices[0]
        delta = first.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            return delta["content"]
        return first.get("text") if isinstance(first.get("text"), str) else ""

    @staticmethod
    def _infer_capabilities(model_id: str) -> list[Capability]:
        lowered = model_id.lower()
        if any(marker in lowered for marker in ("rerank", "cross-encoder")):
            return [Capability.RERANKER]
        if any(marker in lowered for marker in _NON_CHAT_MARKERS):
            return [Capability.EMBEDDING]
        capabilities = [Capability.FAST_CHAT, Capability.REASONING]
        if any(marker in lowered for marker in ("code", "coder", "qwen", "deepseek")):
            capabilities.append(Capability.CODING)
        if any(marker in lowered for marker in ("vision", "vl", "llava")):
            capabilities.append(Capability.VISION)
        return capabilities
