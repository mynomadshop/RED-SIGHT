"""
RedSight - High-Performance Local AI Intelligence Platform
Project Intelligence

Code-aware chunking, architecture extraction, decision memory,
and project context aggregation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class CodeChunk:
    """A code chunk with symbol awareness."""
    file_path: str
    symbol_name: str  # function, class, method, module
    symbol_type: str  # function, class, variable, import
    start_line: int
    end_line: int
    content: str
    dependencies: List[str] = field(default_factory=list)
    referenced_by: List[str] = field(default_factory=list)
    language: str = "python"


@dataclass
class ArchitectureNode:
    """A node in the project architecture graph."""
    name: str
    type: str  # module, class, function, file, directory
    path: str
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionRecord:
    """A recorded decision with context and outcome."""
    decision_id: str
    timestamp: float
    context: str
    decision: str
    rationale: str
    outcome: Optional[str] = None
    user_confirmed: bool = False
    tags: List[str] = field(default_factory=list)


@dataclass
class ProjectContext:
    """Aggregated project context."""
    project_root: str
    total_files: int = 0
    total_symbols: int = 0
    architecture_nodes: List[ArchitectureNode] = field(default_factory=list)
    decisions: List[DecisionRecord] = field(default_factory=list)
    last_updated: float = 0.0
    file_types: Dict[str, int] = field(default_factory=dict)
    top_dependencies: List[Dict[str, Any]] = field(default_factory=list)


class CodeAwareChunker:
    """
    Symbol-aware chunking for code files.
    
    Preserves code structure, dependencies, and test associations
    for higher retrieval accuracy.
    """

    # Python symbol patterns
    PYTHON_PATTERNS = {
        "function": re.compile(r'^\s*def\s+(\w+)\s*\('),
        "class": re.compile(r'^\s*class\s+(\w+)'),
        "import": re.compile(r'^(?:from\s+(\w+)|import\s+(\w+))'),
        "variable": re.compile(r'^\s*(\w+)\s*=\s*(?!.*\()'),
    }

    def __init__(self, max_chunk_size: int = 1000, overlap: int = 100):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap

    async def chunk_file(self, file_path: str) -> List[CodeChunk]:
        """Chunk a code file into symbol-aware chunks."""
        try:
            p = Path(file_path)
            if not p.exists():
                logger.warning(f"File not found: {file_path}")
                return []

            content = p.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            language = self._detect_language(file_path)

            if language == "python":
                return await self._chunk_python(file_path, lines, content)
            else:
                return await self._chunk_generic(file_path, lines, content, language)

        except Exception as e:
            logger.error(f"Error chunking {file_path}: {e}")
            return []

    def _detect_language(self, file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".java": "java", ".go": "go", ".rs": "rust",
            ".rb": "ruby", ".php": "php", ".c": "c", ".cpp": "cpp",
            ".h": "c", ".hpp": "cpp",
        }
        return lang_map.get(ext, "unknown")

    async def _chunk_python(self, file_path: str, lines: List[str], content: str) -> List[CodeChunk]:
        """Chunk a Python file into symbol-aware chunks."""
        chunks = []
        symbols = []

        # Extract symbols
        for i, line in enumerate(lines, 1):
            for sym_type, pattern in self.PYTHON_PATTERNS.items():
                match = pattern.match(line)
                if match:
                    if sym_type == "import":
                        module = match.group(1) or match.group(2)
                        if module:
                            symbols.append({
                                "name": module,
                                "type": "import",
                                "line": i,
                                "content": line.strip(),
                            })
                    else:
                        symbols.append({
                            "name": match.group(1),
                            "type": sym_type,
                            "line": i,
                            "content": line.strip(),
                        })

        # Create chunks from symbols
        for idx, symbol in enumerate(symbols):
            start_line = symbol["line"] - 1

            # Find end line (next symbol or end of file)
            if idx + 1 < len(symbols):
                end_line = symbols[idx + 1]["line"] - 1
            else:
                end_line = len(lines)

            chunk_content = "\n".join(lines[start_line:end_line])
            chunk = CodeChunk(
                file_path=file_path,
                symbol_name=symbol["name"],
                symbol_type=symbol["type"],
                start_line=start_line + 1,
                end_line=end_line,
                content=chunk_content,
                language="python",
            )
            chunks.append(chunk)

        # Extract dependencies
        for chunk in chunks:
            if chunk.symbol_type == "import":
                chunk.dependencies = [chunk.symbol_name]
            elif chunk.symbol_type == "function":
                # Find imported names used in this function
                for dep in symbols:
                    if dep["type"] == "import" and dep["name"] in chunk.content:
                        chunk.dependencies.append(dep["name"])

        return chunks

    async def _chunk_generic(self, file_path: str, lines: List[str], content: str, language: str) -> List[CodeChunk]:
        """Chunk a generic code file."""
        if not lines:
            return []

        # Simple line-based chunking for non-Python files
        chunk_size = self.max_chunk_size // 10  # Approximate chars per line
        chunks = []

        for i in range(0, len(lines), chunk_size):
            chunk_lines = lines[i:i + chunk_size]
            chunk_content = "\n".join(chunk_lines)

            chunks.append(CodeChunk(
                file_path=file_path,
                symbol_name=f"chunk_{i // chunk_size}",
                symbol_type="block",
                start_line=i + 1,
                end_line=min(i + chunk_size, len(lines)),
                content=chunk_content,
                language=language,
            ))

        return chunks

    async def build_dependency_graph(self, chunks: List[CodeChunk]) -> Dict[str, List[str]]:
        """Build a dependency graph from chunks."""
        graph: Dict[str, List[str]] = {}

        for chunk in chunks:
            key = f"{chunk.file_path}:{chunk.symbol_name}"
            deps = list(chunk.dependencies)
            graph[key] = deps

        return graph


class ArchitectureExtractor:
    """
    Extracts project architecture from code files.
    
    Builds a graph of modules, classes, functions, and their relationships.
    """

    def __init__(self):
        self._nodes: Dict[str, ArchitectureNode] = {}

    async def extract(self, project_root: str, max_files: int = 500) -> ProjectContext:
        """Extract architecture from a project."""
        start_time = time.time()
        context = ProjectContext(project_root=project_root)

        # Scan project files
        files = self._scan_project(Path(project_root), max_files)
        context.total_files = len(files)

        # Count file types
        for f in files:
            ext = f.suffix.lower()
            context.file_types[ext or "(no ext)"] = context.file_types.get(ext or "(no ext)", 0) + 1

        # Chunk and analyze files
        chunker = CodeAwareChunker()
        all_chunks: List[CodeChunk] = []

        for file_path in files[:max_files]:
            chunks = await chunker.chunk_file(str(file_path))
            all_chunks.extend(chunks)

        context.total_symbols = len(all_chunks)

        # Build architecture nodes
        for chunk in all_chunks:
            node = ArchitectureNode(
                name=chunk.symbol_name,
                type=chunk.symbol_type,
                path=chunk.file_path,
                dependencies=chunk.dependencies,
            )
            node_key = f"{chunk.file_path}:{chunk.symbol_name}"
            self._nodes[node_key] = node

        # Build dependency graph
        dep_graph = await chunker.build_dependency_graph(all_chunks)

        # Calculate top dependencies
        dep_counts: Dict[str, int] = {}
        for deps in dep_graph.values():
            for dep in deps:
                dep_counts[dep] = dep_counts.get(dep, 0) + 1

        context.top_dependencies = sorted(
            [{"name": k, "count": v} for k, v in dep_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:20]

        # Add architecture nodes to context
        context.architecture_nodes = list(self._nodes.values())[:100]
        context.last_updated = time.time()

        elapsed = time.time() - start_time
        logger.info(f"Architecture extracted: {context.total_files} files, "
                    f"{context.total_symbols} symbols, {elapsed:.1f}s")

        return context

    def _scan_project(self, root: Path, max_files: int) -> List[Path]:
        """Scan project for code files."""
        code_extensions = {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
            ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift",
            ".kt", ".scala", ".sh", ".bash", ".yaml", ".yml", ".json",
            ".toml", ".ini", ".cfg", ".xml", ".html", ".css", ".sql",
        }

        files = []
        for ext in code_extensions:
            files.extend(root.rglob(f"*{ext}"))

        # Filter out venv, node_modules, .git, __pycache__
        excluded = {"venv", "node_modules", ".git", "__pycache__", ".tox", ".eggs"}
        filtered = []
        for f in files:
            if not any(exc in f.parts for exc in excluded):
                filtered.append(f)

        return sorted(filtered)[:max_files]

    def get_node(self, key: str) -> Optional[ArchitectureNode]:
        """Get an architecture node by key."""
        return self._nodes.get(key)

    def get_dependencies(self, key: str) -> List[str]:
        """Get dependencies for a node."""
        node = self._nodes.get(key)
        return node.dependencies if node else []

    def get_dependents(self, key: str) -> List[str]:
        """Get dependents for a node."""
        node = self._nodes.get(key)
        return node.dependents if node else []


class DecisionMemory:
    """
    Tracks and stores project decisions with context and outcomes.
    
    Enables learning from past decisions and understanding project evolution.
    """

    def __init__(self):
        self._decisions: Dict[str, DecisionRecord] = {}

    async def record(
        self,
        context: str,
        decision: str,
        rationale: str,
        tags: Optional[List[str]] = None,
        user_confirmed: bool = False,
    ) -> str:
        """Record a new decision."""
        decision_id = f"dec_{int(time.time())}_{len(self._decisions)}"
        record = DecisionRecord(
            decision_id=decision_id,
            timestamp=time.time(),
            context=context,
            decision=decision,
            rationale=rationale,
            user_confirmed=user_confirmed,
            tags=tags or [],
        )
        self._decisions[decision_id] = record
        logger.debug(f"Decision recorded: {decision_id}")
        return decision_id

    async def update_outcome(self, decision_id: str, outcome: str) -> bool:
        """Update the outcome of a decision."""
        if decision_id in self._decisions:
            self._decisions[decision_id].outcome = outcome
            return True
        return False

    async def confirm(self, decision_id: str) -> bool:
        """Mark a decision as user-confirmed."""
        if decision_id in self._decisions:
            self._decisions[decision_id].user_confirmed = True
            return True
        return False

    async def query(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[DecisionRecord]:
        """Query decisions by context, decision text, or tags."""
        query_lower = query.lower()
        results = []

        for record in self._decisions.values():
            # Filter by tags if specified
            if tags and not any(t in record.tags for t in tags):
                continue

            # Search in context, decision, and rationale
            text = f"{record.context} {record.decision} {record.rationale}"
            if any(term in text.lower() for term in query_lower.split()):
                results.append(record)

        return results[:limit]

    async def get_by_id(self, decision_id: str) -> Optional[DecisionRecord]:
        """Get a decision by ID."""
        return self._decisions.get(decision_id)

    async def get_recent(self, limit: int = 20) -> List[DecisionRecord]:
        """Get recent decisions."""
        sorted_decisions = sorted(
            self._decisions.values(),
            key=lambda x: x.timestamp,
            reverse=True,
        )
        return sorted_decisions[:limit]

    async def get_stats(self) -> Dict[str, Any]:
        """Get decision memory statistics."""
        total = len(self._decisions)
        confirmed = sum(1 for d in self._decisions.values() if d.user_confirmed)
        with_outcome = sum(1 for d in self._decisions.values() if d.outcome)

        return {
            "total_decisions": total,
            "confirmed": confirmed,
            "with_outcome": with_outcome,
            "confirmation_rate": round(confirmed / total * 100, 1) if total > 0 else 0,
        }


class ProjectIntelligence:
    """
    Main Project Intelligence orchestrator.
    
    Combines code-aware chunking, architecture extraction,
    and decision memory into a unified system.
    """

    def __init__(self):
        self._chunker = CodeAwareChunker()
        self._extractor = ArchitectureExtractor()
        self._decision_memory = DecisionMemory()
        self._project_contexts: Dict[str, ProjectContext] = {}

    async def index_project(self, project_root: str, max_files: int = 500) -> ProjectContext:
        """Index a project and extract architecture."""
        context = await self._extractor.extract(project_root, max_files)
        self._project_contexts[project_root] = context
        return context

    async def record_decision(
        self,
        context: str,
        decision: str,
        rationale: str,
        tags: Optional[List[str]] = None,
        user_confirmed: bool = False,
    ) -> str:
        """Record a project decision."""
        return await self._decision_memory.record(
            context=context,
            decision=decision,
            rationale=rationale,
            tags=tags,
            user_confirmed=user_confirmed,
        )

    async def search_architecture(self, query: str, limit: int = 10) -> List[ArchitectureNode]:
        """Search architecture nodes by name or path."""
        query_lower = query.lower()
        results = []

        for node in self._extractor._nodes.values():
            text = f"{node.name} {node.path} {node.type}"
            if query_lower in text.lower():
                results.append(node)

        return results[:limit]

    async def get_dependencies(self, symbol_key: str) -> List[str]:
        """Get dependencies for a symbol."""
        return self._extractor.get_dependencies(symbol_key)

    async def get_dependents(self, symbol_key: str) -> List[str]:
        """Get dependents for a symbol."""
        return self._extractor.get_dependents(symbol_key)

    async def query_decisions(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[DecisionRecord]:
        """Query project decisions."""
        return await self._decision_memory.query(query, tags, limit)

    async def get_project_stats(self) -> Dict[str, Any]:
        """Get overall project intelligence statistics."""
        context_stats = {}
        for root, ctx in self._project_contexts.items():
            context_stats[root] = {
                "total_files": ctx.total_files,
                "total_symbols": ctx.total_symbols,
                "file_types": ctx.file_types,
            }

        decision_stats = await self._decision_memory.get_stats()

        return {
            "projects_indexed": len(self._project_contexts),
            "contexts": context_stats,
            "decisions": decision_stats,
        }

    async def export_context(self, project_root: str) -> Optional[Dict[str, Any]]:
        """Export project context as JSON-serializable dict."""
        ctx = self._project_contexts.get(project_root)
        if not ctx:
            return None

        return {
            "project_root": ctx.project_root,
            "total_files": ctx.total_files,
            "total_symbols": ctx.total_symbols,
            "file_types": ctx.file_types,
            "top_dependencies": ctx.top_dependencies,
            "architecture_nodes": [
                {
                    "name": n.name,
                    "type": n.type,
                    "path": n.path,
                    "dependencies": n.dependencies,
                }
                for n in ctx.architecture_nodes[:50]
            ],
            "decisions": [
                {
                    "id": d.decision_id,
                    "context": d.context,
                    "decision": d.decision,
                    "rationale": d.rationale,
                    "outcome": d.outcome,
                    "tags": d.tags,
                }
                for d in list(self._decision_memory._decisions.values())[:20]
            ],
        }