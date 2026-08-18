"""
RedSight - High-Performance Local AI Intelligence Platform
Retrieval Package

Provides search and retrieval:
- Qdrant vector database client
- Hybrid search (vector + keyword)
- Metadata filtering
- Embedding loading and management
"""

from app.retrieval.qdrant_client import QdrantClientWrapper, QdrantConfig
from app.retrieval.hybrid_search import HybridSearchEngine, SearchResult
from app.retrieval.metadata_db import MetadataDB
from app.retrieval.embedding_loader import EmbeddingModelLoader

__all__ = [
    "QdrantClientWrapper",
    "QdrantConfig",
    "HybridSearchEngine",
    "SearchResult",
    "MetadataDB",
    "EmbeddingModelLoader",
]
