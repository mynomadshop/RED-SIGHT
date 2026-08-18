"""
RedSight - High-Performance Local AI Intelligence Platform
Source Viewer

UI component for inspecting retrieved chunks and their source files.
Displays:
- Chunk content with highlighting
- Source file path and metadata
- Page number, heading, position
- Provenance chain (source → chunk → embedding)
- Related chunks from same source
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ChunkDetail:
    """Detailed view of a single chunk."""
    chunk_id: str
    content: str
    source_path: str
    project: str
    collection: str
    page_number: Optional[int] = None
    heading: Optional[str] = None
    chunk_index: int = 0
    offset_start: Optional[int] = None
    offset_end: Optional[int] = None
    score: Optional[float] = None
    embedding_version: str = "unknown"
    parser_version: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "source_path": self.source_path,
            "project": self.project,
            "collection": self.collection,
            "page_number": self.page_number,
            "heading": self.heading,
            "chunk_index": self.chunk_index,
            "offset_start": self.offset_start,
            "offset_end": self.offset_end,
            "score": round(self.score, 4) if self.score else None,
            "embedding_version": self.embedding_version,
            "parser_version": self.parser_version,
        }


@dataclass
class SourceFileInfo:
    """Metadata about a source file."""
    source_path: str
    file_type: str
    project: str
    size_bytes: int
    file_hash: str
    chunk_count: int = 0
    last_indexed: Optional[str] = None
    access_scope: str = "internal"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "file_type": self.file_type,
            "project": self.project,
            "size_bytes": self.size_bytes,
            "file_hash": self.file_hash,
            "chunk_count": self.chunk_count,
            "last_indexed": self.last_indexed,
            "access_scope": self.access_scope,
        }


class SourceViewer:
    """
    Inspect retrieved chunks and their source files.

    Provides:
    - Full chunk detail with provenance
    - Source file metadata
    - Related chunks from same source
    - Content preview with position highlighting
    """

    def __init__(self, metadata_db=None):
        self._metadata = metadata_db

    async def get_chunk_detail(self, chunk_id: str) -> Optional[ChunkDetail]:
        """Get full detail for a chunk."""
        if not self._metadata:
            return None

        chunk_data = await self._metadata.get_chunk_by_id(chunk_id)
        if not chunk_data:
            return None

        return ChunkDetail(
            chunk_id=chunk_data["chunk_id"],
            content=chunk_data["content"],
            source_path="",  # Would need source lookup
            project="",
            collection=chunk_data["collection"],
            page_number=chunk_data.get("page_number"),
            heading=chunk_data.get("heading"),
            chunk_index=chunk_data.get("chunk_index", 0),
            offset_start=chunk_data.get("offset_start"),
            offset_end=chunk_data.get("offset_end"),
            embedding_version=chunk_data.get("embedding_version", "unknown"),
            parser_version=chunk_data.get("parser_version", "unknown"),
        )

    async def get_source_file_info(self, source_path: str) -> Optional[SourceFileInfo]:
        """Get metadata about a source file."""
        if not self._metadata:
            return None

        source_data = await self._metadata.get_source_by_path(source_path)
        if not source_data:
            return None

        # Get chunk count for this source
        chunks = await self._metadata.get_chunks_for_source(source_data["id"])

        return SourceFileInfo(
            source_path=source_path,
            file_type=source_data["file_type"],
            project=source_data["project"],
            size_bytes=source_data["size_bytes"],
            file_hash=source_data["file_hash"],
            chunk_count=len(chunks),
            last_indexed=source_data.get("updated_at"),
            access_scope=source_data.get("access_scope", "internal"),
        )

    async def get_related_chunks(self, source_path: str, exclude_chunk_id: Optional[str] = None,
                                  limit: int = 10) -> List[ChunkDetail]:
        """Get other chunks from the same source file."""
        if not self._metadata:
            return []

        source_data = await self._metadata.get_source_by_path(source_path)
        if not source_data:
            return []

        chunks = await self._metadata.get_chunks_for_source(source_data["id"])

        related = []
        for c in chunks:
            if exclude_chunk_id and c["chunk_id"] == exclude_chunk_id:
                continue
            if len(related) >= limit:
                break
            related.append(ChunkDetail(
                chunk_id=c["chunk_id"],
                content=c["content"],
                source_path=source_path,
                project=source_data["project"],
                collection=c["collection"],
                page_number=c.get("page_number"),
                heading=c.get("heading"),
                chunk_index=c.get("chunk_index", 0),
            ))

        return related

    async def preview_content(self, source_path: str, offset: int = 0,
                               length: int = 500) -> Dict[str, Any]:
        """
        Preview content from a source file.

        Returns preview text with position info.
        """
        try:
            path = Path(source_path)
            if not path.exists():
                return {"error": f"File not found: {source_path}"}

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            start = max(0, offset)
            end = min(len(content), offset + length)
            preview = content[start:end]

            # Find line numbers for position
            lines_before = content[:start].count('\n')
            lines_in_preview = preview.count('\n')

            return {
                "source_path": source_path,
                "offset_start": start,
                "offset_end": end,
                "line_start": lines_before + 1,
                "line_end": lines_before + lines_in_preview + 1,
                "preview": preview,
                "total_length": len(content),
            }
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

    async def get_source_navigation(self, source_path: str, current_chunk_id: str,
                                     chunk_size: int = 512) -> Dict[str, Any]:
        """
        Get navigation info for browsing chunks in a source file.

        Returns previous/next chunk IDs and current position.
        """
        if not self._metadata:
            return {"error": "Metadata DB not available"}

        source_data = await self._metadata.get_source_by_path(source_path)
        if not source_data:
            return {"error": "Source not found"}

        chunks = await self._metadata.get_chunks_for_source(source_data["id"])
        chunk_ids = [c["chunk_id"] for c in chunks]

        try:
            current_idx = chunk_ids.index(current_chunk_id)
        except ValueError:
            current_idx = 0

        prev_chunk = chunk_ids[current_idx - 1] if current_idx > 0 else None
        next_chunk = chunk_ids[current_idx + 1] if current_idx < len(chunk_ids) - 1 else None

        return {
            "source_path": source_path,
            "total_chunks": len(chunk_ids),
            "current_index": current_idx,
            "current_chunk_id": current_chunk_id,
            "previous_chunk_id": prev_chunk,
            "next_chunk_id": next_chunk,
            "chunk_ids": chunk_ids,
        }
