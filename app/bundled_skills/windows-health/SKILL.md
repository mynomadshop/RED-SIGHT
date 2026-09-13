---
name: windows-health
description: Diagnose a Windows RedSight installation and explain specific service or dependency failures.
---

# Windows Health

Example request: Check RedSight startup and dependency health on this computer.

Find the RedSight project root and use documents.extract or filesystem.read for its latest diagnostic logs. For a live health check use system.powershell with a read-only command that runs the installed scripts/windows/Verify-RedSightSetup.ps1; obtain the exact path from filesystem results first. Interpret nonzero exit codes and distinguish required failures from optional integrations. Propose the smallest repair and run it only within the user-requested scope and tool approval. Never delete installations or credentials as a diagnostic step.
