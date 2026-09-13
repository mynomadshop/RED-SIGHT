"""One-click starters for the agent's shipped skills."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.skills.bundled import list_bundled_skills


class BundledSkillsTab(QWidget):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.skills = list_bundled_skills()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose a skill, add your file paths or task details, and run it in chat."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a skill: documents, CSV, research, CUDA...")
        layout.addWidget(self.search)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.instruction = QPlainTextEdit()
        self.instruction.setMaximumHeight(110)
        layout.addWidget(self.instruction)
        self.run_button = QPushButton("Run skill in chat")
        self.run_button.setObjectName("RedSightRunBundledSkill")
        layout.addWidget(self.run_button)
        self.search.textChanged.connect(self.refresh)
        self.list.currentItemChanged.connect(self.select)
        self.run_button.clicked.connect(self.run_skill)
        self.refresh()

    def refresh(self, query=""):
        self.list.clear()
        terms = query.lower().split()
        for skill in self.skills:
            if all(term in (skill["name"] + " " + skill["description"]).lower() for term in terms):
                item = QListWidgetItem(skill["name"])
                item.setData(Qt.ItemDataRole.UserRole, skill)
                self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.run_button.setEnabled(bool(self.list.count()))

    def select(self, item, _previous=None):
        if item is None:
            return
        skill = item.data(Qt.ItemDataRole.UserRole)
        self.description.setText(skill["description"])
        self.instruction.setPlainText(skill["example"])

    def run_skill(self):
        item = self.list.currentItem()
        instruction = self.instruction.toPlainText().strip()
        if item is None or not instruction or self.dialog._probe_running():
            return
        skill = item.data(Qt.ItemDataRole.UserRole)
        command = f"/skill {skill['name']} | {instruction}"
        window = self.dialog.window
        self.dialog.accept()
        def send():
            chat = window._tabs.widget(0)
            window._tabs.setCurrentIndex(0)
            chat._message_input.setText(command)
            chat._on_send()

        QTimer.singleShot(0, send)
