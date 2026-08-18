"""
RedSight - High-Performance Local AI Intelligence Platform
Diagnostics Script

System diagnostics and health checks.
"""

import typer
import asyncio
import httpx

app = typer.Typer()


@app.command()
def main():
    """Run system diagnostics."""
    typer.echo("=== RedSight Diagnostics ===\n")
    
    # Check API server
    typer.echo("1. API Server:")
    try:
        response = httpx.get("http://127.0.0.1:8000/api/v1/health", timeout=5.0)
        if response.status_code == 200:
            typer.echo("   ✓ Running")
        else:
            typer.echo(f"   ✗ Not responding (status: {response.status_code})")
    except Exception as e:
        typer.echo(f"   ✗ Not running ({e})")
    
    # Check LM Studio
    typer.echo("\n2. LM Studio:")
    try:
        response = httpx.get("http://127.0.0.1:1234/v1/models", timeout=5.0)
        if response.status_code == 200:
            models = response.json().get("data", [])
            typer.echo(f"   ✓ Connected ({len(models)} models)")
        else:
            typer.echo(f"   ✗ Not responding (status: {response.status_code})")
    except Exception as e:
        typer.echo(f"   ✗ Not running ({e})")
    
    # Check Python environment
    typer.echo("\n3. Python Environment:")
    import sys
    typer.echo(f"   Python: {sys.version}")
    typer.echo(f"   Executable: {sys.executable}")
    
    # Check key packages
    typer.echo("\n4. Key Packages:")
    packages = ["fastapi", "pydantic", "pynvml", "pymupdf"]
    for pkg in packages:
        try:
            __import__(pkg)
            typer.echo(f"   ✓ {pkg}")
        except ImportError:
            typer.echo(f"   ✗ {pkg} (not installed)")
    
    typer.echo("\n=== Diagnostics Complete ===")


if __name__ == "__main__":
    main()
