@echo off
REM RedSight Launcher - Fixed PATH and Python Environment
REM This script ensures the RedSight .venv is used exclusively

REM Save original environment
set "ORIGINAL_PATH=%PATH%"
set "ORIGINAL_PYTHONPATH=%PYTHONPATH%"

REM Remove hermes-agent venv from PATH to prevent conflicts
set "PATH=%PATH:C:\Users\walim\AppData\Local\hermes\hermes-agent\venv\Scripts;=%"
set "PATH=%PATH:C:\Users\walim\AppData\Local\hermes\hermes-agent\venv\;=%"
set "PATH=%PATH:C:\Users\walim\AppData\Local\hermes\hermes-agent;=%"

REM Add RedSight .venv to PATH first
set "PATH=%~dp0.venv\Scripts;%PATH%"

REM Clear PYTHONPATH to prevent hermes-agent from being imported
set "PYTHONPATH="

REM Set working directory to project root
cd /d "%~dp0"

REM Set RedSight environment variables
set RED_SIGHT_MODE=local_preferred
set RED_SIGHT_DATA_ROOT=%~dp0data
set LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
set QDRANT_URL=http://127.0.0.1:6333
set LOG_LEVEL=INFO

REM Set Python environment
set PYTHONDONTWRITEBYTECODE=1
set PYTHONUNBUFFERED=1

REM Set QT environment for HiDPI
set QT_AUTO_SCREEN_SCALE_FACTOR=1
set QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough

REM Execute the launch script
echo Starting RedSight Command Center...
echo Using Python: %~dp0.venv\Scripts\python.exe
echo Working directory: %~dp0
echo PYTHONPATH: %PYTHONPATH%

REM Use the .venv Python explicitly
"%~dp0.venv\Scripts\python.exe" launch_redsight_command_center.py

REM Restore original environment
set "PATH=%ORIGINAL_PATH%"
set "PYTHONPATH=%ORIGINAL_PYTHONPATH%"
