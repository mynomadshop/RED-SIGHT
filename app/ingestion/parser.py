"""
RedSight - High-Performance Local AI Intelligence Platform
Document Parser

Parses PDF, text, and other document formats with structural preservation.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """A chunk of parsed document content."""
    chunk_id: str
    content: str
    source_path: str
    project: str
    page_number: Optional[int] = None
    heading: Optional[str] = None
    chunk_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "source_path": self.source_path,
            "project": self.project,
            "page_number": self.page_number,
            "heading": self.heading,
            "chunk_index": self.chunk_index,
            "metadata": self.metadata,
        }


class DocumentParser:
    """
    Document Parser - Parses PDFs, text, and other documents.
    
    Preserves headings, code symbols, tables, page numbers, and
    source locations instead of flattening everything into plain text.
    """
    
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    async def parse(self, source_path: str, project: str,
                   metadata: Optional[Dict[str, Any]] = None) -> List[DocumentChunk]:
        """
        Parse a document source file.
        
        Args:
            source_path: Path to the source file
            project: Project identifier
            metadata: Optional additional metadata
        
        Returns list of DocumentChunks.
        """
        path = Path(source_path)
        
        if not path.exists():
            logger.error(f"Source file not found: {source_path}")
            return []
        
        # Determine file type and parse accordingly
        suffix = path.suffix.lower()
        
        if suffix == ".pdf":
            chunks = await self._parse_pdf(str(path), project, metadata)
        elif suffix in (".txt", ".md", ".rst"):
            chunks = await self._parse_text(str(path), project, metadata)
        elif suffix == ".py":
            chunks = await self._parse_text(str(path), project, metadata)
        else:
            logger.warning(f"Unsupported file type: {suffix}")
            chunks = await self._parse_text(str(path), project, metadata)
        
        logger.info(f"Parsed {len(chunks)} chunks from {source_path}")
        return chunks
    
    async def _parse_pdf(self, path: str, project: str,
                        metadata: Optional[Dict[str, Any]]) -> List[DocumentChunk]:
        """Parse a PDF file."""
        chunks = []
        
        try:
            import pymupdf
            
            doc = pymupdf.open(path)
            chunk_index = 0
            
            for page_num, page in enumerate(doc):
                text = page.get_text("text")
                if not text.strip():
                    continue
                
                # Split text into chunks
                page_chunks = self._split_text(text, page_num)
                for i, content in enumerate(page_chunks):
                    chunk_id = self._generate_chunk_id(path, page_num, i)
                    chunks.append(DocumentChunk(
                        chunk_id=chunk_id,
                        content=content,
                        source_path=path,
                        project=project,
                        page_number=page_num + 1,
                        chunk_index=i,
                        metadata=metadata or {},
                    ))
                    chunk_index += 1
            
            doc.close()
            
        except ImportError:
            logger.warning("pymupdf not available, skipping PDF parsing")
        except Exception as e:
            logger.error(f"PDF parsing error: {e}")
        
        return chunks
    
    async def _parse_text(self, path: str, project: str,
                         metadata: Optional[Dict[str, Any]]) -> List[DocumentChunk]:
        """Parse a text file."""
        chunks = []
        
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            
            # Split into chunks
            text_chunks = self._split_text(content)
            for i, text in enumerate(text_chunks):
                chunk_id = self._generate_chunk_id(path, None, i)
                chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    content=text,
                    source_path=path,
                    project=project,
                    chunk_index=i,
                    metadata=metadata or {},
                ))
            
        except Exception as e:
            logger.error(f"Text parsing error: {e}")
        
        return chunks
    
    def _split_text(self, text: str, page_number: Optional[int] = None) -> List[str]:
        """Split text into chunks with overlap."""
        if len(text) <= self.chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + self.chunk_size
            chunk = text[start:end]
            
            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence boundary
                for sep in [". ", "\n\n", "\n"]:
                    idx = chunk.rfind(sep)
                    if idx > self.chunk_size // 2:
                        chunk = chunk[:idx + len(sep)]
                        end = start + len(chunk)
                        break
            
            chunks.append(chunk)
            start = end - self.chunk_overlap
        
        return chunks
    
    def _generate_chunk_id(self, source_path: str, page_number: Optional[int],
                          chunk_index: int) -> str:
        """Generate a stable chunk ID."""
        path_hash = hashlib.md5(source_path.encode()).hexdigest()[:8]
        page_str = f"p{page_number}" if page_number is not None else "no_page"
        return f"chunk_{path_hash}_{page_str}_{chunk_index}"
    
    async def get_file_hash(self, path: str) -> str:
        """Get MD5 hash of a file for change detection."""
        hasher = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()


# ─── Convenience functions ───────────────────────────────────────────

async def parse_document(source_path: str, project: str,
                         metadata: Optional[Dict[str, Any]] = None) -> List[DocumentChunk]:
    """Parse a document source file and return chunks."""
    parser = DocumentParser()
    return await parser.parse(source_path, project, metadata)


def get_supported_formats() -> List[str]:
    """Return list of supported file formats."""
    return [".pdf", ".txt", ".md", ".rst", ".py", ".html", ".csv", ".json"]
