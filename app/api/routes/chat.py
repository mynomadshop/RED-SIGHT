"""
RedSight - High-Performance Local AI Intelligence Platform
API Routes - Chat

Chat completion and streaming endpoints.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/chat")
async def chat_completion(request: dict):
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
    
    messages = request.get("messages", [])
    model_id = request.get("model") or configured_model
    stream = request.get("stream", False)
    temperature = request.get("temperature", 0.7)
    max_tokens = request.get("max_tokens")
    
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    try:
        if stream:
            # For streaming, we need to return an SSE response
            # This is a simplified version - production would use StreamingResponse
            response = await provider.chat(
                messages=messages,
                model_id=model_id,
                stream=True,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            
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
            response = await provider.chat(
                messages=messages,
                model_id=model_id,
                stream=False,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            
            return {
                "message": response,
                "model": model_id or "default",
                "stream": False,
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(request: dict):
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
    
    messages = request.get("messages", [])
    model_id = request.get("model") or configured_model
    temperature = request.get("temperature", 0.7)
    
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    try:
        response = await provider.chat(
            messages=messages,
            model_id=model_id,
            stream=True,
            temperature=temperature,
        )
        
        # In production, this would return a StreamingResponse
        # For now, collect and return
        tokens = []
        async for token in response:
            tokens.append(token)
        
        return {
            "tokens": tokens,
            "message": "".join(tokens),
            "model": model_id or "default",
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
