"""
RedSight - High-Performance Local AI Intelligence Platform
SQLite Metadata Database

Persistent source registry with SQLAlchemy. Tracks:
- Source files (path, hash, type, project, checksum)
- Chunks (content, position, collection, provenance)
- Index versions (parser version, embedding version, timestamp)
- Job tracking (status, errors, timing)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Relationship,
    sessionmaker,
    relationship,
)

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# ─── SQLAlchemy Models ───────────────────────────────────────────


class SourceFile(Base):
    """Canonical source file record."""

    __tablename__ = "source_files"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)
    source_path: Mapped[str] = Column(Text, unique=True, nullable=False, index=True)
    file_hash: Mapped[str] = Column(String(64), nullable=False, index=True)
    file_type: Mapped[str] = Column(String(20), nullable=False)  # pdf, txt, md, py, etc.
    project: Mapped[str] = Column(String(100), nullable=False, index=True)
    access_scope: Mapped[str] = Column(String(20), default="internal")
    size_bytes: Mapped[int] = Column(Integer, default=0)
    created_at: Mapped[float] = Column(DateTime, server_default=func.now())
    updated_at: Mapped[float] = Column(DateTime, server_default=func.now(), onupdate=func.now())

    chunks: Mapped[List["Chunk"]] = relationship("Chunk", back_populates="source", cascade="all, delete-orphan")
    jobs: Mapped[List["IndexJob"]] = relationship("IndexJob", back_populates="source")


class Chunk(Base):
    """Indexed content chunk with provenance."""

    __tablename__ = "chunks"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = Column(String(100), unique=True, nullable=False, index=True)
    source_file_id: Mapped[int] = Column(Integer, ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False)
    collection: Mapped[str] = Column(String(50), nullable=False, index=True)
    content: Mapped[str] = Column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = Column(Integer, nullable=True)
    heading: Mapped[Optional[str]] = Column(String(500), nullable=True)
    chunk_index: Mapped[int] = Column(Integer, default=0)
    offset_start: Mapped[Optional[int]] = Column(Integer, nullable=True)
    offset_end: Mapped[Optional[int]] = Column(Integer, nullable=True)
    embedding_version: Mapped[str] = Column(String(50), default="unknown")
    parser_version: Mapped[str] = Column(String(50), default="unknown")
    created_at: Mapped[float] = Column(DateTime, server_default=func.now())

    source: Mapped["SourceFile"] = relationship("SourceFile", back_populates="chunks")


class IndexVersion(Base):
    """Tracks index versions for rollback support."""

    __tablename__ = "index_versions"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = Column(Integer, unique=True, nullable=False)
    collection: Mapped[str] = Column(String(50), nullable=False, index=True)
    parser_version: Mapped[str] = Column(String(50), nullable=False)
    embedding_model: Mapped[str] = Column(String(200), nullable=False)
    embedding_version: Mapped[str] = Column(String(50), nullable=False)
    points_count: Mapped[int] = Column(Integer, default=0)
    created_at: Mapped[float] = Column(DateTime, server_default=func.now())
    is_active: Mapped[bool] = Column(Boolean, default=False)


class IndexJob(Base):
    """Indexing job tracking."""

    __tablename__ = "index_jobs"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = Column(String(20), unique=True, nullable=False, index=True)
    source_file_id: Mapped[int] = Column(Integer, ForeignKey("source_files.id"), nullable=True)
    collection: Mapped[str] = Column(String(50), nullable=False)
    project: Mapped[str] = Column(String(100), nullable=False)
    status: Mapped[str] = Column(String(20), default="pending")  # pending, processing, complete, failed
    chunks_created: Mapped[int] = Column(Integer, default=0)
    error: Mapped[Optional[str]] = Column(Text, nullable=True)
    started_at: Mapped[Optional[float]] = Column(Float, nullable=True)
    completed_at: Mapped[Optional[float]] = Column(Float, nullable=True)
    created_at: Mapped[float] = Column(DateTime, server_default=func.now())

    source: Mapped["SourceFile"] = relationship("SourceFile", back_populates="jobs")


# ─── MetadataDB Class ────────────────────────────────────────────


class MetadataDB:
    """
    SQLite metadata database for source registry, chunk tracking,
    index versions, and job management.
    """

    def __init__(self, db_path: str = "./data/metadata.db"):
        self._db_path = db_path
        self._engine = None
        self._session_factory = None

    async def init_db(self) -> bool:
        """Initialize the database and create tables."""
        try:
            # Ensure parent directory exists
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

            self._engine = create_engine(
                f"sqlite:///{self._db_path}",
                echo=False,
                connect_args={"timeout": 30},
            )
            Base.metadata.create_all(self._engine)
            self._session_factory = sessionmaker(bind=self._engine)
            logger.info(f"SQLite metadata DB initialized at {self._db_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize metadata DB: {e}")
            return False

    def _session(self):
        """Get a new database session."""
        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call init_db() first.")
        return self._session_factory()

    # ── Source File Operations ──────────────────────────────────

    async def get_or_create_source(self, source_path: str, project: str,
                                    file_hash: str) -> Optional[int]:
        """Get existing source file ID or create new record."""
        session = self._session()
        try:
            source = session.query(SourceFile).filter_by(source_path=source_path).first()
            if source:
                return source.id

            # Determine file type
            from pathlib import Path as P
            suffix = P(source_path).suffix.lower().lstrip(".")
            file_type = suffix or "unknown"

            # Get file size
            try:
                size_bytes = Path(source_path).stat().st_size
            except OSError:
                size_bytes = 0

            source = SourceFile(
                source_path=source_path,
                file_hash=file_hash,
                file_type=file_type,
                project=project,
                size_bytes=size_bytes,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
            logger.info(f"Created source record: {source_path} (id={source.id})")
            return source.id
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create source record: {e}")
            return None
        finally:
            session.close()

    async def get_source_by_path(self, source_path: str) -> Optional[Dict[str, Any]]:
        """Get source file metadata by path."""
        session = self._session()
        try:
            source = session.query(SourceFile).filter_by(source_path=source_path).first()
            if not source:
                return None
            return {
                "id": source.id,
                "source_path": source.source_path,
                "file_hash": source.file_hash,
                "file_type": source.file_type,
                "project": source.project,
                "access_scope": source.access_scope,
                "size_bytes": source.size_bytes,
                "created_at": source.created_at,
                "updated_at": source.updated_at,
            }
        finally:
            session.close()

    async def check_hash_changed(self, source_path: str, new_hash: str) -> bool:
        """Check if a file's hash has changed since last indexed."""
        session = self._session()
        try:
            source = session.query(SourceFile).filter_by(source_path=source_path).first()
            if not source:
                return True  # New file, needs indexing
            return source.file_hash != new_hash
        finally:
            session.close()

    # ── Chunk Operations ────────────────────────────────────────

    async def upsert_chunk(self, chunk_id: str, source_file_id: int,
                           collection: str, content: str,
                           page_number: Optional[int] = None,
                           heading: Optional[str] = None,
                           chunk_index: int = 0,
                           embedding_version: str = "unknown",
                           parser_version: str = "unknown",
                           offset_start: Optional[int] = None,
                           offset_end: Optional[int] = None) -> bool:
        """Insert or update a chunk record."""
        session = self._session()
        try:
            existing = session.query(Chunk).filter_by(chunk_id=chunk_id).first()
            if existing:
                # Update existing
                existing.content = content
                existing.page_number = page_number
                existing.heading = heading
                existing.chunk_index = chunk_index
                existing.embedding_version = embedding_version
                existing.parser_version = parser_version
                existing.offset_start = offset_start
                existing.offset_end = offset_end
            else:
                chunk = Chunk(
                    chunk_id=chunk_id,
                    source_file_id=source_file_id,
                    collection=collection,
                    content=content,
                    page_number=page_number,
                    heading=heading,
                    chunk_index=chunk_index,
                    embedding_version=embedding_version,
                    parser_version=parser_version,
                    offset_start=offset_start,
                    offset_end=offset_end,
                )
                session.add(chunk)

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to upsert chunk {chunk_id}: {e}")
            return False
        finally:
            session.close()

    async def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a chunk by its ID."""
        session = self._session()
        try:
            chunk = session.query(Chunk).filter_by(chunk_id=chunk_id).first()
            if not chunk:
                return None
            return {
                "chunk_id": chunk.chunk_id,
                "content": chunk.content,
                "collection": chunk.collection,
                "page_number": chunk.page_number,
                "heading": chunk.heading,
                "chunk_index": chunk.chunk_index,
                "embedding_version": chunk.embedding_version,
                "parser_version": chunk.parser_version,
                "offset_start": chunk.offset_start,
                "offset_end": chunk.offset_end,
            }
        finally:
            session.close()

    async def get_chunks_for_source(self, source_file_id: int) -> List[Dict[str, Any]]:
        """Get all chunks for a source file."""
        session = self._session()
        try:
            chunks = session.query(Chunk).filter_by(source_file_id=source_file_id).all()
            return [
                {
                    "chunk_id": c.chunk_id,
                    "content": c.content,
                    "collection": c.collection,
                    "page_number": c.page_number,
                    "heading": c.heading,
                    "chunk_index": c.chunk_index,
                }
                for c in chunks
            ]
        finally:
            session.close()

    async def delete_chunks_for_collection(self, collection: str) -> int:
        """Delete all chunks in a collection (for re-indexing)."""
        session = self._session()
        try:
            count = session.query(Chunk).filter_by(collection=collection).delete()
            session.commit()
            logger.info(f"Deleted {count} chunks from collection '{collection}'")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete chunks: {e}")
            return 0
        finally:
            session.close()

    # ── Index Version Operations ────────────────────────────────

    async def create_index_version(self, collection: str, parser_version: str,
                                    embedding_model: str, embedding_version: str,
                                    points_count: int = 0) -> Optional[int]:
        """Create a new index version record."""
        session = self._session()
        try:
            # Deactivate previous active version for this collection
            session.query(IndexVersion).filter_by(
                collection=collection, is_active=True
            ).update({"is_active": False})

            # Get next version number for this collection
            max_ver = (
                session.query(func.max(IndexVersion.version))
                .filter_by(collection=collection)
                .scalar()
            )
            next_version = (max_ver or 0) + 1

            version = IndexVersion(
                version=next_version,
                collection=collection,
                parser_version=parser_version,
                embedding_model=embedding_model,
                embedding_version=embedding_version,
                points_count=points_count,
                is_active=True,
            )
            session.add(version)
            session.commit()
            session.refresh(version)
            logger.info(f"Created index version {version.id} for '{collection}'")
            return version.id
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create index version: {e}")
            return None
        finally:
            session.close()

    async def get_active_version(self, collection: str) -> Optional[Dict[str, Any]]:
        """Get the active index version for a collection."""
        session = self._session()
        try:
            version = session.query(IndexVersion).filter_by(
                collection=collection, is_active=True
            ).first()
            if not version:
                return None
            return {
                "id": version.id,
                "version": version.version,
                "collection": version.collection,
                "parser_version": version.parser_version,
                "embedding_model": version.embedding_model,
                "embedding_version": version.embedding_version,
                "points_count": version.points_count,
                "created_at": version.created_at,
                "is_active": version.is_active,
            }
        finally:
            session.close()

    async def rollback_to_version(self, collection: str, target_version_id: int) -> bool:
        """Rollback a collection to a specific index version."""
        session = self._session()
        try:
            target = session.query(IndexVersion).filter_by(
                id=target_version_id, collection=collection
            ).first()
            if not target:
                return False

            # Delete current active version data
            await self.delete_chunks_for_collection(collection)

            # Activate target version
            session.query(IndexVersion).filter_by(
                collection=collection, is_active=True
            ).update({"is_active": False})
            target.is_active = True
            session.commit()

            logger.info(f"Rolled back '{collection}' to version {target.id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Rollback failed: {e}")
            return False
        finally:
            session.close()

    # ── Job Operations ──────────────────────────────────────────

    async def create_job(self, job_id: str, source_file_id: Optional[int],
                         collection: str, project: str) -> bool:
        """Create a new indexing job record."""
        session = self._session()
        try:
            job = IndexJob(
                job_id=job_id,
                source_file_id=source_file_id,
                collection=collection,
                project=project,
                status="pending",
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create job: {e}")
            return False
        finally:
            session.close()

    async def update_job(self, job_id: str, **kwargs) -> bool:
        """Update job status and fields."""
        session = self._session()
        try:
            job = session.query(IndexJob).filter_by(job_id=job_id).first()
            if not job:
                return False
            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update job {job_id}: {e}")
            return False
        finally:
            session.close()

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job details."""
        session = self._session()
        try:
            job = session.query(IndexJob).filter_by(job_id=job_id).first()
            if not job:
                return None
            return {
                "job_id": job.job_id,
                "collection": job.collection,
                "project": job.project,
                "status": job.status,
                "chunks_created": job.chunks_created,
                "error": job.error,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
            }
        finally:
            session.close()

    async def list_jobs(self, status: Optional[str] = None,
                        limit: int = 50) -> List[Dict[str, Any]]:
        """List indexing jobs."""
        session = self._session()
        try:
            query = session.query(IndexJob)
            if status:
                query = query.filter_by(status=status)
            jobs = query.order_by(IndexJob.created_at.desc()).limit(limit).all()
            return [
                {
                    "job_id": j.job_id,
                    "collection": j.collection,
                    "project": j.project,
                    "status": j.status,
                    "chunks_created": j.chunks_created,
                    "error": j.error,
                    "started_at": j.started_at,
                    "completed_at": j.completed_at,
                }
                for j in jobs
            ]
        finally:
            session.close()

    # ── Collection Stats ────────────────────────────────────────

    async def get_collection_stats(self, collection: str) -> Dict[str, Any]:
        """Get statistics for a collection."""
        session = self._session()
        try:
            chunk_count = session.query(Chunk).filter_by(collection=collection).count()
            versions = (
                session.query(IndexVersion)
                .filter_by(collection=collection)
                .order_by(IndexVersion.created_at.desc())
                .all()
            )
            return {
                "collection": collection,
                "total_chunks": chunk_count,
                "version_count": len(versions),
                "versions": [
                    {
                        "id": v.id,
                        "version": v.version,
                        "parser_version": v.parser_version,
                        "embedding_model": v.embedding_model,
                        "points_count": v.points_count,
                        "is_active": v.is_active,
                        "created_at": v.created_at,
                    }
                    for v in versions
                ],
            }
        finally:
            session.close()

    # ── Full Stats ──────────────────────────────────────────────

    async def get_stats(self) -> Dict[str, Any]:
        """Get overall database statistics."""
        session = self._session()
        try:
            source_count = session.query(SourceFile).count()
            chunk_count = session.query(Chunk).count()
            job_count = session.query(IndexJob).count()
            version_count = session.query(IndexVersion).count()

            # Chunks by collection
            from sqlalchemy import text
            result = session.execute(
                text("SELECT collection, COUNT(*) as cnt FROM chunks GROUP BY collection")
            )
            by_collection = {row[0]: row[1] for row in result}

            return {
                "source_files": source_count,
                "chunks": chunk_count,
                "jobs": job_count,
                "index_versions": version_count,
                "chunks_by_collection": by_collection,
            }
        finally:
            session.close()

    async def close(self):
        """Close the database connection."""
        if self._engine:
            self._engine.dispose()
            logger.info("SQLite metadata DB closed")
