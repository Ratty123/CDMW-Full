"""Describe, collect, review and explicitly submit a private problem report."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict

from PySide6.QtCore import QByteArray, QSignalBlocker, QTimer, QUrl, Qt, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from cdmw.services.problem_report_service import (
    CLEAN_TESTS, DETAIL_RULES, FREQUENCIES, LAST_WORKING, PLATFORMS, PROBLEM_GUIDANCE, PROBLEM_TYPES,
    REPORT_DESTINATION, REPORT_ENDPOINT,
    ProblemDetails, ProblemReportRequest, ProblemSnapshot, ReviewedProblemReport,
    detail_errors, parse_report_receipt, report_delivery_failure, report_test_token,
)
from cdmw.workers.problem_report_workers import ProblemReportCollection


class ProblemReportDialog(QDialog):
    def __init__(self, snapshot: ProblemSnapshot, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Report a Problem — private test")
        self.resize(850, 720)
        self._snapshot = snapshot
        self._generation = 0
        self._closed = False
        self._collection = None
        self._reviewed = None
        self._reply = None
        self._sent = False
        self._receipt = ""
        self._retry_until = 0.0
        self._loading_draft = False
        self._screenshots: tuple[str, ...] = ()
        self._network = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(1000)
        self._retry_timer.timeout.connect(self._update_buttons)
        layout = QVBoxLayout(self)
        intro = QLabel("Report one problem at a time. Describe it, add your game/mod setup, then review exactly what will be sent to the private test inbox.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        form_page = QWidget()
        self._form = QFormLayout(form_page)
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.problem_type = self._combo(PROBLEM_TYPES)
        self._form.addRow("Type of problem *", self.problem_type)
        self.guidance = QLabel(PROBLEM_GUIDANCE["Other / unsure"])
        self.guidance.setWordWrap(True)
        self._form.addRow(self.guidance)
        self.summary = self._line("One specific problem, e.g. Archive Browser fails to extract a DDS")
        self._form.addRow("Summary *", self.summary)
        self.tool = self._line("Tool or menu where this happened")
        self.tool.setText(str(json.loads(snapshot.context_json).get("current_tab", "")))
        self._form.addRow("Tool / workflow *", self.tool)
        self.input_item = self._line("Item name or archive-relative file path; use Not applicable if there is no file")
        self.input_item.setText(str(json.loads(snapshot.context_json).get("selected_archive_path", "Not applicable")))
        self._form.addRow("Item or file *", self.input_item)
        self.steps = self._text("1. Open…\n2. Select…\n3. Click… Include the file or item name.", 105)
        self._form.addRow("Steps to reproduce *", self.steps)
        self.expected = self._text("What should have happened?", 65)
        self._form.addRow("Expected result *", self.expected)
        self.actual = self._text("What happened instead? Include the exact error text or where it stalled.", 85)
        self._form.addRow("Actual result / error *", self.actual)
        self.frequency = self._combo(FREQUENCIES)
        self._form.addRow("How often? *", self.frequency)
        problem_scroll = QScrollArea()
        problem_scroll.setWidgetResizable(True)
        problem_scroll.setWidget(form_page)
        self.tabs.addTab(problem_scroll, "1. Problem")
        setup_page = QWidget()
        self._form = QFormLayout(setup_page)
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        setup_help = QLabel("Unknown and Not tried are valid answers. You do not need to change or delete game files to submit a report. Include the mod manager and export/install method you actually used.")
        setup_help.setWordWrap(True)
        self._form.addRow(setup_help)
        self.game_platform = self._combo(PLATFORMS)
        self._form.addRow("Game platform *", self.game_platform)
        self.game_version = self._line("Game version, or Unknown")
        self._form.addRow("Game version *", self.game_version)
        self.mod_setup = self._text("List the manager, relevant mods and archive edits, or write None.", 65)
        self._form.addRow("Mods and manager *", self.mod_setup)
        self.clean_test = self._combo(CLEAN_TESTS)
        self._form.addRow("Test without mods *", self.clean_test)
        self.last_working = self._combo(LAST_WORKING)
        self._form.addRow("Did this work before? *", self.last_working)
        self.changes = self._text("What changed since then? CDMW/game update, mod, setting or file edit. Write Not sure yet if you do not know.", 65)
        self._changes_label = QLabel("Recent changes *")
        self._form.addRow(self._changes_label, self.changes)
        self.contact = self._line("Optional Nexus username or contact for follow-up")
        self._form.addRow("Contact", self.contact)
        self.include_logs = QCheckBox("Include recent logs and operation details")
        self.include_logs.setChecked(True)
        self.include_layout = QCheckBox("Include a small game folder listing (names and sizes)")
        self.include_layout.setChecked(True)
        self._form.addRow(self.include_logs)
        self._form.addRow(self.include_layout)
        screenshot_row = QWidget()
        screenshot_layout = QHBoxLayout(screenshot_row)
        screenshot_layout.setContentsMargins(0, 0, 0, 0)
        self.attach_button = QPushButton("Choose screenshots…")
        self.attach_button.clicked.connect(self._choose_screenshots)
        self.clear_screenshots_button = QPushButton("Remove")
        self.clear_screenshots_button.clicked.connect(self._clear_screenshots)
        self.screenshot_label = QLabel("No screenshots (optional; up to 3)")
        self.screenshot_label.setWordWrap(True)
        screenshot_layout.addWidget(self.attach_button)
        screenshot_layout.addWidget(self.clear_screenshots_button)
        screenshot_layout.addWidget(self.screenshot_label, 1)
        self._form.addRow(screenshot_row)
        privacy = QLabel("Paths and common credentials are redacted. Screenshots are resized and metadata is removed; visible personal information needs your review. Game file contents and full settings files are excluded.")
        privacy.setWordWrap(True)
        self._form.addRow(privacy)
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(setup_page)
        self.tabs.addTab(form_scroll, "2. Game and mods")
        review_page = QWidget()
        review_layout = QVBoxLayout(review_page)
        self.destination = QLabel(f"Destination: {REPORT_DESTINATION}\nCloud evidence is retained for 90 days. Private issue summaries remain in the inbox until removed.")
        self.destination.setWordWrap(True)
        review_layout.addWidget(self.destination)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        review_layout.addWidget(self.preview, 1)
        self.image_tabs = QTabWidget()
        self.image_tabs.setMaximumHeight(225)
        self.image_tabs.hide()
        review_layout.addWidget(self.image_tabs)
        self.consent = QCheckBox("I reviewed the report and screenshots and agree to send them to this private inbox")
        self.consent.setEnabled(False)
        self.consent.toggled.connect(self._update_buttons)
        review_layout.addWidget(self.consent)
        self.tabs.addTab(review_page, "3. Review and send")
        self.tabs.setTabEnabled(2, False)
        self.tabs.currentChanged.connect(self._update_buttons)
        self.status = QLabel("Required fields are marked *. Unknown and Not tried are valid answers.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(lambda: self.tabs.setCurrentIndex(max(0, self.tabs.currentIndex() - 1)))
        self.next_button = QPushButton("Next: game and mods")
        self.next_button.clicked.connect(self._next)
        self.load_button = QPushButton("Open saved draft…")
        self.load_button.clicked.connect(self._open_draft)
        self.collect_button = QPushButton("Collect and review")
        self.collect_button.clicked.connect(self._collect)
        self.send_button = QPushButton("Send report")
        self.send_button.clicked.connect(self._send)
        self.copy_receipt_button = QPushButton("Copy receipt")
        self.copy_receipt_button.clicked.connect(lambda: QApplication.clipboard().setText(self._receipt))
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.next_button)
        buttons.addWidget(self.collect_button)
        buttons.addWidget(self.load_button)
        buttons.addStretch(1)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.copy_receipt_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        for widget in (self.summary, self.tool, self.input_item, self.game_version, self.contact):
            widget.textChanged.connect(self._invalidate)
        for widget in (self.steps, self.expected, self.actual, self.mod_setup, self.changes):
            widget.textChanged.connect(self._invalidate)
        for widget in (self.frequency, self.game_platform, self.clean_test, self.problem_type, self.last_working):
            widget.currentIndexChanged.connect(self._invalidate)
        for widget in (self.include_layout, self.include_logs):
            widget.toggled.connect(self._invalidate)
        self.problem_type.currentIndexChanged.connect(self._update_guidance)
        self.last_working.currentIndexChanged.connect(self._update_guidance)
        for key, _label, _minimum, maximum in DETAIL_RULES:
            widget = getattr(self, key)
            if isinstance(widget, QLineEdit):
                widget.setMaxLength(maximum)
        self.contact.setMaxLength(200)
        self._update_guidance()
        self._update_buttons()

    def _line(self, placeholder: str) -> QLineEdit:
        widget = QLineEdit()
        widget.setPlaceholderText(placeholder)
        return widget

    def _text(self, placeholder: str, height: int) -> QPlainTextEdit:
        widget = QPlainTextEdit()
        widget.setPlaceholderText(placeholder)
        widget.setFixedHeight(height)
        return widget

    def _combo(self, choices: tuple[str, ...]) -> QComboBox:
        widget = QComboBox()
        widget.addItem("Choose…", "")
        for choice in choices:
            widget.addItem(choice, choice)
        return widget

    def _details(self) -> ProblemDetails:
        return ProblemDetails(self.summary.text().strip(), self.tool.text().strip(), self.steps.toPlainText().strip(),
            self.expected.toPlainText().strip(), self.actual.toPlainText().strip(), str(self.frequency.currentData()),
            self.game_version.text().strip(), str(self.game_platform.currentData()), self.mod_setup.toPlainText().strip(),
            str(self.clean_test.currentData()), self.contact.text().strip(), str(self.problem_type.currentData()),
            self.input_item.text().strip(), str(self.last_working.currentData()), self.changes.toPlainText().strip())

    @Slot()
    def _update_guidance(self) -> None:
        self.guidance.setText(PROBLEM_GUIDANCE.get(str(self.problem_type.currentData()), PROBLEM_GUIDANCE["Other / unsure"]))
        changed = self.last_working.currentData() == "Worked before"
        self.changes.setVisible(changed)
        self._changes_label.setVisible(changed)

    def _show_field_error(self, key: str, message: str) -> None:
        index = 0 if key in {"problem_type", "summary", "tool", "input_item", "steps", "expected", "actual", "frequency"} else 1
        self.tabs.setCurrentIndex(index)
        widget = getattr(self, key)
        self.tabs.widget(index).ensureWidgetVisible(widget)
        widget.setFocus()
        self.status.setText(message)

    @Slot()
    def _next(self) -> None:
        for key, message in detail_errors(self._details()):
            if key in {"problem_type", "summary", "tool", "input_item", "steps", "expected", "actual", "frequency"}:
                self._show_field_error(key, message)
                return
        self.tabs.setCurrentIndex(1)

    @Slot()
    def _invalidate(self) -> None:
        self._generation += 1
        self._reviewed = None
        self.consent.setChecked(False)
        self.consent.setEnabled(False)
        self.preview.clear()
        self.image_tabs.clear()
        self.image_tabs.hide()
        self.tabs.setTabEnabled(2, False)
        if self._collection is not None:
            self._collection.cancel()
        self._update_buttons()

    @Slot()
    def _choose_screenshots(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Choose up to three screenshots", "",
                                               "Screenshots (*.png *.jpg *.jpeg *.webp)")
        if not files:
            return
        if len(files) > 3:
            self.status.setText("Choose at most three screenshots.")
            return
        self._screenshots = tuple(files)
        self.screenshot_label.setText(f"{len(files)} screenshot(s) selected")
        self._invalidate()

    @Slot()
    def _clear_screenshots(self) -> None:
        self._screenshots = ()
        self.screenshot_label.setText("No screenshots (optional; up to 3)")
        self._invalidate()

    @Slot()
    def _collect(self) -> None:
        if self._collection is not None or self._reply is not None or self._sent:
            return
        details = self._details()
        errors = detail_errors(details)
        if errors:
            self._show_field_error(*errors[0])
            return
        self._invalidate()
        request = ProblemReportRequest(details, self._snapshot, self.include_logs.isChecked(),
                                       self.include_layout.isChecked(), self._screenshots)
        self._loading_draft = False
        self._start_collection(request)

    @Slot()
    def _open_draft(self) -> None:
        if self._collection is not None or self._reply is not None or self._sent:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open a saved CDMW report draft",
            self._snapshot.workspace_root + "/problem_reports", "CDMW report drafts (*.json)")
        if not path:
            return
        self._invalidate()
        self._loading_draft = True
        self._start_collection(ProblemReportRequest(self._details(), self._snapshot, draft_path=path))

    def _start_collection(self, request: ProblemReportRequest) -> None:
        collection = ProblemReportCollection(self._generation, request)
        self._collection = collection
        collection.completed.connect(self._collected)
        collection.failed.connect(self._failed)
        collection.stopped.connect(self._collection_stopped)
        self.status.setText("Preparing a local draft…")
        self._set_form_enabled(False)
        self._update_buttons()
        collection.start()

    @Slot(int, object)
    def _collected(self, request_id: int, result: object) -> None:
        if self._closed or request_id != self._generation or not isinstance(result, ReviewedProblemReport):
            return
        self._reviewed = result
        if self._loading_draft:
            data = asdict(ProblemDetails(**json.loads(result.body)["details"]))
            for key, value in data.items():
                widget = getattr(self, key)
                with QSignalBlocker(widget):
                    if isinstance(widget, QComboBox):
                        widget.setCurrentIndex(widget.findData(value))
                    elif isinstance(widget, QPlainTextEdit):
                        widget.setPlainText(value)
                    else:
                        widget.setText(value)
            self._update_guidance()
            for widget, checked in ((self.include_logs, "logs" in json.loads(result.body)["evidence"]),
                                    (self.include_layout, "folder_layout" in json.loads(result.body)["evidence"])):
                with QSignalBlocker(widget):
                    widget.setChecked(checked)
            self._screenshots = ()
            self.screenshot_label.setText("Saved screenshots appear in Review. Choose them again if you edit and recollect.")
        self.preview.setPlainText(result.preview)
        import base64
        for shot in json.loads(result.body)["screenshots"]:
            label = QLabel()
            image = QImage.fromData(base64.b64decode(shot["data"]), "JPEG")
            label.setPixmap(QPixmap.fromImage(image))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scroll = QScrollArea()
            scroll.setWidget(label)
            self.image_tabs.addTab(scroll, shot["name"])
        self.image_tabs.setVisible(self.image_tabs.count() > 0)
        self.consent.setEnabled(True)
        self.tabs.setTabEnabled(2, True)
        self.tabs.setCurrentIndex(2)
        self.status.setText(f"Review {len(result.body) / 1024:.0f} KB. Local draft saved: {result.draft_path}" +
                           ("" if report_test_token() else "\nPrivate test sending is unavailable until the test access key is loaded."))
        self._update_buttons()

    @Slot(int, str)
    def _failed(self, request_id: int, message: str) -> None:
        if not self._closed and request_id == self._generation:
            self.status.setText(message)

    @Slot()
    def _collection_stopped(self) -> None:
        self._collection = None
        if not self._closed:
            self._set_form_enabled(True)
            self._update_buttons()

    def _set_form_enabled(self, enabled: bool) -> None:
        for index in (0, 1):
            self.tabs.widget(index).setEnabled(enabled)

    @Slot()
    def _update_buttons(self) -> None:
        busy = self._collection is not None or self._reply is not None
        index = self.tabs.currentIndex()
        seconds = max(0, math.ceil(self._retry_until - time.monotonic()))
        self.back_button.setVisible(index > 0 and not self._sent)
        self.back_button.setEnabled(not busy)
        self.next_button.setVisible(index == 0 and not self._sent)
        self.next_button.setEnabled(not busy)
        self.collect_button.setVisible(index == 1 and not self._sent)
        self.load_button.setEnabled(not busy and not self._sent)
        self.load_button.setVisible(not self._sent)
        self.copy_receipt_button.setVisible(bool(self._receipt))
        self.send_button.setVisible(index == 2 and not self._sent)
        self.send_button.setText(f"Retry in {seconds // 60}:{seconds % 60:02d}" if seconds else "Send report")
        if not seconds:
            self._retry_timer.stop()
        self.collect_button.setEnabled(not busy and not self._sent)
        self.send_button.setEnabled(bool(self._reviewed and self.consent.isChecked() and report_test_token()
                                         and not busy and not self._sent and not seconds))

    @Slot()
    def _send(self) -> None:
        if not self.send_button.isEnabled() or self._reviewed is None:
            return
        request = QNetworkRequest(QUrl(REPORT_ENDPOINT))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Authorization", f"Bearer {report_test_token()}".encode("utf-8"))
        # Never forward the access key or evidence to a redirect target.
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(45000)
        self._reply = self._network.post(request, QByteArray(self._reviewed.body))
        self._reply.finished.connect(self._upload_finished)
        self._timer.start(45000)
        self._set_form_enabled(False)
        self.consent.setEnabled(False)
        self.status.setText("Sending the reviewed report…")
        self._update_buttons()

    @Slot()
    def _timeout(self) -> None:
        if self._reply is not None:
            self._reply.abort()

    @Slot()
    def _upload_finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._reply = None
        self._timer.stop()
        if not self._closed and self._reviewed is not None:
            try:
                status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
                body = bytes(reply.readAll())
                if reply.error() != QNetworkReply.NetworkError.NoError or status not in (200, 201):
                    failure = report_delivery_failure(body, status, bytes(reply.rawHeader("Retry-After")).decode("ascii", errors="ignore"),
                                                      report_id=self._reviewed.report_id)
                    if failure.retry_seconds:
                        self._retry_until = time.monotonic() + failure.retry_seconds
                        self._retry_timer.start()
                    if failure.duplicate_receipt:
                        self._receipt = failure.duplicate_receipt
                        self._sent = True
                    raise ValueError(failure.message)
                receipt = parse_report_receipt(body, report_id=self._reviewed.report_id)
                self._sent = True
                self._receipt = receipt
                self.status.setText(f"Report received: {receipt}\nKeep this receipt for follow-up. Local draft: {self._reviewed.draft_path}")
            except ValueError as error:
                self.status.setText(str(error))
            self._set_form_enabled(not self._sent)
            self.consent.setEnabled(not self._sent)
            self._update_buttons()
        reply.deleteLater()

    def _shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        if self._collection is not None:
            self._collection.cancel()
        if self._reply is not None:
            self._reply.abort()
        self._timer.stop()
        self._retry_timer.stop()

    def closeEvent(self, event) -> None:
        self._shutdown()
        super().closeEvent(event)

    def reject(self) -> None:
        self._shutdown()
        super().reject()

    def done(self, result: int) -> None:
        self._shutdown()
        super().done(result)
