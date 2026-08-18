"""
RedSight - High-Performance Local AI Intelligence Platform
Golden Queries - Real Data from System

Curated evaluation queries sourced from actual system files,
projects, and operational knowledge.

Sourced from:
- C:/Users/walim/RedSight/ — platform docs
- C:/Users/walim/BrightDataMCP/ — extraction code
- C:/Users/walim/ComfyUI/ — AI workflows
- C:/Users/walim/PSX/ — trading platform
- C:/Users/walim/Hermes/ — agent system
- C:/Users/walim/DailyReports/ — BK reports
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.retrieval.golden_set import GoldenSet, GoldenQuery

logger = logging.getLogger(__name__)


def create_golden_queries() -> GoldenSet:
    """
    Create golden queries from real system data.

    Returns a GoldenSet with queries sourced from the actual
    files on the system.
    """
    gs = GoldenSet(data_dir="./data/evals")

    # ── RedSight Platform Queries ────────────────────────────────
    gs.add_query(GoldenQuery(
        query_id="rs_001",
        query_text="How does RedSight handle GPU scheduling with dual RTX 5090?",
        category="code",
        expected_chunk_ids=["gpu_scheduler"],
        expected_source_paths=["app/acceleration/gpu_scheduler.py"],
        expected_collections=["project_code"],
        difficulty="medium",
        description="Query about dual-GPU scheduler implementation",
        task_type="code",
    ))

    gs.add_query(GoldenQuery(
        query_id="rs_002",
        query_text="What are the core interfaces defined in RedSight?",
        category="docs",
        expected_chunk_ids=["interfaces"],
        expected_source_paths=["app/core/interfaces.py", "README.md"],
        expected_collections=["project_code", "knowledge_docs"],
        difficulty="easy",
        description="Query about platform architecture interfaces",
        task_type="general",
    ))

    gs.add_query(GoldenQuery(
        query_id="rs_003",
        query_text="How does the knowledge fabric work with Qdrant and SQLite?",
        category="docs",
        expected_chunk_ids=["qdrant", "metadata"],
        expected_source_paths=["app/retrieval/qdrant_client.py", "app/retrieval/metadata_db.py"],
        expected_collections=["project_code"],
        difficulty="medium",
        description="Query about RAG backend architecture",
        task_type="general",
    ))

    gs.add_query(GoldenQuery(
        query_id="rs_004",
        query_text="What is the ingestion pipeline for PDF documents?",
        category="docs",
        expected_chunk_ids=["ingestion", "parser"],
        expected_source_paths=["app/ingestion/indexer.py", "app/ingestion/parser.py"],
        expected_collections=["project_code"],
        difficulty="medium",
        description="Query about document ingestion steps",
        task_type="general",
    ))

    gs.add_query(GoldenQuery(
        query_id="rs_005",
        query_text="How does RedSight classify queries to determine which collections to search?",
        category="code",
        expected_chunk_ids=["query_classifier"],
        expected_source_paths=["app/retrieval/hybrid_search.py"],
        expected_collections=["project_code"],
        difficulty="medium",
        description="Query about query classification logic",
        task_type="general",
    ))

    # ── BrightData MCP Extraction Queries ────────────────────────
    gs.add_query(GoldenQuery(
        query_id="bd_001",
        query_text="How does the BrightData MCP extractor authenticate with RMDataCentral?",
        category="code",
        expected_chunk_ids=["auth", "extractor"],
        expected_source_paths=["BrightDataMCP/*.py"],
        expected_collections=["project_code"],
        difficulty="hard",
        description="Query about BK portal authentication flow",
        task_type="code",
    ))

    gs.add_query(GoldenQuery(
        query_id="bd_002",
        query_text="What is the workflow for extracting BK daily reports from the portal?",
        category="docs",
        expected_chunk_ids=["workflow", "rmdata"],
        expected_source_paths=["BK sent/RMDataCentral Daily Workflow.md"],
        expected_collections=["knowledge_docs"],
        difficulty="medium",
        description="Query about BK report extraction workflow",
        task_type="general",
    ))

    gs.add_query(GoldenQuery(
        query_id="bd_003",
        query_text="How to extract store-level sales data from RMDataCentral?",
        category="code",
        expected_chunk_ids=["api", "sales"],
        expected_source_paths=["BrightDataMCP/*.py", "BK sent/*.md"],
        expected_collections=["project_code", "knowledge_docs"],
        difficulty="hard",
        description="Query about BK data extraction",
        task_type="code",
    ))

    # ── ComfyUI AI Workflow Queries ──────────────────────────────
    gs.add_query(GoldenQuery(
        query_id="cu_001",
        query_text="What are the ComfyUI workflow files for image generation?",
        category="code",
        expected_chunk_ids=["workflow", "json"],
        expected_source_paths=["COMFYUI/*.json"],
        expected_collections=["project_code"],
        difficulty="medium",
        description="Query about ComfyUI node workflows",
        task_type="general",
    ))

    gs.add_query(GoldenQuery(
        query_id="cu_002",
        query_text="How to configure ComfyUI with dual GPU setup?",
        category="docs",
        expected_chunk_ids=["config", "gpu"],
        expected_source_paths=["COMFYUI/*.json", "ComfyUI-Installs/README.md"],
        expected_collections=["knowledge_docs"],
        difficulty="hard",
        description="Query about multi-GPU ComfyUI configuration",
        task_type="general",
    ))

    # ── PSX Trading Platform Queries ─────────────────────────────
    gs.add_query(GoldenQuery(
        query_id="psx_001",
        query_text="How does the PSX AutoTrader BlueSight system work?",
        category="code",
        expected_chunk_ids=["bluesight", "trading"],
        expected_source_paths=["PSX/*.py", "PSX_AutoTrader/*.py"],
        expected_collections=["project_code"],
        difficulty="hard",
        description="Query about PSX trading platform architecture",
        task_type="code",
    ))

    gs.add_query(GoldenQuery(
        query_id="psx_002",
        query_text="What stocks does the PSX monitoring system track?",
        category="docs",
        expected_chunk_ids=["monitoring", "stocks"],
        expected_source_paths=["PSX/*.md", "PSX/*.py"],
        expected_collections=["project_code"],
        difficulty="easy",
        description="Query about PSX stock monitoring",
        task_type="general",
    ))

    # ── Hermes Agent System Queries ──────────────────────────────
    gs.add_query(GoldenQuery(
        query_id="hr_001",
        query_text="How does Hermes Agent manage skills and memory?",
        category="docs",
        expected_chunk_ids=["skills", "memory"],
        expected_source_paths=["Hermes/**/*.md", ".hermes/**/*.md"],
        expected_collections=["knowledge_docs"],
        difficulty="medium",
        description="Query about Hermes skill and memory system",
        task_type="general",
    ))

    gs.add_query(GoldenQuery(
        query_id="hr_002",
        query_text="What cron job patterns does Hermes support?",
        category="docs",
        expected_chunk_ids=["cron", "scheduling"],
        expected_source_paths=["Hermes/**/*.md"],
        expected_collections=["knowledge_docs"],
        difficulty="medium",
        description="Query about Hermes scheduling system",
        task_type="general",
    ))

    # ── BK Operations Queries ────────────────────────────────────
    gs.add_query(GoldenQuery(
        query_id="bk_001",
        query_text="How are BK daily reports generated and what data do they contain?",
        category="docs",
        expected_chunk_ids=["daily_report", "bk"],
        expected_source_paths=["DailyReports/*.pdf", "BK sent/*.md"],
        expected_collections=["knowledge_docs"],
        difficulty="easy",
        description="Query about BK daily reporting",
        task_type="general",
    ))

    gs.add_query(GoldenQuery(
        query_id="bk_002",
        query_text="What is the PAR OPS reporting pipeline?",
        category="docs",
        expected_chunk_ids=["par_ops", "pipeline"],
        expected_source_paths=["Downloads/PAR_OPS_Reporting_Pipeline_Runbook.pdf"],
        expected_collections=["knowledge_docs"],
        difficulty="medium",
        description="Query about PAR OPS data pipeline",
        task_type="general",
    ))

    # ── Cross-Project Architecture Queries ───────────────────────
    gs.add_query(GoldenQuery(
        query_id="arch_001",
        query_text="What Python projects exist on this system?",
        category="code",
        expected_chunk_ids=["projects", "overview"],
        expected_source_paths=["*/README.md"],
        expected_collections=["project_code", "knowledge_docs"],
        difficulty="easy",
        description="Query about project inventory",
        task_type="general",
    ))

    gs.add_query(GoldenQuery(
        query_id="arch_002",
        query_text="How does the system use LM Studio for local model inference?",
        category="docs",
        expected_chunk_ids=["lmstudio", "inference"],
        expected_source_paths=["app/models/lmstudio.py", "*.md"],
        expected_collections=["project_code", "knowledge_docs"],
        difficulty="medium",
        description="Query about LM Studio integration",
        task_type="general",
    ))

    return gs


def save_golden_queries(filepath: Optional[str] = None) -> str:
    """Create and save golden queries to file."""
    gs = create_golden_queries()
    return gs.save_to_file(filepath)


# Import Optional
from typing import Optional
