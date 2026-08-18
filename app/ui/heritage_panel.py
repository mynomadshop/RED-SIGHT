from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QLineEdit,
    QListWidget,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(
            encoding="utf-8-sig",
            errors="replace",
        )
    except Exception as exc:
        return (
            "Unavailable: "
            + str(exc)
        )


class HermesHeritageDock(QDockWidget):

    def __init__(
        self,
        heritage_root: Path,
        parent=None,
    ):
        super().__init__(
            "HERMES HERITAGE",
            parent,
        )

        self.root = Path(
            heritage_root
        )

        self.catalog = []
        self.visible_skills = []

        self.setObjectName(
            "RedSightHermesHeritageDock"
        )

        self.setMinimumWidth(
            440
        )

        tabs = QTabWidget()

        self.overview = QTextBrowser()
        self.soul = QTextBrowser()
        self.memory = QTextBrowser()
        self.mcp = QTextBrowser()

        tabs.addTab(
            self.overview,
            "Overview",
        )

        tabs.addTab(
            self.soul,
            "Soul",
        )

        tabs.addTab(
            self.memory,
            "Memory",
        )

        tabs.addTab(
            self._build_skills_tab(),
            "Skills",
        )

        tabs.addTab(
            self.mcp,
            "MCP",
        )

        container = QWidget()

        layout = QVBoxLayout(
            container
        )

        layout.setContentsMargins(
            6,
            6,
            6,
            6,
        )

        layout.addWidget(
            tabs
        )

        self.setWidget(
            container
        )

        self.setStyleSheet(
            """
            QDockWidget {
                color: #FFFFFF;
                font-weight: 700;
            }

            QDockWidget::title {
                background-color: #17090B;
                color: #FF3540;
                padding: 8px;
                border-bottom: 1px solid #8D252B;
            }

            QTabWidget::pane {
                background-color: #0B1016;
                border: 1px solid #46525D;
            }

            QTabBar::tab {
                background-color: #19212A;
                color: #E4E9ED;
                padding: 8px 10px;
                border: 1px solid #3D4852;
            }

            QTabBar::tab:selected {
                background-color: #A51F27;
                color: #FFFFFF;
            }

            QTextBrowser,
            QListWidget,
            QLineEdit {
                background-color: #0C131A;
                color: #F7F9FA;
                border: 1px solid #4A5864;
                selection-background-color: #AE252D;
                selection-color: #FFFFFF;
            }

            QLineEdit {
                padding: 7px;
                border-radius: 5px;
            }
            """
        )

        self.refresh()

    def _build_skills_tab(self):

        page = QWidget()

        layout = QVBoxLayout(
            page
        )

        self.search = QLineEdit()

        self.search.setPlaceholderText(
            "Search inherited Hermes skills..."
        )

        splitter = QSplitter(
            Qt.Orientation.Vertical
        )

        self.skill_list = QListWidget()

        self.skill_detail = QTextBrowser()

        splitter.addWidget(
            self.skill_list
        )

        splitter.addWidget(
            self.skill_detail
        )

        splitter.setSizes(
            [
                270,
                450,
            ]
        )

        layout.addWidget(
            self.search
        )

        layout.addWidget(
            splitter
        )

        self.search.textChanged.connect(
            self.filter_skills
        )

        self.skill_list.currentRowChanged.connect(
            self.show_skill
        )

        return page

    def refresh(self):

        try:

            manifest = json.loads(
                (
                    self.root
                    / "heritage_manifest.json"
                ).read_text(
                    encoding="utf-8-sig"
                )
            )

        except Exception:

            manifest = {}

        mcp_servers = manifest.get(
            "mcp_servers",
            [],
        )

        self.overview.setPlainText(
            "REDSIGHT HERMES HERITAGE\n\n"
            + "Hermes source:\n"
            + str(
                manifest.get(
                    "hermes_home",
                    "unknown",
                )
            )
            + "\n\nInherited skills: "
            + str(
                manifest.get(
                    "skill_count",
                    0,
                )
            )
            + "\nSOUL migrated: "
            + str(
                manifest.get(
                    "soul_present",
                    False,
                )
            )
            + "\nMEMORY migrated: "
            + str(
                manifest.get(
                    "memory_present",
                    False,
                )
            )
            + "\nUSER migrated: "
            + str(
                manifest.get(
                    "user_present",
                    False,
                )
            )
            + "\nCron migrated: "
            + str(
                manifest.get(
                    "cron_present",
                    False,
                )
            )
            + "\n\nMCP servers:\n"
            + (
                "\n".join(
                    "  - " + str(x)
                    for x in mcp_servers
                )
                if mcp_servers
                else "  None discovered"
            )
            + "\n\n"
            + (
                "Hermes Soul, Memory, USER profile, Skills and MCP "
                "definitions are preserved inside RedSight heritage."
            )
        )

        self.soul.setPlainText(
            _read(
                self.root
                / "SOUL.md"
            )
        )

        self.memory.setPlainText(
            "================ MEMORY.md ================\n\n"
            + _read(
                self.root
                / "memories"
                / "MEMORY.md"
            )
            + "\n\n"
            + "================ USER.md ==================\n\n"
            + _read(
                self.root
                / "memories"
                / "USER.md"
            )
        )

        self.mcp.setPlainText(
            _read(
                self.root
                / "MCP_SERVERS.md"
            )
            + "\n\n"
            + "============ SANITIZED MCP CONFIG ==========\n\n"
            + _read(
                self.root
                / "mcp_servers_sanitized.json"
            )
        )

        try:

            self.catalog = json.loads(
                (
                    self.root
                    / "skills_catalog.json"
                ).read_text(
                    encoding="utf-8-sig"
                )
            )

        except Exception:

            self.catalog = []

        self.filter_skills(
            self.search.text()
        )

    def filter_skills(
        self,
        text,
    ):

        query = str(
            text
        ).strip().lower()

        self.skill_list.clear()

        self.visible_skills = []

        for skill in self.catalog:

            haystack = (
                str(
                    skill.get(
                        "Name",
                        "",
                    )
                )
                + " "
                + str(
                    skill.get(
                        "Description",
                        "",
                    )
                )
                + " "
                + str(
                    skill.get(
                        "Source",
                        "",
                    )
                )
            ).lower()

            if (
                query
                and query not in haystack
            ):

                continue

            self.visible_skills.append(
                skill
            )

            self.skill_list.addItem(
                "{}  [{}]".format(
                    skill.get(
                        "Name",
                        "skill",
                    ),
                    skill.get(
                        "Source",
                        "unknown",
                    ),
                )
            )

        if self.skill_list.count():

            self.skill_list.setCurrentRow(
                0
            )

    def show_skill(
        self,
        row,
    ):

        if (
            row < 0
            or row >= len(
                self.visible_skills
            )
        ):

            return

        item = self.visible_skills[
            row
        ]

        relative = str(
            item.get(
                "RelativePath",
                "",
            )
        )

        path = (
            self.root
            / relative
        )

        self.skill_detail.setPlainText(
            "NAME: "
            + str(
                item.get(
                    "Name",
                    "",
                )
            )
            + "\nSOURCE: "
            + str(
                item.get(
                    "Source",
                    "",
                )
            )
            + "\nSHA256: "
            + str(
                item.get(
                    "SHA256",
                    "",
                )
            )
            + "\nPATH: "
            + relative
            + "\n\n"
            + _read(path)
        )


def attach_heritage_ui(
    window,
    project_root,
):

    root = Path(
        project_root
    )

    # -------------------------------------------------------------
    # REDSIGHT LOGO / BRAND
    # -------------------------------------------------------------

    toolbar = QToolBar(
        "RedSight Brand",
        window,
    )

    toolbar.setObjectName(
        "RedSightBrandToolbar"
    )

    toolbar.setMovable(
        False
    )

    toolbar.setFloatable(
        False
    )

    toolbar.setStyleSheet(
        """
        QToolBar {
            background-color: #070B10;
            border-bottom: 1px solid #8A2027;
            spacing: 6px;
            padding: 2px;
        }
        """
    )

    logo = QLabel(
        "REDSIGHT"
    )

    logo_font = QFont(
        "Bahnschrift SemiCondensed",
        31,
        QFont.Weight.Black,
    )

    logo_font.setItalic(
        True
    )

    logo_font.setLetterSpacing(
        QFont.SpacingType.AbsoluteSpacing,
        1.2,
    )

    logo.setFont(
        logo_font
    )

    logo.setStyleSheet(
        """
        color: #F1262D;
        background: transparent;
        font-weight: 900;
        padding: 2px 12px 2px 9px;
        """
    )

    subtitle = QLabel(
        "AGENTIC INTELLIGENCE  |  LOCAL FIRST"
    )

    subtitle.setStyleSheet(
        """
        color: #E5EAEE;
        background: transparent;
        font-size: 12px;
        font-weight: 700;
        padding-left: 5px;
        """
    )

    toolbar.addWidget(
        logo
    )

    toolbar.addWidget(
        subtitle
    )

    window.addToolBar(
        Qt.ToolBarArea.TopToolBarArea,
        toolbar,
    )

    # -------------------------------------------------------------
    # HERITAGE SIDE PANEL
    # -------------------------------------------------------------

    dock = HermesHeritageDock(
        root
        / "data"
        / "heritage"
        / "hermes",
        window,
    )

    window.addDockWidget(
        Qt.DockWidgetArea.LeftDockWidgetArea,
        dock,
    )

    window._redsight_brand_toolbar = toolbar
    window._redsight_heritage_dock = dock

    return dock
