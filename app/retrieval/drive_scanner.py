"""
RedSight - High-Performance Local AI Intelligence Platform
Smart Drive Scanner

Discovers and categorizes files from multiple drives (C:, D:, etc.)
into RedSight knowledge collections.

Strategy:
1. Walk specified drives with smart filters (skip system dirs, large files)
2. Classify files by type, size, recency, and content hints
3. Assign to collections based on file type and location
4. Generate a report of discoverable files by category
5. Support incremental scanning with hash-based change detection

Collections mapping:
- knowledge_docs → PDFs, TXT, MD, DOCX
- project_code → Python, JS, TS, JSON, YAML, TOML
- project_decisions → README, ARCHITECTURE, DESIGN docs
- skills_index → SKILL.md, workflow files
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ─── File Classification ───────────────────────────────────────────────

@dataclass
class DiscoveredFile:
    """A file discovered on a drive."""
    path: str
    file_type: str  # pdf, py, md, txt, json, etc.
    size_bytes: int
    drive: str  # C:, D:, etc.
    category: str  # code, docs, decisions, skills, config, data, media
    collection: str  # target RedSight collection
    project_hint: str  # inferred project name
    is_recent: bool  # modified in last 90 days
    is_large: bool  # > 10MB (skip for indexing)
    checksum: Optional[str] = None
    last_modified: Optional[float] = None
    depth_from_root: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
            "drive": self.drive,
            "category": self.category,
            "collection": self.collection,
            "project_hint": self.project_hint,
            "is_recent": self.is_recent,
            "is_large": self.is_large,
            "checksum": self.checksum,
            "last_modified": self.last_modified,
            "depth_from_root": self.depth_from_root,
        }


# ─── File Type Mappings ────────────────────────────────────────────────

DOCUMENT_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".rst", ".doc", ".docx", ".odt", ".rtf",
    ".tex", ".epub", ".csv", ".tsv",
}

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss",
    ".java", ".kt", ".kt", ".swift", ".go", ".rs", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".scala", ".r", ".m",
    ".sh", ".bash", ".zsh", ".bat", ".ps1", ".sql",
}

CONFIG_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".env", ".gitignore", ".dockerignore", ".editorconfig",
    ".xml", ".properties",
}

SKILL_EXTENSIONS = {
    ".md",  # SKILL.md files
}

MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".jpg", ".jpeg", ".png", ".gif",
    ".webp", ".bmp", ".svg", ".mp3", ".wav", ".flac",
}

SKIP_PATTERNS: Set[str] = {
    # Directories to skip
    "node_modules", "__pycache__", ".git", ".hg", ".svn",
    "venv", ".venv", "env", ".env", "dist", "build", "target",
    ".next", ".nuxt", ".output", ".cache", ".pytest_cache",
    ".mypy_cache", ".ruff_cache",
    "site-packages", "egg-info", ".eggs",
    "venv", "virtualenv",
    # Hidden/system
    ".config", ".cache", ".local", ".npm", ".nvm",
    # Large model directories
    "models", "checkpoints", "snapshots",
}

SKIP_FILE_PATTERNS: Set[str] = {
    # Skip large binary files
    ".dll", ".exe", ".so", ".dylib", ".a", ".lib",
    ".db", ".sqlite", ".sqlite3",  # DBs (handled separately)
    ".log", ".tmp", ".temp",
    ".crdownload", ".part",  # Incomplete downloads
}

# Size thresholds
MAX_DOC_SIZE = 50 * 1024 * 1024  # 50MB for documents
MAX_CODE_SIZE = 5 * 1024 * 1024   # 5MB for code files
LARGE_THRESHOLD = 10 * 1024 * 1024  # 10MB general threshold
RECENT_DAYS = 90


def classify_file(path: Path) -> Tuple[str, str, str]:
    """
    Classify a file by extension.

    Returns (file_type, category, collection).
    """
    suffix = path.suffix.lower()

    # Document files
    if suffix in DOCUMENT_EXTENSIONS:
        if suffix in (".py",):
            return ("py", "code", "project_code")
        if suffix in (".md",):
            # Check if it's a README/decision doc
            name = path.stem.lower()
            if name in ("readme", "architecture", "design", "spec", "blueprint"):
                return ("md", "decisions", "project_decisions")
            if "skill" in name or name == "skill":
                return ("md", "skills", "skills_index")
            return ("md", "docs", "knowledge_docs")
        return (suffix.lstrip("."), "docs", "knowledge_docs")

    # Code files
    if suffix in CODE_EXTENSIONS:
        return (suffix.lstrip("."), "code", "project_code")

    # Config files
    if suffix in CONFIG_EXTENSIONS:
        return (suffix.lstrip("."), "config", "knowledge_docs")

    # Media files (skip for indexing)
    if suffix in MEDIA_EXTENSIONS:
        return (suffix.lstrip("."), "media", "skip")

    return ("unknown", "other", "skip")


def infer_project(path: Path, drive: str) -> str:
    """
    Infer project name from file path.

    Examples:
    - C:/Users/walim/RedSight/app/server.py → "redsight"
    - C:/Users/walim/BrightDataMCP/extract.py → "brightdatamcp"
    - D:/Users/walim/COMFYUI/main.py → "comfyui"
    """
    # Get relative path from user home
    try:
        home = Path.home()
        rel = path.relative_to(home)
    except ValueError:
        # File not under home, use parent dir
        return path.parent.name.lower().replace(" ", "_")

    parts = rel.parts
    if len(parts) >= 2:
        # Use the first directory after home as project name
        return parts[0].lower().replace(" ", "_").replace("-", "_")

    return path.parent.name.lower()


def compute_checksum(path: Path, max_bytes: int = 8192) -> str:
    """Compute MD5 checksum of file (first N bytes for speed)."""
    try:
        hasher = hashlib.md5()
        with open(path, "rb") as f:
            data = f.read(min(max_bytes, path.stat().st_size))
            hasher.update(data)
        return hasher.hexdigest()
    except (OSError, PermissionError):
        return ""


class DriveScanner:
    """
    Smart drive scanner that discovers and categorizes files.

    Scans specified drives, classifies files, and generates
    a structured report of discoverable content.
    """

    def __init__(
        self,
        drives: Optional[List[str]] = None,
        max_depth: int = 6,
        include_recent_only: bool = False,
    ):
        self.drives = drives or ["C:", "D:"]
        self.max_depth = max_depth
        self.include_recent_only = include_recent_only
        self._discovered: List[DiscoveredFile] = []
        self._scan_stats: Dict[str, Any] = {}

    def scan(self) -> List[DiscoveredFile]:
        """
        Scan all configured drives and return discovered files.

        Returns list of DiscoveredFile objects sorted by priority:
        1. Recent documents (last 90 days)
        2. Code files
        3. Configuration files
        """
        self._discovered = []
        scan_start = time.time()

        for drive in self.drives:
            self._scan_drive(drive)

        # Sort by priority
        self._discovered.sort(key=lambda f: (
            0 if f.is_recent else 1,
            0 if f.collection != "skip" else 1,
            -f.size_bytes,
        ))

        elapsed = time.time() - scan_start
        self._scan_stats = {
            "drives_scanned": len(self.drives),
            "total_files_found": len(self._discovered),
            "total_size_bytes": sum(f.size_bytes for f in self._discovered),
            "by_collection": self._count_by_collection(),
            "by_category": self._count_by_category(),
            "scan_time_seconds": round(elapsed, 2),
        }

        logger.info(
            f"Drive scan complete: {len(self._discovered)} files, "
            f"{self._scan_stats['total_size_bytes'] / 1024 / 1024:.1f}MB in {elapsed:.1f}s"
        )

        return self._discovered

    def _scan_drive(self, drive: str) -> None:
        """Scan a single drive."""
        drive_path = Path(drive)

        if not drive_path.exists():
            logger.warning(f"Drive not found: {drive}")
            return

        logger.info(f"Scanning {drive}...")
        files_found = 0

        for root, dirs, files in os.walk(drive_path):
            root_path = Path(root)

            # Check depth
            try:
                rel = root_path.relative_to(drive_path)
                depth = len(rel.parts)
            except ValueError:
                depth = 0

            if depth > self.max_depth:
                dirs.clear()  # Don't descend further
                continue

            # Skip unwanted directories
            dirs[:] = [
                d for d in dirs
                if d not in SKIP_PATTERNS
                and not d.startswith(".")
            ]

            for filename in files:
                # Skip unwanted file patterns
                if any(filename.endswith(ext) for ext in SKIP_FILE_PATTERNS):
                    continue

                file_path = root_path / filename

                try:
                    stat = file_path.stat()
                    size = stat.st_size
                    mtime = stat.st_mtime
                except (OSError, PermissionError):
                    continue

                # Skip large files
                if size > LARGE_THRESHOLD:
                    continue

                # Classify
                suffix = file_path.suffix.lower()
                file_type, category, collection = classify_file(file_path)

                if collection == "skip":
                    continue

                # Check recency
                is_recent = (time.time() - mtime) < (RECENT_DAYS * 86400)

                # Skip old files if configured
                if self.include_recent_only and not is_recent:
                    continue

                # Infer project
                project_hint = infer_project(file_path, drive)

                # Compute checksum
                checksum = compute_checksum(file_path) if collection != "skip" else None

                discovered = DiscoveredFile(
                    path=str(file_path),
                    file_type=file_type,
                    size_bytes=size,
                    drive=drive,
                    category=category,
                    collection=collection,
                    project_hint=project_hint,
                    is_recent=is_recent,
                    is_large=size > LARGE_THRESHOLD,
                    checksum=checksum,
                    last_modified=mtime,
                    depth_from_root=depth,
                )

                self._discovered.append(discovered)
                files_found += 1

        logger.info(f"  {drive}: {files_found} files found")

    def get_report(self) -> Dict[str, Any]:
        """Get a comprehensive scan report."""
        if not self._discovered:
            return {"error": "No scan performed. Call scan() first."}

        return {
            **self._scan_stats,
            "files": [f.to_dict() for f in self._discovered],
            "by_project": self._count_by_project(),
            "by_drive": self._count_by_drive(),
            "recent_files": [f.to_dict() for f in self._discovered if f.is_recent][:100],
        }

    def get_indexable_files(
        self,
        collection: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[DiscoveredFile]:
        """Get files that should be indexed, with optional filters."""
        files = self._discovered

        if collection:
            files = [f for f in files if f.collection == collection]

        if project:
            files = [f for f in files if f.project_hint == project]

        # Prioritize: recent > all, docs > code > config
        return files

    def _count_by_collection(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in self._discovered:
            counts[f.collection] = counts.get(f.collection, 0) + 1
        return counts

    def _count_by_category(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in self._discovered:
            counts[f.category] = counts.get(f.category, 0) + 1
        return counts

    def _count_by_project(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in self._discovered:
            counts[f.project_hint] = counts.get(f.project_hint, 0) + 1
        return counts

    def _count_by_drive(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in self._discovered:
            counts[f.drive] = counts.get(f.drive, 0) + 1
        return counts

    def get_summary(self) -> str:
        """Get a human-readable summary of the scan."""
        if not self._discovered:
            return "No files discovered. Run scan() first."

        lines = [
            "📊 Drive Scan Summary",
            "=" * 50,
            f"Drives scanned: {', '.join(self.drives)}",
            f"Total files: {len(self._discovered):,}",
            f"Total size: {sum(f.size_bytes for f in self._discovered) / 1024 / 1024:.1f} MB",
            f"Recent files (90d): {sum(1 for f in self._discovered if f.is_recent):,}",
            "",
            "By Collection:",
        ]

        for coll, count in sorted(self._count_by_collection().items(), key=lambda x: -x[1]):
            lines.append(f"  {coll}: {count:,}")

        lines.append("")
        lines.append("By Category:")
        for cat, count in sorted(self._count_by_category().items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: {count:,}")

        lines.append("")
        lines.append("Top Projects:")
        for proj, count in sorted(self._count_by_project().items(), key=lambda x: -x[1])[:10]:
            lines.append(f"  {proj}: {count:,}")

        return "\n".join(lines)
