@echo off
cd /d "C:\Users\walim\RedSight"
"C:\Users\walim\RedSight\.venv-actions\Scripts\python.exe" -m uvicorn redsight_actions.gateway_stage10:app --host 127.0.0.1 --port 8765 --log-level info
