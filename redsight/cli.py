"""
RedSight - High-Performance Local AI Intelligence Platform
CLI Entry Point

Command-line interface for RedSight operations.
"""

import typer
from typing import Optional

app = typer.Typer(
    name="redsight",
    help="High-Performance Local AI Intelligence Platform",
    add_completion=False,
)


@app.command()
def server(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to listen on"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload"),
):
    """Start the RedSight API server."""
    import uvicorn
    from app.server import app
    
    typer.echo(f"Starting RedSight server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, reload=reload)


@app.command()
def ui():
    """Start the RedSight desktop UI."""
    from ui.command_center import main
    main()


@app.command()
def index(
    path: str = typer.Option(..., "--path", "-p", help="Path to index"),
    collection: str = typer.Option("knowledge_docs", "--collection", "-c", help="Target collection"),
    project: str = typer.Option("default", "--project", "-j", help="Project identifier"),
):
    """Index a folder or file into the knowledge base."""
    from app.ingestion.indexer import Indexer
    from app.ingestion.parser import DocumentParser
    
    typer.echo(f"Indexing {path} to collection '{collection}' (project: '{project}')")
    
    indexer = Indexer()
    import asyncio
    
    async def do_index():
        job_id = await indexer.create_job(path, collection, project)
        result = await indexer.process_job(job_id)
        typer.echo(f"Job {job_id}: {result['status']}")
        if result.get("chunks_created"):
            typer.echo(f"Created {result['chunks_created']} chunks")
        if result.get("error"):
            typer.echo(f"Error: {result['error']}")
    
    asyncio.run(do_index())


@app.command()
def benchmark(
    profile: str = typer.Option("default", "--profile", "-p", help="Benchmark profile"),
    model: str = typer.Option("default", "--model", "-m", help="Model to benchmark"),
):
    """Run benchmarks against a model."""
    from app.telemetry.benchmark import BenchmarkManager
    
    typer.echo(f"Running benchmark: profile={profile}, model={model}")
    
    bm = BenchmarkManager()
    typer.echo("Benchmark runner initialized")
    typer.echo("Note: Full benchmark requires LM Studio to be running")


@app.command()
def status():
    """Show RedSight system status."""
    import httpx
    
    typer.echo("Checking RedSight status...")
    
    try:
        response = httpx.get("http://127.0.0.1:8000/api/v1/health", timeout=5.0)
        if response.status_code == 200:
            typer.echo("✓ API Server: Running")
            typer.echo(f"  Status: {response.json()}")
        else:
            typer.echo("✗ API Server: Not responding")
    except Exception as e:
        typer.echo(f"✗ API Server: Not running ({e})")
    
    try:
        import httpx
        response = httpx.get("http://127.0.0.1:1234/v1/models", timeout=5.0)
        if response.status_code == 200:
            models = response.json().get("data", [])
            typer.echo(f"✓ LM Studio: Connected ({len(models)} models)")
        else:
            typer.echo("✗ LM Studio: Not responding")
    except Exception as e:
        typer.echo(f"✗ LM Studio: Not running ({e})")


if __name__ == "__main__":
    app()
