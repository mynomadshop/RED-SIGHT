"""
RedSight - High-Performance Local AI Intelligence Platform
UI Entry Point

Desktop application launcher.
"""

import sys
from PySide6.QtWidgets import QApplication

from ui.command_center import CommandCenter


def main():
    """Main entry point for the PySide6 UI."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = CommandCenter()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
