# RedSight - Phase Tracker

## Phase 0 - Foundation ✅ COMPLETE

- [x] Project skeleton + pyproject.toml
- [x] Core interfaces (ModelProvider, Retriever, Skill, Tool, MemoryStore, JobScheduler, AuditSink)
- [x] FastAPI backend with streaming
- [x] PySide6 UI skeleton
- [x] Typed config with Pydantic Settings
- [x] GPU telemetry via pynvml
- [x] LM Studio provider adapter
- [x] pytest setup
- [x] Benchmark harness (skeleton)
- [x] Agent coordinator (skeleton)
- [x] Skills registry (skeleton)
- [x] Security layer (skeleton)

## Phase 1 - Knowledge MVP ✅ IN PROGRESS

### Completed
- [x] Qdrant integration — Full client wrapper with embedded mode, collection management, dense + hybrid search, RRF fusion
- [x] SQLite metadata DB — SQLAlchemy models for source registry, chunks, index versions, jobs
- [x] Hybrid search engine — Query classification, parallel collection search, reranking, context budgeting, citation pack
- [x] Source viewer — Chunk detail, source file info, related chunks, content preview, navigation
- [x] Embedding model loader — sentence-transformers + LM Studio API support
- [x] Full ingestion pipeline — PDF/text/code parsing → chunking → embedding → Qdrant + SQLite indexing
- [x] Code-aware parser — AST-based symbol extraction, function/class/method chunking
- [x] Search API — `/api/v1/search`, `/api/v1/collections`, `/api/v1/chunks/{id}`
- [x] Sources API — `/api/v1/sources/chunk/{id}`, `/api/v1/sources/file/{path}/preview`, navigation
- [x] Indexing API — `/api/v1/jobs/index`, batch index, re-index, job listing
- [x] CLI index script — `redsight-index` with embedded Qdrant, model loading, progress reporting
- [x] Server initialization — Full pipeline wired into FastAPI lifespan
- [x] UI Knowledge Search tab — Query input, collection filter, result cards with provenance
- [x] UI Source Viewer panel — Scrollable source cards with content preview, scores, metadata
- [x] UI Indexing tab — File path input, collection selection, job history table
- [x] Integration tests — 20+ tests covering Qdrant, SQLite, parsers, embeddings, full pipeline

### Remaining
- [ ] Reranker model integration (cross-encoder)
- [ ] Sparse vector support (BM25-style lexical)
- [ ] Project directory scanner for batch indexing

## Phase 2 - Hybrid RAG
- [ ] Sparse + dense retrieval fusion
- [ ] Cross-encoder reranking
- [ ] Context budgeting optimization
- [ ] Golden evaluation set
- [ ] Regression test suite

## Phase 3 - Skills & Tools
- [ ] Skill manifests with JSON Schema
- [ ] Semantic skill discovery
- [ ] Typed tool interface
- [ ] Permission sandbox
- [ ] Audit trail integration

## Phase 4 - Project Intelligence
- [ ] Bluesight project miner
- [ ] Code-aware chunking (advanced)
- [ ] Architecture extraction
- [ ] Decision memory

## Phase 5 - GPU Scheduler
- [ ] VRAM reservations
- [ ] GPU affinity
- [ ] Queue management
- [ ] Dual-GPU task placement
- [ ] Benchmark profiles

## Phase 6 - Controlled Learning
- [ ] Candidate memories/skills
- [ ] Validation pipeline
- [ ] Evaluator agent
- [ ] Approval/promotion workflow

## Phase 7 - Productization
- [ ] Installer
- [ ] Backup/restore
- [ ] Crash recovery
- [ ] UI polish
- [ ] Migration tools
