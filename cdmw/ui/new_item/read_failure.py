"""Explain archive-read failures and prepare a bounded, user-copyable report."""

from collections import deque
from datetime import datetime, timezone
import os
import re
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QToolButton, QVBoxLayout,
)

from cdmw.constants import APP_VERSION


def _failure_code(message: str) -> str:
    text = message.casefold()
    if any(part in text for part in ("permission denied", "access is denied", "access denied", "permissionerror", "[winerror 5]")):
        return "NI-ACCESS-DENIED"
    if any(part in text for part in ("no such file", "missing paz", "no package tables", "no game folder", "archives have no", "filenotfounderror", "[winerror 2]", "[winerror 3]")):
        return "NI-MISSING-SOURCE"
    if any(part in text for part in ("not where the workbench last saw it", "archive session fingerprint changed", "archives changed", "source files changed")):
        return "NI-ARCHIVE-CHANGED"
    if "unsupported" in text or "not supported" in text:
        return "NI-UNSUPPORTED-FORMAT"
    if any(part in text for part in ("decryption", "decoded localization", "decompression", "lz4", "footer counts", "runs past", "truncated", "malformed", "checksum")):
        return "NI-DECODE-FAILED"
    return "NI-READ-FAILED"


def _bounded(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[truncated]"


def _report_text(message: str, code: str, progress: tuple[str, ...], game_root: str) -> str:
    text = "\n".join((
        "CDMW New Item archive-read report",
        f"Workbench: {APP_VERSION}",
        f"Time (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Error code: {code}",
        f"Runtime: Python {sys.version.split()[0]}; {sys.platform}; "
        f"{'packaged' if getattr(sys, 'frozen', False) else 'source'}",
        "Operation: Read archives for New Item",
        "",
        "Exact error:",
        _bounded(message, 8000),
        "",
        "Recent loading steps:",
        "\n".join(progress) if progress else "No loading progress was reported.",
        "",
        "Please add: game version, active mods, recent game/mod changes, and steps to reproduce.",
    ))
    # Keep virtual archive paths and package labels while removing common local prefixes.
    for path, token in ((game_root, "<game>"), (os.environ.get("USERPROFILE", ""), "<profile>")):
        if not path:
            continue
        for variant in {path.rstrip("/\\"), path.replace("\\", "/").rstrip("/"), path.replace("/", "\\").rstrip("\\")}:
            if variant:
                text = re.sub(re.escape(variant) + r"(?=[\\/\s\"'():,.;]|$)", lambda _match: token, text, flags=re.IGNORECASE)
    return text


class ArchiveReadFailurePanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = deque(maxlen=12)
        self._collecting = False
        self.report_text = ""
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        self.guidance = QLabel(self)
        self.guidance.setTextFormat(Qt.TextFormat.PlainText)
        self.guidance.setWordWrap(True)
        layout.addWidget(self.guidance)
        controls = QHBoxLayout()
        self.copy_button = QPushButton("Copy error report", self)
        self.copy_button.clicked.connect(self._copy_report)
        controls.addWidget(self.copy_button)
        self.details_button = QToolButton(self)
        self.details_button.setText("Details")
        self.details_button.setCheckable(True)
        controls.addWidget(self.details_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(180)
        layout.addWidget(self.details)
        self.details_button.toggled.connect(self.details.setVisible)
        self.clear()

    def begin(self):
        self.clear()
        self._collecting = True

    def capture_progress(self, message):
        if self._collecting:
            self._progress.append(_bounded(str(message), 500))

    def clear(self):
        self._collecting = False
        self._progress.clear()
        self.report_text = ""
        self.details.clear()
        self.details_button.setChecked(False)
        self.details.hide()
        self.copy_button.setText(self.tr("Copy error report"))
        self.copy_button.setEnabled(False)
        self.hide()

    def show_failure(self, message: str, *, game_root: str = ""):
        self._collecting = False
        code = _failure_code(message)
        if code == "NI-UNSUPPORTED-FORMAT":
            guidance = self.tr("Check for a workbench update. Include this report if the format is still unsupported.")
        elif code == "NI-ARCHIVE-CHANGED":
            guidance = self.tr("Wait for game updates or mod changes to finish, then try again.")
        elif code == "NI-ACCESS-DENIED":
            guidance = self.tr("Check folder permissions and whether another program is using the file.")
        elif code == "NI-MISSING-SOURCE":
            guidance = self.tr("Check the selected game folder and that its archive files are present.")
        elif code == "NI-DECODE-FAILED":
            guidance = self.tr("Unreadable data can mean a different format or a damaged file. Include this report when asking for help.")
        else:
            guidance = self.tr("Try again. If the problem continues, include this report when asking for help.")
        self.guidance.setText(guidance)
        self.report_text = _report_text(str(message), code, tuple(self._progress), game_root)
        self.details.setPlainText(self.report_text)
        self.details_button.setChecked(False)
        self.details.hide()
        self.copy_button.setText(self.tr("Copy error report"))
        self.copy_button.setEnabled(True)
        self.show()

    def _copy_report(self):
        if self.report_text:
            QApplication.clipboard().setText(self.report_text)
            self.copy_button.setText(self.tr("Copied"))
