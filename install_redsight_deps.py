#!/usr/bin/env python3
"""
RedSight Installer - Installs dependencies in a clean isolated environment
Strips hermes-agent paths from sys.path before installing anything.
"""
import sys
import subprocess
import os

# Strip hermes-agent paths from sys.path
sys.path = [
    p for p in sys.path
    if 'hermes' not in p
]

# Clear PYTHONPATH
os.environ.pop('PYTHONPATH', None)

print("=== RedSight Environment Installer ===")
print(f"Python: {sys.executable}")
print(f"Python Path: {sys.path[:3]}")
print()

# Upgrade pip first
print("1. Upgrading pip, setuptools, wheel...")
subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel'], check=True)
print()

# Install project dependencies
print("2. Installing RedSight dependencies...")
subprocess.run([sys.executable, '-m', 'pip', 'install', '-e', '.[dev]'], check=True)
print()

# Install additional dependencies
print("3. Installing qasync...")
subprocess.run([sys.executable, '-m', 'pip', 'install', 'qasync'], check=True)
print()

print("=== Installation Complete ===")
print("All dependencies installed successfully!")
