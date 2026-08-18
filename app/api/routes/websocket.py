"""
RedSight - High-Performance Local AI Intelligence Platform
WebSocket API Routes

Provides WebSocket endpoints for real-time communication:
- /ws/chat — Streaming chat with token-by-token updates
- /ws/telemetry — Live GPU and system metrics
- /ws/agents — Multi-agent orchestration status
- /ws/alerts — Alert notifications
- /ws/broadcast — System-wide broadcast channel
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.hub import (
    WSMessageType, WSMessage, get_ws_hub,
    initialize_ws_hub, shutdown_ws_hub,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Global references set by server.py lifespan
lmstudio_provider: Any = None
cloud_providers: Any = None
multi_agent: Any = None
system_monitor: Any = None
memory_store: Any = None


def set_globals(
    lmstudio: Any = None,
    cloud: Any = None,
    multi_agent_obj: Any = None,
    monitor: Any = None,
    memory: Any = None,
):
    """Set global references from server.py."""
    global lmstudio_provider, cloud_providers, multi_agent, system_monitor, memory_store
    if lmstudio:
        lmstudio_provider = lmstudio
    if cloud:
        cloud_providers = cloud
    if multi_agent_obj:
        multi_agent = multi_agent_obj
    if monitor:
        system_monitor = monitor
    if memory:
        memory_store = memory


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for streaming chat responses.
    
    Clients send JSON with 'message' and optional 'model'/'provider'.
    Server sends token-by-token updates, then a 'done' message.
    """
    session_id = await get_ws_hub().connect(websocket)
    logger.info(f"Chat WebSocket connected: {session_id}")

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            model_id = data.get("model")
            provider = data.get("provider", "lmstudio")

            if not message:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": "No message provided"},
                })
                continue

            # Send start message
            await websocket.send_json({
                "type": "start",
                "data": {"session_id": session_id, "provider": provider},
            })

            try:
                # Get the appropriate provider
                if provider == "cloud":
                    provider_obj = cloud_providers
                else:
                    provider_obj = lmstudio_provider

                if not provider_obj:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "Provider not available"},
                    })
                    continue

                # Stream response
                if hasattr(provider_obj, 'chat') and asyncio.iscoroutinefunction(provider_obj.chat):
                    response = await provider_obj.chat(
                        messages=[{"role": "user", "content": message}],
                        model_id=model_id,
                        stream=True,
                    )

                    async for token in response:
                        await websocket.send_json({
                            "type": "token",
                            "data": {"token": token},
                        })

                await websocket.send_json({
                    "type": "done",
                    "data": {"session_id": session_id},
                })

                # Store in working memory
                if memory_store:
                    await memory_store.working.add(
                        f"[USER] {message}",
                        {"session_id": session_id, "role": "user"},
                    )

            except Exception as e:
                logger.error(f"Chat error: {e}")
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": str(e)},
                })

    except WebSocketDisconnect:
        logger.info(f"Chat WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"Chat WebSocket error: {e}")
    finally:
        await get_ws_hub().disconnect(session_id)


@router.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """
    WebSocket endpoint for live telemetry updates.
    
    Sends periodic GPU and system metrics.
    """
    session_id = await get_ws_hub().connect(websocket)
    logger.info(f"Telemetry WebSocket connected: {session_id}")

    try:
        while True:
            # Send current telemetry
            telemetry_data = {}

            if system_monitor:
                metrics = system_monitor.get_metrics()
                telemetry_data["system"] = metrics

            # Send as broadcast message
            message = WSMessage(
                type=WSMessageType.SYSTEM_STATUS,
                data=telemetry_data,
                session_id=session_id,
            )
            await get_ws_hub().send_to_session(session_id, message)

            # Wait for next update (1 second interval)
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        logger.info(f"Telemetry WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"Telemetry WebSocket error: {e}")
    finally:
        await get_ws_hub().disconnect(session_id)


@router.websocket("/ws/agents")
async def websocket_agents(websocket: WebSocket):
    """
    WebSocket endpoint for multi-agent orchestration status.
    
    Sends agent state updates during orchestration.
    """
    session_id = await get_ws_hub().connect(websocket)
    logger.info(f"Agent WebSocket connected: {session_id}")

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "start_orchestration":
                query = data.get("query", "")
                agents = data.get("agents", [])
                tasks = data.get("tasks", [])

                # Send start notification
                await websocket.send_json({
                    "type": "start",
                    "data": {"action": "orchestration", "query": query},
                })

                if multi_agent:
                    result = await multi_agent.orchestrate(
                        query=query,
                        agents=agents,
                        tasks=tasks,
                    )

                    await websocket.send_json({
                        "type": "result",
                        "data": {
                            "success": result.success,
                            "result": result.result,
                            "error": result.error,
                            "agent_count": result.agent_count,
                            "task_count": result.task_count,
                        },
                    })

            elif action == "get_status":
                status = multi_agent.get_agent_status() if multi_agent else []
                await websocket.send_json({
                    "type": "status",
                    "data": {"agents": status},
                })

            elif action == "get_history":
                history = multi_agent.get_orchestration_history() if multi_agent else []
                await websocket.send_json({
                    "type": "history",
                    "data": {"history": history},
                })

    except WebSocketDisconnect:
        logger.info(f"Agent WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"Agent WebSocket error: {e}")
    finally:
        await get_ws_hub().disconnect(session_id)


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """
    WebSocket endpoint for alert notifications.
    
    Receives real-time alert updates from the monitoring system.
    """
    session_id = await get_ws_hub().connect(websocket)
    logger.info(f"Alert WebSocket connected: {session_id}")

    # Subscribe to alerts channel
    get_ws_hub().subscribe(session_id, "alerts")

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "subscribe":
                channel = data.get("channel", "alerts")
                get_ws_hub().subscribe(session_id, channel)
                await websocket.send_json({
                    "type": "subscribed",
                    "data": {"channel": channel},
                })

            elif action == "unsubscribe":
                channel = data.get("channel", "alerts")
                get_ws_hub().unsubscribe(session_id, channel)
                await websocket.send_json({
                    "type": "unsubscribed",
                    "data": {"channel": channel},
                })

            elif action == "get_active":
                if system_monitor:
                    alerts = system_monitor.alert_manager.get_active_alerts()
                    await websocket.send_json({
                        "type": "active_alerts",
                        "data": {"alerts": alerts},
                    })

    except WebSocketDisconnect:
        logger.info(f"Alert WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"Alert WebSocket error: {e}")
    finally:
        get_ws_hub().unsubscribe(session_id, "alerts")
        await get_ws_hub().disconnect(session_id)


@router.websocket("/ws/broadcast")
async def websocket_broadcast(websocket: WebSocket):
    """
    WebSocket endpoint for system-wide broadcast channel.
    
    Receives all system events and can send messages to all clients.
    """
    session_id = await get_ws_hub().connect(websocket)
    logger.info(f"Broadcast WebSocket connected: {session_id}")

    # Subscribe to all channels
    get_ws_hub().subscribe(session_id, "system_status")
    get_ws_hub().subscribe(session_id, "gpu_status")
    get_ws_hub().subscribe(session_id, "alerts")
    get_ws_hub().subscribe(session_id, "plugin_event")

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "subscribe":
                channel = data.get("channel", "all")
                if channel == "all":
                    get_ws_hub().subscribe(session_id, "system_status")
                    get_ws_hub().subscribe(session_id, "gpu_status")
                    get_ws_hub().subscribe(session_id, "alerts")
                    get_ws_hub().subscribe(session_id, "plugin_event")
                else:
                    get_ws_hub().subscribe(session_id, channel)
                await websocket.send_json({
                    "type": "subscribed",
                    "data": {"channel": channel},
                })

            elif action == "send_message":
                message = data.get("message", "")
                # Broadcast to all other sessions
                broadcast_msg = WSMessage(
                    type=WSMessageType.BROADCAST,
                    data={"message": message, "from": session_id},
                )
                await get_ws_hub().broadcast(broadcast_msg, exclude_session=session_id)

    except WebSocketDisconnect:
        logger.info(f"Broadcast WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"Broadcast WebSocket error: {e}")
    finally:
        get_ws_hub().unsubscribe(session_id, "all")
        get_ws_hub().unsubscribe(session_id, "system_status")
        get_ws_hub().unsubscribe(session_id, "gpu_status")
        get_ws_hub().unsubscribe(session_id, "alerts")
        get_ws_hub().unsubscribe(session_id, "plugin_event")
        await get_ws_hub().disconnect(session_id)
