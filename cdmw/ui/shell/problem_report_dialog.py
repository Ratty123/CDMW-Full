"""Describe, collect, review and explicitly submit a private problem report."""

from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QTimer, QUrl, Qt, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from cdmw.services.problem_report_service import (
    CLEAN_TESTS, FREQUENCIES, PLATFORMS, REPORT_DESTINATION, REPORT_ENDPOINT,
    ProblemDetails, ProblemReportRequest, ProblemSnapshot, ReviewedProblemReport,
    parse_report_receipt, report_test_token, validate_details,
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
        self._screenshots: tuple[str, ...] = ()
        self._network = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)
        layout = QVBoxLayout(self)
        intro = QLabel("Describe what happened, then review the evidence before sending. This test sends to a private inbox.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        form_page = QWidget()
        self._form = QFormLayout(form_page)
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.summary = self._line("One specific problem, e.g. Archive Browser fails to extract a DDS")
        self._form.addRow("Summary *", self.summary)
        self.tool = self._line("Tool or menu where this happened")
        self.tool.setText(str(json.loads(snapshot.context_json).get("current_tab", "")))
        self._form.addRow("Tool / workflow *", self.tool)
        self.steps = self._text("1. Open…\n2. Select…\n3. Click… Include the file or item name.", 105)
        self._form.addRow("Steps to reproduce *", self.steps)
        self.expected = self._text("What should have happened?", 65)
        self._form.addRow("Expected result *", self.expected)
        self.actual = self._text("What happened instead? Include the exact error text or where it stalled.", 85)
        self._form.addRow("Actual result / error *", self.actual)
        self.frequency = self._combo(FREQUENCIES)
        self._form.addRow("How often? *", self.frequency)
        self.game_platform = self._combo(PLATFORMS)
        self._form.addRow("Game platform *", self.game_platform)
        self.game_version = self._line("Game version, or Unknown")
        self._form.addRow("Game version *", self.game_version)
        self.mod_setup = self._text("List the manager, relevant mods and archive edits, or write None.", 65)
        self._form.addRow("Mods and manager *", self.mod_setup)
        self.clean_test = self._combo(CLEAN_TESTS)
        self._form.addRow("Test without mods *", self.clean_test)
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
        form_scroll.setWidget(form_page)
        self.tabs.addTab(form_scroll, "1. Describe")
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
        self.tabs.addTab(review_page, "2. Review and send")
        self.status = QLabel("Required fields are marked *. Unknown and Not tried are valid answers.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.collect_button = QPushButton("Collect and review")
        self.collect_button.clicked.connect(self._collect)
        self.send_button = QPushButton("Send report")
        self.send_button.clicked.connect(self._send)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.collect_button)
        buttons.addStretch(1)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        for widget in (self.summary, self.tool, self.game_version, self.contact):
            widget.textChanged.connect(self._invalidate)
        for widget in (self.steps, self.expected, self.actual, self.mod_setup):
            widget.textChanged.connect(self._invalidate)
        for widget in (self.frequency, self.game_platform, self.clean_test):
            widget.currentIndexChanged.connect(self._invalidate)
        for widget in (self.include_layout, self.include_logs):
            widget.toggled.connect(self._invalidate)
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
            str(self.clean_test.currentData()), self.contact.text().strip())

    @Slot()
    def _invalidate(self) -> None:
        self._generation += 1
        self._reviewed = None
        self.consent.setChecked(False)
        self.consent.setEnabled(False)
        self.preview.clear()
        self.image_tabs.clear()
        self.image_tabs.hide()
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
        errors = validate_details(details)
        if errors:
            self.status.setText("\n".join(errors))
            self.tabs.setCurrentIndex(0)
            return
        self._invalidate()
        request = ProblemReportRequest(details, self._snapshot, self.include_logs.isChecked(),
                                       self.include_layout.isChecked(), self._screenshots)
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
        self.tabs.setCurrentIndex(1)
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
        self.tabs.widget(0).setEnabled(enabled)

    @Slot()
    def _update_buttons(self) -> None:
        busy = self._collection is not None or self._reply is not None
        self.collect_button.setEnabled(not busy and not self._sent)
        self.send_button.setEnabled(bool(self._reviewed and self.consent.isChecked() and report_test_token()
                                         and not busy and not self._sent))

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
                    if status == 202:
                        raise ValueError("Delivery is still pending. Wait two minutes, then retry this report.")
                    raise ValueError("Delivery is not confirmed. The local draft is safe; retry this report when the service is available.")
                receipt = parse_report_receipt(body, report_id=self._reviewed.report_id)
                self._sent = True
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

    def closeEvent(self, event) -> None:
        self._shutdown()
        super().closeEvent(event)

    def reject(self) -> None:
        self._shutdown()
        super().reject()

    def done(self, result: int) -> None:
        self._shutdown()
        super().done(result)
