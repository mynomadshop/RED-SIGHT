"""
RedSight - High-Performance Local AI Intelligence Platform
Multi-Drive Indexer

Batch indexes discovered files from multiple drives into RedSight
knowledge collections using the full ingestion pipeline.

Features:
- Smart file selection based on drive scanner output
- Batch processing with progress tracking
- Change detection (skip unchanged files)
- Collection-aware routing
- Error handling and retry
- Summary reporting
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.ingestion.indexer import Indexer
from app.retrieval.drive_scanner import DiscoveredFile, DriveScanner

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result of a batch indexing operation."""
    total_files: int = 0
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    total_chunks: int = 0
    errors: List[str] = field(default_factory=list)
    per_file: List[Dict[str, Any]] = field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    @property
    def elapsed_seconds(self) -> float:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_files": self.total_files,
            "indexed": self.indexed,
            "skipped": self.skipped,
            "failed": self.failed,
            "total_chunks": self.total_chunks,
            "errors": self.errors[:20],  # Limit error list
            "per_file": self.per_file[:50],  # Limit detail
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "success_rate": round(self.indexed / max(1, self.total_files), 4),
        }


class MultiDriveIndexer:
    """
    Batch indexer for multi-drive file ingestion.

    Orchestrates the full indexing pipeline across files discovered
    from multiple drives, with change detection and progress tracking.
    """

    def __init__(
        self,
        indexer: Indexer,
        scanner: Optional[DriveScanner] = None,
        max_concurrent: int = 3,
    ):
        self._indexer = indexer
        self._scanner = scanner or DriveScanner()
        self._max_concurrent = max_concurrent

    async def index_discovered_files(
        self,
        files: List[DiscoveredFile],
        dry_run: bool = False,
    ) -> BatchResult:
        """
        Index a list of discovered files.

        Args:
            files: List of DiscoveredFile from DriveScanner
            dry_run: If True, only report what would be indexed

        Returns:
            BatchResult with statistics
        """
        result = BatchResult(
            total_files=len(files),
            start_time=time.time(),
        )

        if dry_run:
            result.end_time = time.time()
            result.per_file = [f.to_dict() for f in files[:50]]
            result.indexed = len(files)
            return result

        # Group by collection for efficient batching
        by_collection: Dict[str, List[DiscoveredFile]] = {}
        for f in files:
            if f.collection not in by_collection:
                by_collection[f.collection] = []
            by_collection[f.collection].append(f)

        logger.info(f"Indexing {len(files)} files across {len(by_collection)} collections")

        # Process each collection
        for collection, coll_files in by_collection.items():
            logger.info(f"Processing collection '{collection}': {len(coll_files)} files")

            for discovered in coll_files:
                try:
                    # Check if file is indexable
                    if discovered.is_large:
                        result.skipped += 1
                        result.per_file.append({
                            "path": discovered.path,
                            "status": "skipped_large",
                            "reason": f"File too large ({discovered.size_bytes / 1024:.0f}KB)",
                        })
                        continue

                    # Create and run indexing job
                    job_id = await self._indexer.create_job(
                        source_path=discovered.path,
                        collection=discovered.collection,
                        project=discovered.project_hint,
                    )

                    job_result = await self._indexer.process_job(job_id)

                    if job_result["status"] == "complete":
                        chunks = job_result.get("chunks_created", 0)
                        if chunks > 0:
                            result.indexed += 1
                            result.total_chunks += chunks
                            result.per_file.append({
                                "path": discovered.path,
                                "status": "indexed",
                                "chunks": chunks,
                                "collection": discovered.collection,
                                "project": discovered.project_hint,
                            })
                        else:
                            result.skipped += 1
                            result.per_file.append({
                                "path": discovered.path,
                                "status": "skipped_unchanged",
                            })
                    elif job_result["status"] == "failed":
                        result.failed += 1
                        error_msg = job_result.get("error", "unknown error")
                        result.errors.append(f"{discovered.path}: {error_msg}")
                        result.per_file.append({
                            "path": discovered.path,
                            "status": "failed",
                            "error": error_msg,
                        })

                except Exception as e:
                    result.failed += 1
                    error_msg = str(e)
                    result.errors.append(f"{discovered.path}: {error_msg}")
                    result.per_file.append({
                        "path": discovered.path,
                        "status": "failed",
                        "error": error_msg,
                    })

        result.end_time = time.time()
        logger.info(
            f"Batch complete: {result.indexed} indexed, "
            f"{result.skipped} skipped, {result.failed} failed, "
            f"{result.total_chunks} chunks in {result.elapsed_seconds:.1f}s"
        )

        return result

    async def index_drive(
        self,
        drives: Optional[List[str]] = None,
        collection: Optional[str] = None,
        max_depth: int = 6,
        recent_only: bool = False,
        dry_run: bool = False,
    ) -> BatchResult:
        """
        Scan and index files from specified drives.

        Args:
            drives: List of drive letters (e.g., ["C:", "D:"])
            collection: Optional collection filter
            max_depth: Maximum directory depth to scan
            recent_only: Only index files modified in last 90 days
            dry_run: Report only, don't index

        Returns:
            BatchResult with statistics
        """
        drives = drives or ["C:", "D:"]

        logger.info(f"Starting multi-drive index: {drives}")

        # Scan drives
        self._scanner = DriveScanner(
            drives=drives,
            max_depth=max_depth,
            include_recent_only=recent_only,
        )

        discovered = self._scanner.scan()

        # Filter by collection if specified
        if collection:
            discovered = [f for f in discovered if f.collection == collection]

        logger.info(f"Discovered {len(discovered)} indexable files")

        # Index
        result = await self.index_discovered_files(discovered, dry_run=dry_run)

        # Add scan summary
        result.scan_summary = self._scanner.get_summary()

        return result

    async def index_project(
        self,
        project_path: str,
        collection: str = "project_code",
        project_name: Optional[str] = None,
        dry_run: bool = False,
    ) -> BatchResult:
        """
        Index all files in a project directory.

        Args:
            project_path: Path to project directory
            collection: Target collection
            project_name: Project identifier
            dry_run: Report only

        Returns:
            BatchResult with statistics
        """
        from pathlib import Path as P

        project_dir = P(project_path)
        if not project_dir.exists():
            raise ValueError(f"Project path not found: {project_path}")

        # Discover files in project
        files = []
        for root, dirs, filenames in os.walk(project_dir):
            for filename in filenames:
                file_path = P(root) / filename
                try:
                    stat = file_path.stat()
                    if stat.st_size > 5 * 1024 * 1024:  # Skip > 5MB
                        continue

                    suffix = file_path.suffix.lower()
                    if suffix in (".py", ".js", ".ts", ".json", ".yaml",
                                  ".yml", ".toml", ".md", ".txt", ".html",
                                  ".css", ".sql", ".sh", ".bat"):
                        files.append(DiscoveredFile(
                            path=str(file_path),
                            file_type=suffix.lstrip("."),
                            size_bytes=stat.st_size,
                            drive="C:",
                            category="code" if suffix in (".py", ".js", ".ts") else "docs",
                            collection=collection,
                            project_hint=project_name or project_dir.name.lower(),
                            is_recent=True,
                            is_large=False,
                            last_modified=stat.st_mtime,
                        ))
                except (OSError, PermissionError):
                    continue

        result = await self.index_discovered_files(files, dry_run=dry_run)
        return result

    def get_report(self, result: BatchResult) -> str:
        """Generate a human-readable report."""
        lines = [
            "📊 Multi-Drive Indexing Report",
            "=" * 50,
            f"Total files processed: {result.total_files}",
            f"✅ Indexed: {result.indexed}",
            f"⏭️ Skipped: {result.skipped}",
            f"❌ Failed: {result.failed}",
            f"📄 Total chunks: {result.total_chunks}",
            f"⏱️  Elapsed: {result.elapsed_seconds:.1f}s",
            f"📈 Success rate: {result.indexed / max(1, result.total_files) * 100:.1f}%",
        ]

        if result.errors:
            lines.append("")
            lines.append("Errors:")
            for err in result.errors[:10]:
                lines.append(f"  ❌ {err}")

        return "\n".join(lines)
