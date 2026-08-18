@echo off
title REDSIGHT
cd /d "C:\Users\walim\RedSight"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\walim\RedSight\START-REDSIGHT.ps1"
if errorlevel 1 (
  echo.
  echo REDSIGHT launcher failed. Review %%LOCALAPPDATA%%\RedSight\logs
  pause
)