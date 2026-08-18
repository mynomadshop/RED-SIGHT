#!/usr/bin/env python3
"""
RedSight - Startup Script

Launches the RedSight platform with all subsystems initialized.
Usage:
    python scripts/start.py              # Default startup
    python scripts/start.py --host 0.0.0.0 --port 8000
    python scripts/start.py --dev        # Development mode with reload
    python scripts/start.py --health     # Quick health check only
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def parse_args():
    parser = argparse.ArgumentParser(description="RedSight Platform Startup")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--dev", action="store_true", help="Development mode with auto-reload")
    parser.add_argument("--health", action="store_true", help="Quick health check only")
    parser.add_argument("--workers", type=int, default=1, help="Number of workers (default: 1)")
    return parser.parse_args()


def quick_health_check():
    """Perform a quick health check without full startup."""
    import httpx
    
    try:
        response = httpx.get("http://127.0.0.1:8000/api/v1/health", timeout=5.0)
        if response.status_code == 200:
            print("✅ RedSight is healthy")
            print(f"   Status: {response.json()}")
            return True
        else:
            print(f"❌ RedSight health check failed: {response.status_code}")
            return False
    except httpx.ConnectError:
        print("❌ RedSight is not running")
        print("   Start it with: python scripts/start.py")
        return False
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False


def main():
    args = parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger("redsight.startup")
    
    if args.health:
        success = quick_health_check()
        sys.exit(0 if success else 1)
    
    logger.info("Starting RedSight Platform...")
    logger.info(f"   Host: {args.host}")
    logger.info(f"   Port: {args.port}")
    logger.info(f"   Mode: {'Development' if args.dev else 'Production'}")
    
    # Import and create app
    try:
        from app.server import create_app
        app = create_app()
    except Exception as e:
        logger.error(f"Failed to create app: {e}")
        sys.exit(1)
    
    # Import uvicorn
    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn is required to run the server")
        logger.error("Install it with: pip install uvicorn[standard]")
        sys.exit(1)
    
    # Configure uvicorn
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        reload=args.dev,
        workers=args.workers,
        log_level="info" if not args.dev else "debug",
    )
    
    server = uvicorn.Server(config)
    
    logger.info(f"🚀 RedSight starting on http://{args.host}:{args.port}")
    logger.info("   Press Ctrl+C to stop")
    
    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Shutting down RedSight...")


if __name__ == "__main__":
    main()
