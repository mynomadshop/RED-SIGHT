"""
RedSight - High-Performance Local AI Intelligence Platform
Server Entry Point

Standalone server launcher.
"""

import typer
import uvicorn

app = typer.Typer()


@app.command()
def main(
    host: str = "127.0.0.1",
    port: int = 8000,
    workers: int = 1,
    reload: bool = False,
):
    """Start the RedSight API server."""
    from app.server import app as redsight_app
    
    typer.echo(f"Starting RedSight API server on {host}:{port}")
    typer.echo(f"Workers: {workers}, Reload: {reload}")
    
    uvicorn.run(
        redsight_app,
        host=host,
        port=port,
        workers=workers,
        reload=reload,
    )


if __name__ == "__main__":
    main()
