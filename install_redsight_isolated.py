#!/usr/bin/env python3
"""
RedSight Isolated Installer
Strips hermes-agent paths from sys.path and PYTHONPATH before installing.
"""
import sys
import os
import subprocess

# Strip hermes-agent paths from sys.path
sys.path = [
    p for p in sys.path
    if 'hermes' not in p
]

# Clear PYTHONPATH to prevent re-import
os.environ.pop('PYTHONPATH', None)

print("=== RedSight Isolated Installer ===")
print(f"Python: {sys.executable}")
print(f"Python Path: {sys.path[:3]}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'NOT SET')}")
print()

# Install project dependencies
print("Installing RedSight dependencies...")
result = subprocess.run(
    [sys.executable, '-m', 'pip', 'install', '-e', '.[dev]'],
    env={**os.environ, 'PYTHONPATH': ''},
    check=False
)
print(f"pip install exit code: {result.returncode}")
print()

# Install additional dependencies
print("Installing qasync...")
result = subprocess.run(
    [sys.executable, '-m', 'pip', 'install', 'qasync'],
    env={**os.environ, 'PYTHONPATH': ''},
    check=False
)
print(f"pip install exit code: {result.returncode}")
print()

print("=== Installation Complete ===")
