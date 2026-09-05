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
mode = env.get('RED_SIGHT_PLATFORM__MODE') or env.get('RED_SIGHT_MODE') or 'local_preferred'
data_root = (
    env.get('RED_SIGHT_PLATFORM__DATA_ROOT')
    or env.get('RED_SIGHT_DATA_ROOT')
    or os.path.join(script_dir, 'data')
)
lm_studio_url = (
    env.get('RED_SIGHT_LMSTUDIO__BASE_URL')
    or env.get('LM_STUDIO_BASE_URL')
    or 'http://127.0.0.1:1234/v1'
)
qdrant_url = (
    env.get('RED_SIGHT_RETRIEVAL__VECTOR_BACKEND_URL')
    or env.get('VECTOR_BACKEND_URL')
    or env.get('QDRANT_URL')
    or 'http://127.0.0.1:6333'
)
log_level = env.get('RED_SIGHT_TELEMETRY__LOG_LEVEL') or env.get('LOG_LEVEL') or 'INFO'
env['RED_SIGHT_PLATFORM__MODE'] = mode
env['RED_SIGHT_PLATFORM__DATA_ROOT'] = data_root
env['RED_SIGHT_LMSTUDIO__BASE_URL'] = lm_studio_url
env['RED_SIGHT_RETRIEVAL__VECTOR_BACKEND_URL'] = qdrant_url
env['RED_SIGHT_TELEMETRY__LOG_LEVEL'] = log_level
# Compatibility aliases for older gateway and installer components.
env['RED_SIGHT_MODE'] = mode
env['RED_SIGHT_DATA_ROOT'] = data_root
env['LM_STUDIO_BASE_URL'] = lm_studio_url
env['QDRANT_URL'] = qdrant_url
env['LOG_LEVEL'] = log_level
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['PYTHONUNBUFFERED'] = '1'
env['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
env['QT_SCALE_FACTOR_ROUNDING_POLICY'] = 'PassThrough'

# Run the launcher with the isolated environment
print("Starting RedSight Command Center...")
print(f"Working directory: {script_dir}")
print(f"PYTHONPATH: {env.get('PYTHONPATH', 'NOT SET')}")

subprocess.run([sys.executable, launcher], env=env)
