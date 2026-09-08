"""
RedSight - High-Performance Local AI Intelligence Platform
API Routes - Chat

Chat completion and streaming endpoints.
"""

import json
import logging
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    # Native tool-call assistant turns legitimately carry ``content: null``;
    # the following tool result supplies the content for that exchange.
    content: str | list[dict[str, Any]] | None = None
    name: str | None = Field(default=None, max_length=128)
    tool_call_id: str | None = Field(default=None, max_length=256)
    tool_calls: list[dict[str, Any]] | None = Field(default=None, max_length=128)

    @field_validator("content")
    @classmethod
    def content_is_bounded(
        cls, value: str | list[dict[str, Any]] | None
    ) -> str | list[dict[str, Any]] | None:
        if value is None:
            return value
        size = len(value) if isinstance(value, str) else len(json.dumps(value, ensure_ascii=False))
        if size > 250_000:
            raise ValueError("message content exceeds 250000 characters")
        return value


class FunctionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.-]+$")
    description: str = Field(default="", max_length=4_000)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})

    @field_validator("parameters")
    @classmethod
    def parameters_are_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False)) > 100_000:
            raise ValueError("tool schema exceeds 100000 characters")
        return value


class ChatTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["function"] = "function"
    function: FunctionDefinition


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    model: str | None = Field(default=None, max_length=300)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    tools: list[ChatTool] | None = Field(default=None, max_length=128)
    tool_choice: str | dict[str, Any] | None = None

    @field_validator("tool_choice")
    @classmethod
    def tool_choice_is_bounded(cls, value: str | dict[str, Any] | None):
        if value is None:
            return value
        if isinstance(value, str):
            if value not in {"auto", "none", "required"}:
                raise ValueError("tool_choice must be auto, none, required, or a named function")
        elif len(json.dumps(value, ensure_ascii=False)) > 10_000:
            raise ValueError("tool_choice exceeds 10000 characters")
        return value


def _provider_arguments(request: ChatRequest, configured_model: str | None) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "messages": [message.model_dump(exclude_none=True) for message in request.messages],
        "model_id": request.model or configured_model,
        "stream": request.stream,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    if request.tools:
        arguments["tools"] = [tool.model_dump() for tool in request.tools]
    if request.tool_choice is not None:
        arguments["tool_choice"] = request.tool_choice
    return arguments


def _upstream_status(exc: BaseException) -> int | None:
    """Recover a provider HTTP status through safe wrapper exceptions."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            return current.response.status_code
        current = current.__cause__ or current.__context__
    return None


async def _provider_chat(provider: Any, arguments: dict[str, Any]) -> Any:
    """Use native tools when supported, with an auto-mode compatibility fallback."""
    try:
        return await provider.chat(**arguments)
    except Exception as exc:
        if (
            arguments.get("tools")
            and arguments.get("tool_choice") in {None, "auto"}
            and _upstream_status(exc) in {400, 422}
        ):
            logger.info("Provider rejected optional native tools; retrying text-only planning")
            fallback = dict(arguments)
            fallback.pop("tools", None)
            fallback.pop("tool_choice", None)
            return await provider.chat(**fallback)
        raise


@router.post("/chat")
async def chat_completion(request: ChatRequest):
    """
    Chat completion endpoint.
    
    Accepts messages, model_id, and optional parameters.
    Returns streaming or non-streaming response.
    """
    from app.server import get_chat_provider

    provider, configured_model, provider_name = get_chat_provider()
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No AI provider is configured. Open Settings from the top toolbar "
                "and choose AI Provider."
                if provider_name == "none"
                else f"The selected AI provider ({provider_name}) has no usable credential. "
                "Open Settings and add or test its configuration."
            ),
        )
    
    if isinstance(request, dict):  # direct-call compatibility for internal tests/clients
        request = ChatRequest.model_validate(request)
    model_id = request.model or configured_model
    arguments = _provider_arguments(request, configured_model)
    
    try:
        if request.stream:
            # For streaming, we need to return an SSE response
            # This is a simplified version - production would use StreamingResponse
            response = await _provider_chat(provider, arguments)
            
            # Collect tokens for non-streaming response
            tokens = []
            async for token in response:
                tokens.append(token)
            
            return {
                "message": "".join(tokens),
                "model": model_id or "default",
                "stream": False,
            }
        else:
            response = await _provider_chat(provider, arguments)
            
            return {
                "message": response,
                "model": model_id or "default",
                "stream": False,
            }
            
    except Exception as exc:
        logger.exception("%s chat request failed", provider_name)
        raise HTTPException(
            status_code=502,
            detail=f"{provider_name} could not complete the request ({type(exc).__name__})",
        ) from exc


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Chat completion with Server-Sent Events streaming.
    
    Returns tokens as they arrive for real-time display.
    """
    from app.server import get_chat_provider

    provider, configured_model, provider_name = get_chat_provider()
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No AI provider is configured. Open Settings from the top toolbar "
                "and choose AI Provider."
                if provider_name == "none"
                else f"The selected AI provider ({provider_name}) has no usable credential. "
                "Open Settings and add or test its configuration."
            ),
        )
    
    if isinstance(request, dict):
        request = ChatRequest.model_validate({**request, "stream": True})
    else:
        request.stream = True
    model_id = request.model or configured_model
    try:
        response = await provider.chat(**_provider_arguments(request, configured_model))

        async def events():
            try:
                async for token in response:
                    yield "data: " + json.dumps({"token": token}, ensure_ascii=False) + "\n\n"
                yield "data: " + json.dumps({"done": True, "model": model_id or "default"}) + "\n\n"
            except Exception as exc:
                logger.exception("%s streaming chat failed", provider_name)
                yield "data: " + json.dumps(
                    {"error": f"{provider_name} stream failed ({type(exc).__name__})"}
                ) + "\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception as exc:
        logger.exception("%s streaming request could not start", provider_name)
        raise HTTPException(status_code=502, detail=f"{provider_name} stream could not start") from exc
