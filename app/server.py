"""
RedSight - High-Performance Local AI Intelligence Platform
FastAPI Application - Main Entry Point

Provides HTTP/WebSocket endpoints for the UI and external clients.
Initializes the full knowledge pipeline (Qdrant + SQLite + Embeddings).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.acceleration.gpu_telemetry import GpuTelemetry
from app.acceleration.gpu_scheduler import JobSchedulerImpl
from app.config.settings import get_settings
from app.models.lmstudio import LmStudioProvider
from app.retrieval.qdrant_client import QdrantClientWrapper
from app.retrieval.metadata_db import MetadataDB
from app.retrieval.embedding_loader import EmbeddingModelLoader
from app.retrieval.hybrid_search import HybridSearchEngine
from app.retrieval.source_viewer import SourceViewer
from app.api.routes.search import set_search_engine

if TYPE_CHECKING:
    from app.ingestion.indexer import Indexer
    from app.intelligence import ProjectIntelligence
    from app.learning import ControlledLearning
    from app.memory import MemoryStore
    from app.models.cloud_providers import CloudProviderRegistry
    from app.monitoring.system_monitor import SystemMonitor
    from app.orchestration.agent import AgentOrchestrator
    from app.orchestration.multi_agent import MultiAgentOrchestrator
    from app.plugins import PluginEventBus, PluginManager
    from app.retrieval.context_budgeter import ContextBudgeter
    from app.retrieval.reranker import CrossEncoderReranker
    from app.retrieval.sparse_retrieval import BM25Index
    from app.security.audit import AuditLogger
    from app.security.permissions import PermissionChecker
    from app.skills.discovery import SemanticSkillDiscovery
    from app.skills.registry import SkillRegistry
    from app.skills.sandbox import SkillSandbox
    from app.tools.builtin import ToolRegistry
    from app.websocket import WebSocketHub

logger = logging.getLogger(__name__)

# Global state
gpu_telemetry: Optional[GpuTelemetry] = None
lmstudio_provider: Optional[LmStudioProvider] = None
job_scheduler: Optional[JobSchedulerImpl] = None
qdrant: Optional[QdrantClientWrapper] = None
metadata_db: Optional[MetadataDB] = None
search_engine: Optional[HybridSearchEngine] = None
source_viewer: Optional[SourceViewer] = None

# Phase 3: Skills & Tools
skill_discovery: Optional["SemanticSkillDiscovery"] = None
skill_registry: Optional["SkillRegistry"] = None
tool_registry: Optional["ToolRegistry"] = None
sandbox: Optional["SkillSandbox"] = None
permission_checker: Optional["PermissionChecker"] = None
audit_logger: Optional["AuditLogger"] = None
agent_orchestrator: Optional["AgentOrchestrator"] = None

# Phase 4: Project Intelligence
project_intelligence: Optional["ProjectIntelligence"] = None
learning_engine: Optional["ControlledLearning"] = None
_indexer: Optional["Indexer"] = None
_bm25_index: Optional["BM25Index"] = None
_reranker: Optional["CrossEncoderReranker"] = None
_budgeter: Optional["ContextBudgeter"] = None

# Phase 8: Cloud providers & multi-agent
cloud_providers: Optional["CloudProviderRegistry"] = None
multi_agent_orchestrator: Optional["MultiAgentOrchestrator"] = None

# Phase 8: Monitoring
system_monitor: Optional["SystemMonitor"] = None

# Phase 9: WebSocket hub, memory, plugins
ws_hub: Optional["WebSocketHub"] = None
memory_store: Optional["MemoryStore"] = None
plugin_manager: Optional["PluginManager"] = None
event_bus: Optional["PluginEventBus"] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler — startup and shutdown."""
    global gpu_telemetry, lmstudio_provider, job_scheduler
    global qdrant, metadata_db, search_engine, source_viewer
    global learning_engine, project_intelligence
    global cloud_providers, multi_agent_orchestrator, system_monitor
    global ws_hub, memory_store, plugin_manager

    # Startup
    logger.info("RedSight starting up...")

    # Initialize GPU telemetry
    gpu_telemetry = GpuTelemetry()
    if gpu_telemetry.initialize():
        gpu_telemetry.start_polling()
        logger.info("GPU telemetry initialized")

    # Initialize LM Studio provider
    lmstudio_provider = LmStudioProvider()
    health = await lmstudio_provider.health_check()
    logger.info(f"LM Studio health: {'OK' if health else 'UNREACHABLE'}")

    # Initialize job scheduler
    job_scheduler = JobSchedulerImpl(gpu_telemetry=gpu_telemetry)
    from app.api.routes.gpu_scheduler import set_gpu_telemetry, set_job_scheduler

    set_gpu_telemetry(gpu_telemetry)
    set_job_scheduler(job_scheduler)
    
    # Phase 6: Controlled Learning
    from app.learning import ControlledLearning, SafetyBoundary
    safety = SafetyBoundary()
    learning_engine = ControlledLearning(
        safety_boundary=safety,
        working_memory=None,
        procedural_memory=None,
    )
    globals()["learning_engine"] = learning_engine
    from app.api.routes.controlled_learning import set_learning_engine

    set_learning_engine(learning_engine)
    logger.info("Controlled learning engine initialized")

    # ── Phase 1: Knowledge Pipeline ─────────────────────────────
    settings = get_settings()

    # 1. Qdrant
    logger.info("Initializing Qdrant...")
    embedded_path = (
        settings.retrieval.vector_backend_path
        or str(settings.data_root_path / "qdrant_db")
    )
    qdrant = QdrantClientWrapper(
        url=settings.retrieval.vector_backend_url,
        host=settings.retrieval.vector_backend_host,
        port=settings.retrieval.vector_backend_port,
        embedded=settings.retrieval.vector_backend_embedded,
        embedded_path=embedded_path,
    )
    if await qdrant.connect():
        await qdrant.ensure_collections()
        logger.info("Qdrant ready")
    else:
        logger.warning("Qdrant not available — search will be offline")

    # 2. SQLite metadata DB
    logger.info("Initializing metadata database...")
    metadata_db = MetadataDB(db_path=str(settings.data_root_path / "metadata.db"))
    if await metadata_db.init_db():
        logger.info("Metadata DB ready")
    else:
        logger.warning("Metadata DB not available")

    # 3. Embedding model
    embedding_model = None
    if settings.retrieval.enable_embeddings:
        logger.info("Loading embedding model...")
        loader = EmbeddingModelLoader(
            model_name=settings.retrieval.embedding_model or "sentence-transformers/all-MiniLM-L6-v2",
            lmstudio_url=settings.lmstudio.base_url or None,
        )
        if await loader.load():
            embedding_model = loader.model
            logger.info(f"Embedding model loaded: {loader.get_info()}")
        else:
            logger.warning("No embedding model available — indexing without vectors")

    # 4. Hybrid search engine
    search_engine = HybridSearchEngine(
        qdrant=qdrant,
        metadata_db=metadata_db,
        embedding_model=embedding_model,
    )
    set_search_engine(search_engine)
    logger.info("Hybrid search engine initialized")

    # 5. Source viewer
    source_viewer = SourceViewer(metadata_db=metadata_db)
    logger.info("Source viewer initialized")

    from app.ingestion.indexer import Indexer
    # 6. Indexer (for indexing jobs)
    from app.api.routes.sources import set_source_viewer as set_sources
    from app.api.routes.jobs import set_indexer as set_jobs_indexer
    from app.api.routes.search import set_bm25_index, set_reranker, set_budgeter
    from app.retrieval.sparse_retrieval import BM25Index
    from app.retrieval.reranker import CrossEncoderReranker
    from app.retrieval.context_budgeter import ContextBudgeter
    from app.retrieval.golden_set import GoldenSet
    from app.retrieval.golden_queries import create_golden_queries

    set_search_engine(search_engine)
    set_sources(source_viewer)
    # ── Phase 2: Hybrid RAG Components ────────────────────────────

    # 7. BM25 sparse index
    bm25_index = BM25Index(k1=1.5, b=0.75)
    set_bm25_index(bm25_index)
    logger.info("BM25 sparse index initialized")

    # 8. Cross-encoder reranker
    reranker = CrossEncoderReranker()
    await reranker.load()
    set_reranker(reranker)
    logger.info(f"Reranker initialized: {reranker.get_info()}")

    # 9. Context budgeter
    budgeter = ContextBudgeter(max_tokens=4096)
    set_budgeter(budgeter)
    logger.info("Context budgeter initialized")

    # 10. Golden evaluation set
    golden_set = create_golden_queries()
    logger.info(f"Golden evaluation set loaded: {len(golden_set.list_queries())} queries")

    # Create indexer with same dependencies
    indexer = Indexer(
        qdrant=qdrant,
        metadata_db=metadata_db,
        embedding_model=embedding_model,
        bm25_index=bm25_index,  # Feed BM25 for sparse indexing
    )
    set_jobs_indexer(indexer)

    logger.info("RedSight started successfully")

    # ── Phase 3: Skills & Tools ──────────────────────────────────

    # 11. Audit logger
    from app.security.audit import AuditLogger
    audit_logger = AuditLogger(log_path=str(settings.data_root_path / "audit.log"))
    globals()["audit_logger"] = audit_logger
    logger.info("Audit logger initialized")

    # 12. Permission policy & checker
    from app.security.permissions import PermissionPolicy, PermissionChecker
    policy = PermissionPolicy()
    # Define roles
    policy.add_role("admin", ["read_only", "read_write", "write_only", "destructive"])
    policy.add_role("agent", ["read_only", "read_write"])
    policy.add_role("user", ["read_only"])
    permission_checker = PermissionChecker(policy=policy, audit_logger=audit_logger)
    globals()["permission_checker"] = permission_checker
    logger.info("Permission system initialized")

    # 13. Skill discovery
    from app.skills.discovery import SemanticSkillDiscovery
    skill_discovery = SemanticSkillDiscovery()
    # Set embedding model if available
    if embedding_model:
        skill_discovery.set_embedding_model(embedding_model)
    globals()["skill_discovery"] = skill_discovery
    logger.info("Semantic skill discovery initialized")

    # 14. Skill registry
    from app.skills.registry import SkillRegistry
    skill_registry = SkillRegistry()
    globals()["skill_registry"] = skill_registry
    logger.info("Skill registry initialized")

    # 15. Tool registry with built-in tools
    from app.tools.builtin import (
        ToolRegistry as _BuiltinToolRegistry,
        _handle_read_file, _handle_write_file, _handle_list_directory,
        _handle_search_files, _handle_run_command, _handle_read_directory,
        _handle_get_file_info, _handle_list_processes, _handle_disk_usage,
        _handle_search_code, _handle_read_json, _handle_write_json,
        _handle_delete_file, _handle_copy_file, _handle_move_file,
        _handle_search_text, _handle_get_env, _handle_list_skills,
        _handle_list_tools,
    )
    from app.tools.contract import ToolContract
    tool_registry = _BuiltinToolRegistry(policy=policy, audit_logger=audit_logger)

    # Register built-in tools with contracts and handlers
    tools_to_register = [
        {
            "name": "read_file",
            "description": "Read the contents of a file from the filesystem",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read"},
                },
                "required": ["path"],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 30,
            "handler": _handle_read_file,
        },
        {
            "name": "write_file",
            "description": "Write content to a file on the filesystem",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            "permissions": ["read_write"],
            "timeout_seconds": 30,
            "handler": _handle_write_file,
        },
        {
            "name": "list_directory",
            "description": "List contents of a directory",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list"},
                },
                "required": ["path"],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 30,
            "handler": _handle_list_directory,
        },
        {
            "name": "search_files",
            "description": "Search for files by name pattern",
            "schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern to search for"},
                    "path": {"type": "string", "description": "Directory to search in"},
                },
                "required": ["pattern"],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 60,
            "handler": _handle_search_files,
        },
        {
            "name": "run_command",
            "description": "Execute a shell command",
            "schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                },
                "required": ["command"],
            },
            "permissions": ["read_write"],
            "timeout_seconds": 60,
            "handler": _handle_run_command,
        },
        {
            "name": "read_directory",
            "description": "Read all files in a directory tree",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to read"},
                },
                "required": ["path"],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 60,
            "handler": _handle_read_directory,
        },
        {
            "name": "get_file_info",
            "description": "Get metadata about a file (size, modified, etc.)",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                },
                "required": ["path"],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 30,
            "handler": _handle_get_file_info,
        },
        {
            "name": "list_processes",
            "description": "List running system processes",
            "schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 30,
            "handler": _handle_list_processes,
        },
        {
            "name": "disk_usage",
            "description": "Get disk usage information",
            "schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 30,
            "handler": _handle_disk_usage,
        },
        {
            "name": "search_code",
            "description": "Search for text patterns in code files",
            "schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text pattern to search for"},
                    "path": {"type": "string", "description": "Directory to search in"},
                    "file_types": {"type": "array", "items": {"type": "string"}, "description": "File extensions to search"},
                },
                "required": ["pattern"],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 60,
            "handler": _handle_search_code,
        },
        {
            "name": "read_json",
            "description": "Read and parse a JSON file",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the JSON file"},
                },
                "required": ["path"],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 30,
            "handler": _handle_read_json,
        },
        {
            "name": "write_json",
            "description": "Write data to a JSON file",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the JSON file"},
                    "data": {"type": "object", "description": "Data to write"},
                },
                "required": ["path", "data"],
            },
            "permissions": ["read_write"],
            "timeout_seconds": 30,
            "handler": _handle_write_json,
        },
        {
            "name": "delete_file",
            "description": "Delete a file from the filesystem",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to delete"},
                    "_confirmed": {"type": "boolean", "description": "Confirm deletion"},
                },
                "required": ["path", "_confirmed"],
            },
            "permissions": ["destructive"],
            "timeout_seconds": 30,
            "handler": _handle_delete_file,
            "requires_confirmation": True,
            "is_destructive": True,
        },
        {
            "name": "copy_file",
            "description": "Copy a file from source to destination",
            "schema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Source file path"},
                    "destination": {"type": "string", "description": "Destination file path"},
                },
                "required": ["source", "destination"],
            },
            "permissions": ["read_write"],
            "timeout_seconds": 60,
            "handler": _handle_copy_file,
        },
        {
            "name": "move_file",
            "description": "Move or rename a file",
            "schema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Source file path"},
                    "destination": {"type": "string", "description": "Destination file path"},
                },
                "required": ["source", "destination"],
            },
            "permissions": ["read_write"],
            "timeout_seconds": 60,
            "handler": _handle_move_file,
        },
        {
            "name": "search_text",
            "description": "Search for text patterns in file contents",
            "schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text pattern to search for"},
                    "path": {"type": "string", "description": "Directory or file to search in"},
                },
                "required": ["pattern"],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 60,
            "handler": _handle_search_text,
        },
        {
            "name": "get_env",
            "description": "Get environment variables",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Environment variable name (optional)"},
                },
                "required": [],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 10,
            "handler": _handle_get_env,
        },
        {
            "name": "list_skills",
            "description": "List all available skills",
            "schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 10,
            "handler": _handle_list_skills,
        },
        {
            "name": "list_tools",
            "description": "List all available tools",
            "schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "permissions": ["read_only"],
            "timeout_seconds": 10,
            "handler": _handle_list_tools,
        },
    ]

    for tool_def in tools_to_register:
        contract = ToolContract(
            name=tool_def["name"],
            description=tool_def["description"],
            schema=tool_def["schema"],
            permissions=tool_def["permissions"],
            timeout_seconds=tool_def["timeout_seconds"],
            requires_confirmation=tool_def.get("requires_confirmation", False),
            is_destructive=tool_def.get("is_destructive", False),
        )
        tool_registry.register(contract, tool_def["handler"])
    globals()["tool_registry"] = tool_registry
    logger.info(f"Tool registry initialized with {len(tools_to_register)} tools")

    # 16. Sandbox
    from app.skills.sandbox import SkillSandbox
    sandbox = SkillSandbox(
        default_timeout=300,
        max_memory_mb=1024,
        audit_logger=audit_logger,
        permission_checker=permission_checker,
    )
    globals()["sandbox"] = sandbox
    logger.info("Skill sandbox initialized")

    # 17. Agent orchestrator
    from app.orchestration.agent import AgentOrchestrator
    agent_orchestrator = AgentOrchestrator(
        skill_discovery=skill_discovery,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
        sandbox=sandbox,
        permission_checker=permission_checker,
        audit_logger=audit_logger,
    )
    globals()["agent_orchestrator"] = agent_orchestrator
    logger.info("Agent orchestrator initialized")

    # ── Phase 4: Project Intelligence ────────────────────────────

    # 18. Project Intelligence
    from app.intelligence import ProjectIntelligence
    pi = ProjectIntelligence()
    project_intelligence = pi
    globals()["project_intelligence"] = pi
    from app.api.routes.intelligence import set_project_intelligence

    set_project_intelligence(pi)
    logger.info("Project intelligence initialized")

    # ── Phase 8: Cloud Providers, Multi-Agent, Monitoring ────────────

    # 18. Cloud provider registry
    from app.models.cloud_providers import (
        CloudProviderRegistry, OpenAIProvider, AnthropicProvider, GoogleGeminiProvider,
    )
    cloud_registry = CloudProviderRegistry()
    if settings.is_cloud_allowed:
        configured_providers = (
            ("OpenAI", OpenAIProvider, os.getenv("OPENAI_API_KEY", "")),
            ("Anthropic", AnthropicProvider, os.getenv("ANTHROPIC_API_KEY", "")),
            (
                "Google",
                GoogleGeminiProvider,
                os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", ""),
            ),
        )
        for name, provider_type, api_key in configured_providers:
            if not api_key:
                logger.info("%s cloud provider is not configured", name)
                continue
            try:
                cloud_registry.register(provider_type(api_key=api_key))
            except Exception as exc:
                logger.warning("Failed to register %s provider: %s", name, exc)
    else:
        logger.info("Cloud providers disabled by local-first routing policy")
    cloud_providers = cloud_registry
    globals()["cloud_providers"] = cloud_providers
    logger.info(f"Cloud provider registry initialized with {len(cloud_registry.list_models())} models")

    # 19. Multi-agent orchestrator
    from app.orchestration.multi_agent import MultiAgentOrchestrator, AgentRole
    multi_agent = MultiAgentOrchestrator()
    multi_agent.register_agent("researcher-1", AgentRole.RESEARCHER, ["web_search", "analysis"])
    multi_agent.register_agent("coder-1", AgentRole.CODER, ["python", "javascript", "debugging"])
    multi_agent.register_agent("analyst-1", AgentRole.ANALYST, ["data_analysis", "reporting"])
    multi_agent.register_agent("writer-1", AgentRole.WRITER, ["content", "documentation"])
    multi_agent.register_agent("reviewer-1", AgentRole.REVIEWER, ["code_review", "quality"])
    multi_agent.register_agent("coordinator-1", AgentRole.COORDINATOR, ["routing", "delegation"])
    multi_agent_orchestrator = multi_agent
    globals()["multi_agent_orchestrator"] = multi_agent_orchestrator
    logger.info("Multi-agent orchestrator initialized with 6 agent roles")

    # 20. System monitor
    from app.monitoring.system_monitor import SystemMonitor
    sys_monitor = SystemMonitor()
    def check_qdrant():
        if qdrant and qdrant.is_connected:
            return ("healthy", True, "Qdrant connected")
        return ("unhealthy", False, "Qdrant not connected")
    def check_embedding():
        if embedding_model:
            return ("healthy", True, "Embedding model loaded")
        return ("degraded", True, "No embedding model")
    def check_lmstudio():
        if health:
            return ("healthy", True, "LM Studio reachable")
        return ("unhealthy", False, "LM Studio not reachable")
    sys_monitor.add_health_check("qdrant", check_qdrant)
    sys_monitor.add_health_check("embedding", check_embedding)
    sys_monitor.add_health_check("lmstudio", check_lmstudio)
    system_monitor = sys_monitor
    globals()["system_monitor"] = system_monitor
    logger.info("System monitor initialized")

    # ── Phase 9: WebSocket, Memory, Plugins ─────────────────────────

    # 21. WebSocket hub
    from app.websocket import initialize_ws_hub
    ws_hub = await initialize_ws_hub()
    globals()["ws_hub"] = ws_hub
    logger.info("WebSocket hub initialized")

    # 22. Memory store
    from app.memory import MemoryStore
    mem_store = MemoryStore(
        metadata_db=metadata_db,
        vector_client=qdrant if qdrant and qdrant.is_connected else None,
    )
    memory_store = mem_store
    globals()["memory_store"] = memory_store
    logger.info("Memory store initialized")

    # 23. Plugin system
    from app.plugins import initialize_plugin_system
    plugin_mgr = await initialize_plugin_system(plugin_dir="plugins")
    plugin_manager = plugin_mgr
    globals()["plugin_manager"] = plugin_manager
    logger.info("Plugin system initialized")

    # Wire memory store into routes
    from app.api.routes.memory import set_memory_store
    set_memory_store(memory_store)

    # Wire WebSocket hub into routes
    from app.api.routes.websocket import set_globals as set_ws_globals
    set_ws_globals(
        lmstudio=lmstudio_provider,
        cloud=cloud_providers,
        multi_agent_obj=multi_agent_orchestrator,
        monitor=system_monitor,
        memory=memory_store,
    )

    logger.info("RedSight started successfully with all 9 phases")

    try:
        yield
    finally:
        # Always release threads, sockets, and provider clients, even when an
        # application exception interrupts the lifespan context.
        logger.info("RedSight shutting down...")
        from app.plugins import shutdown_plugin_system
        from app.websocket import shutdown_ws_hub

        await shutdown_plugin_system()
        await shutdown_ws_hub()
        if cloud_providers:
            await cloud_providers.close()
        if gpu_telemetry:
            gpu_telemetry.shutdown()
        if lmstudio_provider:
            await lmstudio_provider.close()
        if qdrant:
            await qdrant.close()
        if metadata_db:
            await metadata_db.close()
        logger.info("RedSight stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.platform.platform_name,
        version=settings.platform.version,
        description="High-Performance Local AI Intelligence Platform",
        lifespan=lifespan,
    )

    # Register routes
    from app.api.routes import chat, gpu, health, jobs, memory, models, search, sources
    from app.api.routes import controlled_learning, gpu_scheduler, intelligence, skills_tools
    from app.api.routes import websocket as websocket_routes

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(models.router, prefix="/api/v1", tags=["models"])
    app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
    app.include_router(gpu.router, prefix="/api/v1", tags=["gpu"])
    app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
    app.include_router(search.router, prefix="/api/v1", tags=["search"])
    app.include_router(sources.router, prefix="/api/v1", tags=["sources"])
    app.include_router(skills_tools.router, prefix="/api/v1", tags=["skills-tools"])
    app.include_router(intelligence.router, prefix="/api/v1", tags=["intelligence"])
    app.include_router(gpu_scheduler.router, prefix="/api/v1", tags=["gpu-scheduler"])
    app.include_router(controlled_learning.router, prefix="/api/v1")
    app.include_router(memory.router, prefix="/api/v1", tags=["memory"])
    app.include_router(websocket_routes.router, prefix="/api/v1", tags=["websocket"])

    return app


app = create_app()


# ─── WebSocket Endpoint ─────────────────────────────────────────────

@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for streaming chat responses.

    Clients connect here for real-time token streaming.
    """
    await websocket.accept()

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            message = data.get("message", "")
            model_id = data.get("model")

            if not message:
                await websocket.send_json({"error": "No message provided"})
                continue

            # Stream response
            if lmstudio_provider:
                try:
                    response = await lmstudio_provider.chat(
                        messages=[{"role": "user", "content": message}],
                        model_id=model_id,
                        stream=True,
                    )

                    async for token in response:
                        await websocket.send_json({"token": token})

                    await websocket.send_json({"done": True})

                except Exception as e:
                    await websocket.send_json({"error": str(e)})
            else:
                await websocket.send_json({"error": "LM Studio not available"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()
