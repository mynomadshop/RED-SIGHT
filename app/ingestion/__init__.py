"""
RedSight - High-Performance Local AI Intelligence Platform
Ingestion Package

Provides data ingestion and indexing:
- File parsing (PDF, DOCX, TXT, CSV, etc.)
- Text chunking and tokenization
- Vector and text indexing
- Metadata extraction
"""

from app.ingestion.parser import DocumentParser, parse_document, get_supported_formats
from app.ingestion.indexer import (
    Indexer,
    IndexConfig,
    TextIndex,
    VectorIndex,
    IndexResult,
    IndexStats,
)

__all__ = [
    "DocumentParser",
    "parse_document",
    "get_supported_formats",
    "Indexer",
    "IndexConfig",
    "TextIndex",
    "VectorIndex",
    "IndexResult",
    "IndexStats",
]
