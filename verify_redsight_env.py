#!/usr/bin/env python3
"""
RedSight Environment Verifier
Strips hermes-agent paths from sys.path and verifies all imports.
"""
import sys
import os
import importlib

# Strip hermes-agent paths from sys.path
sys.path = [
    p for p in sys.path
    if 'hermes' not in p
]

# Clear PYTHONPATH
os.environ.pop('PYTHONPATH', None)

print("=== RedSight Environment Verifier ===")
print(f"Python: {sys.executable}")
print(f"Python Path: {sys.path[:3]}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'NOT SET')}")
print()

# List of packages to verify (name: import_name)
packages = [
    ('fastapi', 'fastapi'),
    ('PySide6', 'PySide6'),
    ('qasync', 'qasync'),
    ('qdrant-client', 'qdrant_client'),
    ('torch', 'torch'),
    ('transformers', 'transformers'),
    ('uvicorn', 'uvicorn'),
    ('pydantic', 'pydantic'),
    ('pydantic-settings', 'pydantic_settings'),
    ('python-multipart', 'multipart'),
    ('openai', 'openai'),
    ('sentence-transformers', 'sentence_transformers'),
    ('onnxruntime', 'onnxruntime'),
    ('sqlalchemy', 'sqlalchemy'),
    ('aiosqlite', 'aiosqlite'),
    ('pynvml', 'pynvml'),
    ('pymupdf', 'fitz'),
    ('pymupdf4llm', 'pymupdf4llm'),
    ('python-docx', 'docx'),
    ('markdown', 'markdown'),
    ('chardet', 'chardet'),
    ('httpx', 'httpx'),
    ('structlog', 'structlog'),
    ('rich', 'rich'),
    ('typer', 'typer'),
    ('click', 'click'),
    ('python-dotenv', 'dotenv'),
    ('cryptography', 'cryptography'),
    ('pywin32', 'win32api'),
    ('pytest', 'pytest'),
    ('pytest-asyncio', 'pytest_asyncio'),
    ('pytest-cov', 'coverage'),
    ('ruff', 'ruff'),
    ('mypy', 'mypy'),
    ('pre-commit', 'pre_commit'),
]

failed = []
success = []

for pkg_name, import_name in packages:
    try:
        module = importlib.import_module(import_name)
        version = getattr(module, '__version__', 'no version')
        print(f"✓ {pkg_name}: {version}")
        success.append(pkg_name)
    except Exception as e:
        print(f"✗ {pkg_name}: {type(e).__name__}: {e}")
        failed.append(pkg_name)

print()
print(f"=== Summary ===")
print(f"Success: {len(success)}/{len(packages)}")
print(f"Failed: {len(failed)}/{len(packages)}")

if failed:
    print(f"Failed packages: {', '.join(failed)}")
else:
    print("All packages verified successfully!")
