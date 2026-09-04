"""RedSight desktop UI entry point.

The console command delegates to the same maintained Command Center launcher
used by the Windows shortcuts. This removes the historical split where the
`redsight-ui` console script and desktop shortcut started different UI stacks.
"""

from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    """Run the canonical RedSight Command Center launcher."""
    project_root = Path(__file__).resolve().parent.parent
    launcher = project_root / "launch_redsight_command_center.py"
    if not launcher.is_file():
        raise FileNotFoundError(f"RedSight Command Center launcher not found: {launcher}")
    runpy.run_path(str(launcher), run_name="__main__")


if __name__ == "__main__":
    main()
