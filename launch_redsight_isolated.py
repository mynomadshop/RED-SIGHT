#!/usr/bin/env python3
"""
RedSight Environment Isolator
Strips hermes-agent paths from sys.path before importing anything else.
"""
import sys
import os

# Strip hermes-agent paths from sys.path
sys.path = [
    p for p in sys.path
    if 'hermes' not in p
]

# Also clear PYTHONPATH to prevent re-import
os.environ.pop('PYTHONPATH', None)

# Now import and run the actual launcher
import subprocess
import os

# Get the directory of this script
script_dir = os.path.dirname(os.path.abspath(__file__))
launcher = os.path.join(script_dir, 'launch_redsight_command_center.py')

# Set environment variables
env = os.environ.copy()
env.pop('PYTHONPATH', None)
env['RED_SIGHT_MODE'] = 'local_preferred'
env['RED_SIGHT_DATA_ROOT'] = os.path.join(script_dir, 'data')
env['LM_STUDIO_BASE_URL'] = 'http://127.0.0.1:1234/v1'
env['QDRANT_URL'] = 'http://127.0.0.1:6333'
env['LOG_LEVEL'] = 'INFO'
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['PYTHONUNBUFFERED'] = '1'
env['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
env['QT_SCALE_FACTOR_ROUNDING_POLICY'] = 'PassThrough'

# Run the launcher with the isolated environment
print("Starting RedSight Command Center...")
print(f"Working directory: {script_dir}")
print(f"PYTHONPATH: {env.get('PYTHONPATH', 'NOT SET')}")

subprocess.run([sys.executable, launcher], env=env)
