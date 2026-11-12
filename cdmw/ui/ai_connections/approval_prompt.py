"""The question an AI app's call waits on: Allow once, Allow this tool for this session, or Deny.

Non-modal: the app keeps working while it is open, and the call waits on
its own thread. Deny has the focus; Escape and closing the window deny. A
prompt nobody answers is denied after five minutes (``approvals``), and it
closes itself when its call is cancelled.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.mcp.approvals import ALLOW_ONCE, ALLOW_SESSION, DENY, ApprovalRequest
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT
from cdmw.mcp.summary import summarize_arguments

CLASS_LABELS = {EDIT: "Edit tool", DESTRUCTIVE: "Destructive tool", OUTPUT: "Output tool"}


class ApprovalPrompt(QDialog):
    _decided_elsewhere = Signal(str)

    def __init__(self, request: ApprovalRequest, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.request = request
        self.setObjectName("AiApprovalPrompt")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("An AI app asks to run a tool")
        layout = QVBoxLayout(self)
        self.summary_label = QLabel(f"{request.client or 'An AI app'} wants to run {request.title}.")
        self.summary_label.setObjectName("AiApprovalSummary")
        self.summary_label.setWordWrap(True)
        # Names from the client are data: shown as plain text, never as markup.
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.class_label = QLabel(CLASS_LABELS.get(request.effect, request.effect))
        self.class_label.setObjectName("AiApprovalClass")
        self.change_label = QLabel(request.change)
        self.change_label.setWordWrap(True)
        self.change_label.setTextFormat(Qt.TextFormat.PlainText)
        self.arguments_view = QPlainTextEdit(self)
        self.arguments_view.setObjectName("AiApprovalArguments")
        self.arguments_view.setReadOnly(True)
        self.arguments_view.setPlainText(json.dumps(summarize_arguments(request.arguments), indent=2,
                                                    ensure_ascii=False) if request.arguments else "No arguments.")
        buttons = QHBoxLayout()
        self.allow_once_button = QPushButton("Allow once")
        self.allow_session_button = QPushButton("Allow this tool for this session")
        self.deny_button = QPushButton("Deny")
        for button, answer in ((self.allow_once_button, ALLOW_ONCE), (self.allow_session_button, ALLOW_SESSION),
                               (self.deny_button, DENY)):
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, answer=answer: self.answer(answer))
            buttons.addWidget(button)
        self.deny_button.setDefault(True)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.class_label)
        layout.addWidget(self.change_label)
        layout.addWidget(QLabel("Arguments:"))
        layout.addWidget(self.arguments_view, 1)
        layout.addLayout(buttons)
        self.deny_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self._decided_elsewhere.connect(self._close_quietly, Qt.ConnectionType.QueuedConnection)
        # A timeout or a cancel decides on the call's thread; close here.
        request.on_decided.append(lambda _answer: self._decided_elsewhere.emit(_answer))

    def answer(self, answer: str) -> None:
        self.request.decide(answer)
        self._close_quietly()

    def _close_quietly(self, _answer: str = "") -> None:
        if self.isVisible():
            self.hide()
        self.deleteLater()

    def reject(self) -> None:  # Escape
        self.answer(DENY)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.request.decide(DENY)
        super().closeEvent(event)

    def present(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.deny_button.setFocus(Qt.FocusReason.OtherFocusReason)
        # Flash the taskbar button when CDMW is behind the AI app.
        parent = self.parentWidget()
        if parent is not None:
            QApplication.alert(parent.window(), 0)
