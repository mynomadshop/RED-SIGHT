"""RedSight command-line entry point."""

import asyncio

import typer

app = typer.Typer(
    name="redsight",
    help="High-Performance Local AI Intelligence Platform",
    add_completion=False,
)


@app.command()
def server(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="API port"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload"),
):
    """Start the RedSight API server."""
    import uvicorn
    from app.server import app as redsight_app

    typer.echo(f"Starting RedSight server on {host}:{port}")
    uvicorn.run(redsight_app, host=host, port=port, reload=reload)


@app.command()
def ui():
    """Start the RedSight desktop UI."""
    from ui.command_center import main

    main()


@app.command()
def index(
    path: str = typer.Option(..., "--path", "-p", help="Path to index"),
    collection: str = typer.Option("knowledge_docs", "--collection", "-c"),
    project: str = typer.Option("default", "--project", "-j"),
):
    """Index a file or directory into the knowledge base."""
    from app.ingestion.indexer import Indexer

    typer.echo(f"Indexing {path} -> {collection} (project={project})")
    indexer = Indexer()

    async def do_index():
        job_id = await indexer.create_job(path, collection, project)
        result = await indexer.process_job(job_id)
        typer.echo(f"Job {job_id}: {result['status']}")
        if result.get("chunks_created"):
            typer.echo(f"Created {result['chunks_created']} chunks")
        if result.get("error"):
            raise typer.Exit(code=1)

    asyncio.run(do_index())


@app.command()
def benchmark(
    profile: str = typer.Option("default", "--profile", "-p"),
    model: str = typer.Option("default", "--model", "-m"),
):
    """Run the RedSight benchmark harness."""
    from app.telemetry.benchmark import BenchmarkManager

    typer.echo(f"Benchmark profile={profile}, model={model}")
    BenchmarkManager()


@app.command()
def status():
    """Show RedSight API, LM Studio and Docker status."""
    import httpx

    try:
        response = httpx.get("http://127.0.0.1:8000/api/v1/health", timeout=5.0)
        typer.echo(f"API Server: {'Running' if response.status_code == 200 else 'Not responding'}")
    except Exception as exc:
        typer.echo(f"API Server: Not running ({exc})")

    try:
        response = httpx.get("http://127.0.0.1:1234/v1/models", timeout=5.0)
        if response.status_code == 200:
            models = response.json().get("data", [])
            typer.echo(f"LM Studio: Connected ({len(models)} models)")
        else:
            typer.echo("LM Studio: Not responding")
    except Exception as exc:
        typer.echo(f"LM Studio: Not running ({exc})")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
