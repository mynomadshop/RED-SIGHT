# RedSight Blueprint - High-Performance Local AI Intelligence Platform v2.0
# Full 17-page technical blueprint saved for reference
# See original PDF: High_Performance_Local_AI_Intelligence_Platform_Blueprint-1.pdf

## Architecture Decision Sheet (from blueprint)
- Core runtime: Python 3.12
- Default inference: LM Studio local API (OpenAI-compatible)
- RAG backend: Qdrant + SQLite metadata
- Retrieval: Hybrid + rerank
- UI v1: PySide6
- Skills: Registry + semantic index
- Learning: Gated promotion
- Multi-GPU: Central scheduler
- Cloud APIs: Optional adapters

## Phase 0 - Foundation (Build FIRST)
1. Create repository skeleton + typed settings
2. LM Studio provider adapter (health, list models, chat stream, embeddings)
3. GPU telemetry (enumerate GPUs, VRAM, utilization, status endpoint)
4. Source registry + Qdrant + SQLite (import, index, search)
5. Command Center UI (streaming answer, source cards, model name, GPU status, stop)
6. Benchmark harness (TTFT, tokens/s, retrieval latency, VRAM peak)
7. Add agent/skill execution (one safe read-only skill)

## Key Interfaces to Define First
- ModelProvider (LM Studio + cloud adapters)
- Retriever (hybrid search, reranking)
- Skill (manifest, execution, permissions)
- Tool (typed contracts, permission checks)
- MemoryStore (working/episodic/semantic/procedural)
- JobScheduler (dual-GPU aware, VRAM reservations)
- AuditSink (immutable run records)
