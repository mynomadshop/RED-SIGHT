"""
RedSight - High-Performance Local AI Intelligence Platform
Code Parser

Parses Python source files with symbol-aware chunking.
Chunks around modules, classes, functions, and related tests.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.ingestion.parser import DocumentChunk

logger = logging.getLogger(__name__)


@dataclass
class CodeSymbol:
    """A parsed code symbol (class, function, method)."""
    name: str
    kind: str  # class, function, method, module
    line_start: int
    line_end: int
    docstring: Optional[str]
    source: str  # The actual code text


class CodeParser:
    """
    Code-aware parser for Python source files.

    Chunks code around symbols (classes, functions, methods) rather
    than arbitrary token windows. Cross-links related code elements.
    """

    # Common patterns for code structure
    IMPORT_PATTERN = re.compile(
        r"^(?:from\s+\S+\s+import\s+|import\s+)", re.MULTILINE
    )
    BLANK_LINE_PATTERN = re.compile(r"^\s*$", re.MULTILINE)

    def __init__(self, chunk_size: int = 1024, max_lines_per_chunk: int = 80):
        self.chunk_size = chunk_size
        self.max_lines_per_chunk = max_lines_per_chunk

    async def parse(
        self,
        source_path: str,
        project: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """Parse a Python file into symbol-aware chunks."""
        path = Path(source_path)
        if not path.exists():
            logger.error(f"File not found: {source_path}")
            return []

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read {source_path}: {e}")
            return []

        lines = content.split("\n")
        total_lines = len(lines)

        # Try AST parsing for symbol extraction
        symbols = self._extract_symbols(content)

        if symbols:
            # Symbol-aware chunking
            chunks = self._chunk_by_symbols(
                content, symbols, source_path, project, metadata
            )
        else:
            # Fallback: line-based chunking
            chunks = self._chunk_by_lines(
                content, source_path, project, metadata
            )

        logger.info(f"Parsed {len(chunks)} chunks from {source_path}")
        return chunks

    def _extract_symbols(self, source: str) -> List[CodeSymbol]:
        """Extract code symbols using AST parsing."""
        symbols = []

        try:
            tree = ast.parse(source)
        except SyntaxError:
            logger.warning("Syntax error in source, falling back to regex")
            return self._extract_symbols_regex(source)

        # Module-level docstring
        module_docstring = ast.get_docstring(tree)
        if module_docstring:
            symbols.append(CodeSymbol(
                name=Path(source).stem,
                kind="module",
                line_start=1,
                line_end=1 + len(module_docstring.split("\n")),
                docstring=module_docstring,
                source=module_docstring,
            ))

        # Walk AST for classes and functions
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                docstring = ast.get_docstring(node)
                symbols.append(CodeSymbol(
                    name=node.name,
                    kind="class",
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    docstring=docstring,
                    source="",  # Will be extracted from source later
                ))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip private/dunder methods at module level
                docstring = ast.get_docstring(node)
                symbols.append(CodeSymbol(
                    name=node.name,
                    kind="method" if hasattr(node, "decorator_list") else "function",
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    docstring=docstring,
                    source="",
                ))

        return symbols

    def _extract_symbols_regex(self, source: str) -> List[CodeSymbol]:
        """Fallback regex-based symbol extraction."""
        symbols = []
        lines = source.split("\n")

        # Match class definitions
        class_pattern = re.compile(r"^class\s+(\w+)")
        # Match function definitions
        func_pattern = re.compile(r"^(?:async\s+)?def\s+(\w+)")

        current_class = None
        for i, line in enumerate(lines, 1):
            class_match = class_pattern.match(line.strip())
            func_match = func_pattern.match(line.strip())

            if class_match:
                current_class = class_match.group(1)
                symbols.append(CodeSymbol(
                    name=class_match.group(1),
                    kind="class",
                    line_start=i,
                    line_end=i,
                    docstring=None,
                    source="",
                ))
            elif func_match:
                kind = "method" if current_class else "function"
                symbols.append(CodeSymbol(
                    name=func_match.group(1),
                    kind=kind,
                    line_start=i,
                    line_end=i,
                    docstring=None,
                    source="",
                ))

        return symbols

    def _chunk_by_symbols(
        self,
        content: str,
        symbols: List[CodeSymbol],
        source_path: str,
        project: str,
        metadata: Optional[Dict[str, Any]],
    ) -> List[DocumentChunk]:
        """Chunk code around symbol boundaries."""
        lines = content.split("\n")
        chunks = []
        chunk_index = 0

        # Sort symbols by line number
        symbols.sort(key=lambda s: s.line_start)

        # Build symbol ranges
        for i, sym in enumerate(symbols):
            # Determine the end of this symbol's range
            if i + 1 < len(symbols):
                next_start = symbols[i + 1].line_start - 1
            else:
                next_start = len(lines)

            # Extract symbol code
            line_start = max(0, sym.line_start - 1)
            line_end = min(len(lines), next_start)
            symbol_code = "\n".join(lines[line_start:line_end])

            # Create chunk for this symbol
            chunk_id = f"code_{self._hash_path(source_path)}_sym_{sym.name}_{chunk_index}"
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                content=symbol_code,
                source_path=source_path,
                project=project,
                page_number=None,
                heading=f"{sym.kind}: {sym.name}",
                chunk_index=chunk_index,
                metadata={
                    **(metadata or {}),
                    "symbol_name": sym.name,
                    "symbol_kind": sym.kind,
                    "line_start": sym.line_start,
                    "line_end": line_end,
                    "docstring": sym.docstring,
                },
            ))
            chunk_index += 1

        # If no symbols were found, fall back to line chunking
        if not chunks:
            chunks = self._chunk_by_lines(content, source_path, project, metadata)

        return chunks

    def _chunk_by_lines(
        self,
        content: str,
        source_path: str,
        project: str,
        metadata: Optional[Dict[str, Any]],
    ) -> List[DocumentChunk]:
        """Fallback: chunk by line groups."""
        lines = content.split("\n")
        chunks = []
        chunk_index = 0
        current_lines = []
        current_start = 1

        for i, line in enumerate(lines):
            current_lines.append(line)

            # Check if we've reached a natural break
            if (
                len(current_lines) >= self.max_lines_per_chunk
                or (line.strip() == "" and current_lines)
            ):
                chunk_text = "\n".join(current_lines)
                chunk_id = f"code_{self._hash_path(source_path)}_line_{chunk_index}"

                chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    content=chunk_text,
                    source_path=source_path,
                    project=project,
                    chunk_index=chunk_index,
                    metadata=metadata or {},
                ))
                chunk_index += 1
                current_lines = []
                current_start = i + 2

        # Handle remaining lines
        if current_lines:
            chunk_text = "\n".join(current_lines)
            chunk_id = f"code_{self._hash_path(source_path)}_line_{chunk_index}"
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                content=chunk_text,
                source_path=source_path,
                project=project,
                chunk_index=chunk_index,
                metadata=metadata or {},
            ))

        return chunks

    @staticmethod
    def _hash_path(path: str) -> str:
        """Short hash of a file path."""
        return hashlib.md5(path.encode()).hexdigest()[:8]
