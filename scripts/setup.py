"""
RedSight - High-Performance Local AI Intelligence Platform
Setup Script

Initializes the RedSight environment.
"""

import typer
import asyncio
from pathlib import Path

app = typer.Typer()


@app.command()
def main(
    data_root: str = typer.Option("./data", "--data-root", "-d", help="Data root directory"),
):
    """Initialize the RedSight environment."""
    typer.echo("Initializing RedSight environment...")
    
    # Create directories
    dirs = [
        data_root,
        f"{data_root}/sources",
        f"{data_root}/qdrant",
        f"{data_root}/evals",
        "tests/unit",
        "tests/integration",
        "tests/rag",
        "tests/performance",
    ]
    
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
        typer.echo(f"  Created: {d}")
    
    typer.echo("RedSight environment initialized!")


if __name__ == "__main__":
    main()
