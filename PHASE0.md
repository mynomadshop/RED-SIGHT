# RedSight - High-Performance Local AI Intelligence Platform
# Phase 0: Foundation

## Cleanup Summary
- Removed state-snapshots (874MB)
- Removed old backup (835MB)
- Cleaned 148 old sessions (>30 days)
- Removed incomplete downloads (34GB .crdownload)
- Cleared pip/npm/yarn caches
- Disk: 94% → 93% (74GB free)

## Blueprint Analysis
- Extracted all 17 pages from PDF
- Saved summary to blueprint.md
- Key interfaces defined: ModelProvider, Retriever, Skill, Tool, MemoryStore, JobScheduler, AuditSink

## Phase 0 Tasks
- [x] Project skeleton created
- [x] pyproject.toml with dependencies
- [x] README.md with architecture overview
- [ ] Core interfaces (ModelProvider, Retriever, Skill, Tool, MemoryStore, JobScheduler, AuditSink)
- [ ] FastAPI backend with streaming
- [ ] PySide6 UI skeleton
- [ ] Typed config with Pydantic Settings
- [ ] GPU telemetry via pynvml
- [ ] Qdrant + SQLite integration
- [ ] pytest setup
- [ ] LM Studio connectivity

## Next Steps
1. Build core interfaces (Phase 0 - Foundation)
2. Implement LM Studio provider adapter
3. Add GPU telemetry
4. Create source registry + Qdrant + SQLite
5. Build Command Center UI screen
6. Add benchmark harness
7. Add agent/skill execution
