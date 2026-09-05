# RedSight - High-Performance Local AI Intelligence Platform

## Overview

RedSight is a local-first AI intelligence platform that turns your projects, documents, and operational knowledge into a governed retrieval + agent system. It routes each task to the fastest suitable local or cloud model while continuously measuring performance and learning from validated outcomes.

### Core Features

- **Local-First AI**: LM Studio as default inference gateway, cloud APIs as optional fallbacks
- **Knowledge Fabric**: Hybrid retrieval (dense + sparse) with reranking and provenance
- **Agent Runtime**: Planner/executor/evaluator loop with subagent support
- **Skill Registry**: Semantic discovery with governed execution and permissions
- **GPU-Aware Scheduling**: Dual-GPU aware scheduler with VRAM reservations and backpressure
- **Project Intelligence**: Code-aware indexing, architecture extraction, decision memory
- **Immersive UI**: PySide6 desktop app with streaming output, source inspection, and performance telemetry
- **Self-Improving**: Gated learning with validation and approval workflows

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Windows Experience Layer                    │
│         PySide6 Desktop App (Command Center)             │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP/WebSocket
┌──────────────────────────▼──────────────────────────────┐
│              Python Control Plane                        │
│         FastAPI Service Layer                           │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│  Agent   │ Retrieval│  Model   │  Skill   │  GPU        │
│ Runtime  │ & Memory │  Router  │ Registry │ Scheduler   │
└──────────┴──────────┴──────────┴──────────┴─────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│              Accelerated Execution                       │
│    CUDA/PyTorch/Triton + LM Studio + Qdrant + SQLite   │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.12+
- Windows 11
- NVIDIA GPU(s) with CUDA 12.x drivers
- LM Studio (running on http://127.0.0.1:1234)

### Installation

```bash
# Clone the repository
git clone https://github.com/mynomadshop/RED-SIGHT.git
cd RED-SIGHT

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -e .

# Install optional dependencies
pip install -e ".[dev]"  # Development tools
pip install -e ".[tensorrt]"  # TensorRT acceleration
```

### Configuration

Create a `.env` file in the project root:

```env
# Platform
RED_SIGHT_PLATFORM__MODE=local_preferred
RED_SIGHT_PLATFORM__DATA_ROOT=./data

# LM Studio
RED_SIGHT_LMSTUDIO__BASE_URL=http://127.0.0.1:1234/v1
RED_SIGHT_LMSTUDIO__TIMEOUT_SECONDS=180

# Qdrant
RED_SIGHT_RETRIEVAL__VECTOR_BACKEND_URL=http://127.0.0.1:6333
RED_SIGHT_RETRIEVAL__VECTOR_BACKEND_EMBEDDED=false

# GPU
RED_SIGHT_ROUTING__VRAM_HEADROOM_GB_PER_GPU=3.0
```

### Running

```bash
# Start the API server
redsight-server --host 127.0.0.1 --port 8000

# Start the desktop UI
redsight-ui

# Index a project folder
redsight-index --path ./projects/bluesight --collection project_code

# Run benchmarks
redsight-benchmark --profile local_llm
```

## Project Structure

```
redsight/
├── app/
│   ├── api/              # FastAPI routes, streaming events
│   ├── orchestration/    # Task planner, state machine, routing
│   ├── agents/           # Agent profiles + executor/evaluator
│   ├── skills/           # Registry, manifests, sandbox runner
│   ├── retrieval/        # Query planning, hybrid search, reranking
│   │   ├── qdrant_client.py    # Qdrant client with embedded mode
│   │   ├── metadata_db.py      # SQLite metadata (SQLAlchemy)
│   │   ├── hybrid_search.py    # Hybrid search engine
│   │   ├── source_viewer.py    # Source inspection UI backend
│   │   └── embedding_loader.py # Embedding model loader
│   ├── memory/           # Working/episodic/semantic/procedural memory
│   ├── ingestion/        # PDF/doc/code/project parsers
│   │   ├── parser.py           # Document parser (PDF/text)
│   │   ├── code_parser.py      # Code-aware parser (AST)
│   │   └── indexer.py          # Full ingestion pipeline
│   ├── models/           # LM Studio + cloud provider adapters
│   ├── acceleration/     # GPU scheduler, NVML, Triton backends
│   ├── tools/            # Typed tool contracts, permission checks
│   ├── security/         # Secrets, scopes, policy, audit
│   ├── telemetry/        # Traces, metrics, benchmarks
│   └─ config/            # Typed settings, capability registry
├── ui/                   # PySide6 desktop app
│   └── command_center.py # Main UI with Knowledge, Sources, Indexing tabs
├── data/
│   ├── sources/          # Canonical imported assets
│   ├── qdrant/           # Vector data / snapshots
│   ├── metadata.db       # SQLite operational metadata
│   └── evals/            # Golden queries/tasks
├── projects/             # Project connectors / manifests
├── tests/
│   ├── unit/
│   ├── integration/
│   │   └── test_phase1.py  # Phase 1 integration tests
│   └── performance/
└── scripts/              # Setup, migration, indexing, diagnostics
    ├── index.py          # CLI indexing utility
    ├── benchmark.py      # Benchmark harness
    └── diagnostics.py    # System diagnostics
```

## Phase 1 - Knowledge MVP

The Knowledge MVP delivers a working retrieval system:

1. **Qdrant Integration** — Local embedded or server-based vector store with hybrid search
2. **SQLite Metadata** — Persistent source registry with versioned indexes
3. **Full Ingestion Pipeline** — PDF/text/code → chunks → embeddings → vector index
4. **Semantic Search** — Query collections with provenance and citation packs
5. **Source Viewer** — Inspect retrieved chunks, preview source files, navigate related chunks
6. **Re-indexing** — Versioned indexes with change detection and rollback support

### API Endpoints

```
POST   /api/v1/search              # Search knowledge base
GET    /api/v1/collections         # List collections
GET    /api/v1/collections/{name}/stats  # Collection statistics
GET    /api/v1/chunks/{chunk_id}   # Get chunk by ID

POST   /api/v1/jobs/index          # Index a file
POST   /api/v1/jobs/index/batch    # Batch index files
POST   /api/v1/collections/{name}/reindex  # Re-index collection
GET    /api/v1/jobs                # List indexing jobs
GET    /api/v1/jobs/{job_id}       # Get job details

POST   /api/v1/scheduler/jobs/submit         # Submit a GPU-scheduled workload
POST   /api/v1/scheduler/jobs/cancel         # Cancel a GPU-scheduled workload
GET    /api/v1/scheduler/jobs                # List GPU-scheduled workloads
GET    /api/v1/scheduler/jobs/{id}           # Get GPU-scheduled workload status
GET    /api/v1/scheduler/jobs/queue-depth    # Get scheduler queue depth

GET    /api/v1/sources/chunk/{id}  # Chunk detail
GET    /api/v1/sources/file/{path}/preview  # File content preview
GET    /api/v1/sources/file/{path}/related  # Related chunks
GET    /api/v1/sources/navigation/{path}    # Chunk navigation
```

### CLI Usage

```bash
# Index a single file
redsight-index --path ./document.pdf --collection knowledge_docs

# Index a directory
redsight-index --path ./projects/bluesight --collection project_code --project bluesight

# Index with verbose output
redsight-index --path ./docs --collection knowledge_docs --verbose

# Index without embeddings (fast, metadata only)
redsight-index --path ./docs --embeddings none
```

## Development

### Running Tests

```bash
pytest tests/ -v
pytest tests/integration/ -v  # Integration tests
pytest tests/unit/ -v         # Unit tests
```

### Code Quality

```bash
ruff check .
ruff format .
mypy redsight/
```

### Pre-commit Hooks

```bash
pre-commit install
pre-commit run --all-files
```

## Architecture Principles

1. **Local-first, cloud-optional** — Every core workflow functions offline
2. **One control plane, multiple engines** — Centralize policy, separate execution
3. **Retrieval over prompt bloat** — Fetch smallest high-quality context set
4. **Provenance everywhere** — Every indexed unit retains source metadata
5. **Executable skills are not just vectors** — Registry controls version and permissions
6. **Learning is gated** — Validation and tests before promotion
7. **Performance is measured** — Benchmark on actual models and workflows
8. **Failure isolation** — One job failure doesn't take down the system

## License

MIT License - See LICENSE file for details
