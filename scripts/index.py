"""
RedSight - High-Performance Local AI Intelligence Platform
Index Script

Command-line indexing utility.

Usage:
    redsight-index --path ./projects/bluesight --collection project_code
    redsight-index --path ./docs/report.pdf --collection knowledge_docs
    redsight-index --path . --collection project_code --project redsight
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import List

import typer

app = typer.Typer(help="RedSight Knowledge Indexer")

logger = logging.getLogger("redsight.index")


def _collect_files(path: str, extensions: List[str] = None) -> List[str]:
    """Collect files from a path (file or directory)."""
    p = Path(path)
    if p.is_file():
        return [str(p)]

    if not p.is_dir():
        typer.echo(f"Error: Path not found: {path}", err=True)
        sys.exit(1)

    allowed = extensions or [".pdf", ".txt", ".md", ".rst", ".py", ".json", ".yaml", ".yml", ".csv"]
    files = []
    for ext in allowed:
        files.extend(str(f) for f in p.rglob(f"*{ext}"))

    # Also get all files if no extensions matched
    if not files:
        files = [str(f) for f in p.rglob("*") if f.is_file()]

    return sorted(files)


@app.command()
def main(
    path: str = typer.Option(..., "--path", "-p", help="Path to index (file or directory)"),
    collection: str = typer.Option("knowledge_docs", "--collection", "-c", help="Target collection"),
    project: str = typer.Option("default", "--project", "-j", help="Project identifier"),
    skip_existing: bool = typer.Option(True, "--skip-existing", help="Skip unchanged files"),
    embeddings: str = typer.Option(
        "local", "--embeddings", "-e", help="Embedding backend: local, lmstudio, none"
    ),
    lmstudio_url: str = typer.Option(
        "http://127.0.0.1:1234/v1", "--lmstudio-url", help="LM Studio API URL"
    ),
    model_name: str = typer.Option(
        "sentence-transformers/all-MiniLM-L6-v2", "--model", help="Local embedding model name"
    ),
    chunk_size: int = typer.Option(512, "--chunk-size", help="Chunk size in characters"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Index a folder or file into the RedSight knowledge base."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    typer.echo(f"📚 RedSight Indexer")
    typer.echo(f"   Path: {path}")
    typer.echo(f"   Collection: {collection}")
    typer.echo(f"   Project: {project}")
    typer.echo(f"   Embeddings: {embeddings}")
    typer.echo()

    # Collect files
    files = _collect_files(path)
    typer.echo(f"📄 Found {len(files)} files to index")

    if not files:
        typer.echo("No files found. Exiting.")
        return

    async def run_indexing():
        # Import here to avoid heavy imports on CLI help
        from app.retrieval.qdrant_client import QdrantClientWrapper
        from app.retrieval.metadata_db import MetadataDB
        from app.retrieval.embedding_loader import EmbeddingModelLoader
        from app.ingestion.indexer import Indexer

        # 1. Initialize Qdrant
        typer.echo("⚡ Initializing Qdrant...")
        qdrant = QdrantClientWrapper(
            host="127.0.0.1",
            port=6333,
            embedded=True,  # Embedded mode for CLI
        )
        if not await qdrant.connect():
            typer.echo("❌ Failed to connect to Qdrant")
            return
        await qdrant.ensure_collections()
        typer.echo("✅ Qdrant ready")

        # 2. Initialize SQLite metadata DB
        typer.echo("🗄️  Initializing metadata database...")
        metadata = MetadataDB(db_path="./data/metadata.db")
        if not await metadata.init_db():
            typer.echo("❌ Failed to initialize metadata DB")
            return
        typer.echo("✅ Metadata DB ready")

        # 3. Load embedding model (optional)
        embedding_model = None
        if embeddings != "none":
            typer.echo(f"🧠 Loading embeddings ({embeddings})...")
            loader = EmbeddingModelLoader(
                model_name=model_name,
                lmstudio_url=lmstudio_url if embeddings == "lmstudio" else None,
            )
            if await loader.load():
                embedding_model = loader.model
                typer.echo(f"✅ Embeddings: {loader.get_info()}")
            else:
                typer.echo("⚠️  No embedding model available — indexing without vectors")

        # 4. Create indexer
        indexer = Indexer(
            qdrant=qdrant,
            metadata_db=metadata,
            embedding_model=embedding_model,
            chunk_size=chunk_size,
        )

        # 5. Index files
        typer.echo()
        typer.echo(f"🚀 Indexing {len(files)} files...")
        typer.echo()

        results = await indexer.index_files(files, collection, project)

        # 6. Summary
        typer.echo()
        typer.echo("📊 Indexing Summary")
        typer.echo("-" * 40)
        total_chunks = 0
        success = 0
        failed = 0
        skipped = 0

        for r in results:
            if r["status"] == "complete":
                if r["chunks_created"] == 0:
                    skipped += 1
                else:
                    success += 1
                    total_chunks += r["chunks_created"]
            elif r["status"] == "failed":
                failed += 1
                typer.echo(f"  ❌ {r['source_path']}: {r.get('error', 'unknown')}")

        typer.echo(f"  ✅ Success: {success} files, {total_chunks} chunks")
        typer.echo(f"  ⏭️  Skipped: {skipped} unchanged files")
        typer.echo(f"  ❌ Failed: {failed} files")
        typer.echo()

        # Show collection stats
        stats = await qdrant.get_collection_stats(collection)
        typer.echo(f"Collection '{collection}': {stats.get('points_count', 0)} points")

        # Close connections
        await qdrant.close()
        await metadata.close()

    asyncio.run(run_indexing())


if __name__ == "__main__":
    app()
