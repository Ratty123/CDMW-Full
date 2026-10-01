"""Describe, collect, review and explicitly submit a private problem report."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from html import escape

from PySide6.QtCore import QByteArray, QPoint, QSignalBlocker, QTimer, QUrl, Qt, Slot
from PySide6.QtGui import QImage, QPainter, QPalette, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QStyle, QStyleOptionButton, QStyleOptionComboBox, QTabWidget, QTextBrowser, QToolButton,
    QToolTip, QVBoxLayout, QWidget,
)

from cdmw.services.problem_report_service import (
    CLEAN_TESTS, DETAIL_RULES, FREQUENCIES, LAST_WORKING, PLATFORMS, PROBLEM_GUIDANCE, PROBLEM_TYPES,
    REPORT_DESTINATION, REPORT_ENDPOINT,
    ProblemDetails, ProblemReportRequest, ProblemSnapshot, ReviewedProblemReport,
    detail_errors, parse_report_receipt, report_delivery_failure, report_test_token,
)
from cdmw.workers.problem_report_workers import ProblemReportCollection


class _ReportComboBox(QComboBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
            QStyle.SubControl.SC_ComboBoxArrow, self)
        center = rect.center()
        painter = QPainter(self)
        painter.setPen(QPen(option.palette.color(QPalette.ColorRole.ButtonText), 1.5,
            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline([QPoint(center.x() - 4, center.y() - 2),
                              QPoint(center.x(), center.y() + 2),
                              QPoint(center.x() + 4, center.y() - 2)])


class _ReportCheckBox(QCheckBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.isChecked():
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        center = rect.center()
        painter = QPainter(self)
        role = QPalette.ColorRole.HighlightedText if self.isEnabled() else QPalette.ColorRole.Window
        painter.setPen(QPen(option.palette.color(role), 1.8,
            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline([QPoint(center.x() - 4, center.y()),
                              QPoint(center.x() - 1, center.y() + 3),
                              QPoint(center.x() + 5, center.y() - 4)])


class _ScreenshotPreview(QScrollArea):
    """Fit the reviewed image, with access to its original pixels."""

    def __init__(self, image: QImage, parent=None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap.fromImage(image)
        self._fit = True
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setWidget(self._label)
        self.set_fit(True)

    def set_fit(self, fit: bool) -> None:
        self._fit = fit
        self.setWidgetResizable(fit)
        self._update_image()

    def _update_image(self) -> None:
        if self._fit:
            self._label.setMinimumSize(0, 0)
            self._label.setMaximumSize(16777215, 16777215)
            pixmap = self._pixmap.scaled(self.viewport().size(),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = self._pixmap
            self._label.setFixedSize(pixmap.size())
        self._label.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_image()


class _FieldRow(QWidget):
    """Keep related fields together, stacking them when space is limited."""

    def __init__(self) -> None:
        super().__init__()
        self.fields = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.fields.setContentsMargins(0, 0, 0, 0)
        self.fields.setSpacing(16)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        threshold = max(500, self.fontMetrics().horizontalAdvance("Unexpected in-game result") * 2 + 105)
        self.fields.setDirection(QBoxLayout.Direction.TopToBottom if self.width() < threshold
                                 else QBoxLayout.Direction.LeftToRight)


class ProblemReportDialog(QDialog):
    _PAGE_FIELDS = (
        frozenset(("summary", "problem_type", "tool")),
        frozenset(("input_item", "steps", "expected", "actual", "frequency")),
        frozenset(("game_platform", "game_version", "mod_setup", "clean_test", "last_working", "changes", "contact")),
        frozenset(),
    )
    _REVIEW_PAGE = 4
    _RECEIPT_PAGE = 5

    def __init__(self, snapshot: ProblemSnapshot, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("ProblemReportDialog")
        self.setWindowTitle("Report a Problem — private test")
        self.resize(900, 760)
        self.setMinimumSize(460, 440)
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("ProblemReportHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(26, 20, 26, 20)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        title = QLabel("Report a problem")
        title.setObjectName("ProblemReportTitle")
        title_font = title.font()
        title_font.setPointSizeF(max(12.0, title_font.pointSizeF() + 5))
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addWidget(self._muted_label("One problem per report."))
        header_layout.addLayout(title_layout, 1)
        badge = self._muted_label("Private test")
        badge.setToolTip(REPORT_DESTINATION)
        header_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(header)
        body = QHBoxLayout()
        body.setSpacing(0)
        self.rail = QFrame()
        self.rail.setObjectName("ProblemReportRail")
        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(12, 20, 12, 20)
        rail_layout.setSpacing(8)
        self._step_names = ("Problem", "Reproduce", "Game and mods", "Evidence", "Review")
        self._step_buttons = []
        for index, name in enumerate(self._step_names):
            button = QPushButton(f"{index + 1}  {name}")
            button.setObjectName("ProblemReportStep")
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda _checked=False, page=index: self._navigate(page))
            rail_layout.addWidget(button)
            self._step_buttons.append(button)
        rail_layout.addStretch(1)
        rail_layout.addWidget(self._muted_label("Review before sending"))
        self.rail.setFixedWidth(max(170, self.fontMetrics().horizontalAdvance("Game and mods") + 65))
        body.addWidget(self.rail)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        self.step_picker = _ReportComboBox()
        self.step_picker.setAccessibleName("Report step")
        for index, name in enumerate(self._step_names):
            self.step_picker.addItem(f"{index + 1}  {name}", index)
        self.step_picker.activated.connect(self._navigate)
        self.step_picker.hide()
        content.addWidget(self.step_picker)
        self.tabs = QStackedWidget()
        content.addWidget(self.tabs, 1)
        body.addLayout(content, 1)
        layout.addLayout(body, 1)

        form = self._page("What went wrong?", "Start with one specific example.")
        self.summary = self._line("e.g. Archive Browser fails to extract a DDS")
        self._add_field(form, "Summary *", self.summary,
            "Name the action and tool that failed. Example: Archive Browser fails to extract a DDS.")
        problem_row = _FieldRow()
        self.problem_type = self._combo(PROBLEM_TYPES)
        self._problem_help = self._add_field(problem_row.fields, "Type of problem *", self.problem_type,
            PROBLEM_GUIDANCE["Other / unsure"])
        self.tool = self._line("Tool or menu where this happened")
        self.tool.setText(str(json.loads(snapshot.context_json).get("current_tab", "")))
        self._add_field(problem_row.fields, "Tool / workflow *", self.tool,
            "Filled from the current tool. Change it if the problem happened elsewhere.")
        form.addWidget(problem_row)
        form.addStretch(1)

        form = self._page("Help us repeat it", "Include the item and the actions you took.")
        self.input_item = self._line("Item, game-relative path, or Not applicable")
        self.input_item.setText(str(json.loads(snapshot.context_json).get("selected_archive_path", "Not applicable")))
        self._add_field(form, "Item or file *", self.input_item,
            "Use an item name or path inside the game archive. If no item or file is involved, write Not applicable.")
        self.steps = self._text("1. Open…\n2. Select…\n3. Click…", 90)
        self._steps_help = self._add_field(form, "Steps to reproduce *", self.steps,
            "Give one example someone else can repeat. Include the file or item and the buttons you used.")
        outcome_row = _FieldRow()
        self.expected = self._text("What should have happened?", 70)
        self._add_field(outcome_row.fields, "Expected result *", self.expected)
        self.actual = self._text("What happened or what error appeared?", 70)
        self._add_field(outcome_row.fields, "Actual result / error *", self.actual,
            "Copy the exact error, or say where it stalled. For a game result, describe CDMW and the game separately.")
        form.addWidget(outcome_row)
        self.frequency = self._combo(FREQUENCIES)
        self._add_field(form, "How often? *", self.frequency)
        form.addStretch(1)

        form = self._page("Game and mods", "Unknown and Not tried are valid answers.")
        self.game_platform = self._combo(PLATFORMS)
        self._add_field(form, "Game platform *", self.game_platform)
        self.game_version = self._line("Game version, or Unknown")
        self._add_field(form, "Game version *", self.game_version)
        self.mod_setup = self._text("Manager, relevant mods and install method, or None", 60)
        self._add_field(form, "Mods and manager *", self.mod_setup,
            "Include your mod manager, export/install method and relevant archive edits. Write None if you use no mods.")
        self.clean_test = self._combo(CLEAN_TESTS)
        self._add_field(form, "Test without mods *", self.clean_test,
            "Choose what you have already tried. You do not need to change or delete game files to submit a report.")
        self.last_working = self._combo(LAST_WORKING)
        self._add_field(form, "Did this work before? *", self.last_working)
        self.changes = self._text("Updates or changes, or Not sure yet", 60)
        self._add_field(form, "Recent changes *", self.changes,
            "Mention CDMW/game updates, mods, settings or file edits since it last worked. Not sure yet is fine.")
        self._changes_field = self.changes.parentWidget()
        self.contact = self._line("Nexus username or contact")
        self._add_field(form, "Contact (optional)", self.contact,
            "Include a contact only if you want the maintainer to follow up with you.")
        form.addStretch(1)

        form = self._page("Supporting evidence", "Choose what to include.")
        self.include_logs = _ReportCheckBox()
        self.include_logs.setText("Recent logs and operations")
        self.include_logs.setChecked(True)
        self._add_field(form, "Optional diagnostics", self.include_logs,
            "Include recent CDMW activity that may explain this problem. Paths and common credentials are redacted.")
        self.include_layout = _ReportCheckBox()
        self.include_layout.setText("Folder names and sizes")
        self.include_layout.setChecked(True)
        self._add_field(form, "", self.include_layout,
            "A bounded listing of relevant game folders. Links, backup folders and game file contents are excluded.")
        form.addWidget(self._muted_label("Game file contents are excluded."))
        screenshot_row = QWidget()
        screenshot_layout = QHBoxLayout(screenshot_row)
        screenshot_layout.setContentsMargins(0, 0, 0, 0)
        self.attach_button = QPushButton("Choose images…")
        self.attach_button.clicked.connect(self._choose_screenshots)
        self.clear_screenshots_button = QPushButton("Remove")
        self.clear_screenshots_button.clicked.connect(self._clear_screenshots)
        self.screenshot_label = self._muted_label("No screenshots · up to 3")
        self.screenshot_label.setWordWrap(True)
        screenshot_layout.addWidget(self.attach_button)
        screenshot_layout.addWidget(self.clear_screenshots_button)
        screenshot_layout.addWidget(self.screenshot_label, 1)
        self._add_field(form, "Screenshots (optional)", screenshot_row,
            "Choose PNG, JPEG or WebP images showing the error or last completed step. CDMW resizes them and removes metadata. Check for visible personal information.")
        form.addWidget(self._muted_label("Paths and common credentials are redacted."))
        form.addStretch(1)

        review_layout = self._page("Review your report", "Check the details and any screenshots.")
        self.preview = QTextBrowser()
        self.preview.setObjectName("ProblemReportSummary")
        self.preview.setReadOnly(True)
        self.preview.setOpenLinks(False)
        self.preview.setOpenExternalLinks(False)
        self.preview.anchorClicked.connect(self._review_link)
        self.preview.setMinimumHeight(220)
        review_layout.addWidget(self.preview, 1)
        self.full_details_button = QToolButton()
        self.full_details_button.setText("Full report details")
        self.full_details_button.setCheckable(True)
        self.full_details_button.toggled.connect(self._toggle_full_details)
        review_layout.addWidget(self.full_details_button)
        self._raw_preview = QPlainTextEdit()
        self._raw_preview.setReadOnly(True)
        self._raw_preview.setMinimumHeight(180)
        self._raw_preview.hide()
        review_layout.addWidget(self._raw_preview)
        self.image_tabs = QTabWidget()
        self.image_tabs.setMinimumHeight(180)
        self.image_tabs.setMaximumHeight(240)
        self.image_tabs.hide()
        review_layout.addWidget(self.image_tabs)
        self.fit_images = _ReportCheckBox()
        self.fit_images.setText("Fit screenshot")
        self.fit_images.setChecked(True)
        self.fit_images.toggled.connect(self._fit_images)
        self.fit_images.hide()
        review_layout.addWidget(self.fit_images)
        self.destination = self._muted_label("Private inbox · evidence kept for 90 days")
        self.destination.setToolTip(f"{REPORT_DESTINATION}\nEvidence expires after 90 days. Private issue summaries remain until removed.")
        review_layout.addWidget(self.destination)
        self.consent = _ReportCheckBox()
        self.consent.setText("I reviewed this report and agree to send it")
        self.consent.setEnabled(False)
        self.consent.toggled.connect(self._update_buttons)
        review_layout.addWidget(self.consent)

        receipt_layout = self._page("Report received", "Keep the reference for follow-up.", scroll=False)
        self.receipt_title = receipt_layout.itemAt(0).widget()
        self.receipt_reference = QLabel()
        self.receipt_reference.setObjectName("ProblemReportReference")
        self.receipt_reference.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        receipt_layout.addWidget(self.receipt_reference)
        self.receipt_summary = QLabel()
        self.receipt_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.receipt_summary.setWordWrap(True)
        receipt_layout.addWidget(self.receipt_summary)
        self.receipt_detail = self._muted_label("Private test inbox · evidence kept for 90 days")
        receipt_layout.addWidget(self.receipt_detail)
        receipt_layout.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("ProblemReportStatus")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QFrame()
        footer.setObjectName("ProblemReportFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(18, 12, 18, 12)
        self.required_note = self._muted_label("* Required")
        buttons.addWidget(self.required_note)
        self.load_button = QPushButton("Open draft…")
        self.load_button.setObjectName("ProblemReportQuietButton")
        self.load_button.clicked.connect(self._open_draft)
        buttons.addWidget(self.load_button)
        buttons.addStretch(1)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(lambda: self._navigate(max(0, self.tabs.currentIndex() - 1)))
        self.next_button = QPushButton("Continue")
        self.next_button.clicked.connect(self._next)
        self.next_button.setObjectName("EditorPrimaryButton")
        self.collect_button = QPushButton("Review report")
        self.collect_button.clicked.connect(self._collect)
        self.collect_button.setObjectName("EditorPrimaryButton")
        self.send_button = QPushButton("Send report")
        self.send_button.clicked.connect(self._send)
        self.send_button.setObjectName("EditorPrimaryButton")
        self.copy_receipt_button = QPushButton("Copy receipt")
        self.copy_receipt_button.clicked.connect(lambda: QApplication.clipboard().setText(self._receipt))
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.next_button)
        buttons.addWidget(self.collect_button)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.copy_receipt_button)
        buttons.addWidget(self.close_button)
        layout.addWidget(footer)
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
        self.tabs.currentChanged.connect(self._update_buttons)
        self._update_guidance()
        self._update_buttons()

    def _muted_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("ProblemReportMuted")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _page(self, title: str, hint: str, *, scroll: bool = True) -> QVBoxLayout:
        page = QWidget()
        page.setObjectName("ProblemReportPage")
        form = QVBoxLayout(page)
        form.setContentsMargins(26, 22, 26, 22)
        form.setSpacing(16)
        heading = QLabel(title)
        heading.setObjectName("ProblemReportTitle")
        font = heading.font()
        font.setPointSizeF(max(11.0, font.pointSizeF() + 3))
        font.setBold(True)
        heading.setFont(font)
        heading.setWordWrap(True)
        form.addWidget(heading)
        form.addWidget(self._muted_label(hint))
        if scroll:
            wrapper = QScrollArea()
            wrapper.setWidgetResizable(True)
            wrapper.setWidget(page)
            self.tabs.addWidget(wrapper)
        else:
            self.tabs.addWidget(page)
        return form

    def _add_field(self, layout: QBoxLayout, text: str, field: QWidget, help_text: str = "") -> QToolButton | None:
        group = QWidget()
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(6)
        group_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        caption = QHBoxLayout()
        caption.setContentsMargins(0, 0, 0, 0)
        caption.setSpacing(6)
        if text:
            label = QLabel(text)
            label.setObjectName("ProblemReportFieldLabel")
            label.setWordWrap(True)
            label.setMinimumHeight(max(20, label.sizeHint().height()))
            label.setBuddy(field)
            caption.addWidget(label)
        else:
            caption.addWidget(field)
        help_button = None
        if help_text:
            help_button = QToolButton()
            help_button.setObjectName("ProblemReportHelp")
            help_button.setText("?")
            help_button.setToolTip(help_text)
            help_button.setAccessibleName(f"Help: {text or field.text()}")
            help_button.clicked.connect(lambda: QToolTip.showText(
                help_button.mapToGlobal(QPoint(0, help_button.height())), help_button.toolTip(), help_button))
            caption.addWidget(help_button)
        caption.addStretch(1)
        group_layout.addLayout(caption)
        if text:
            group_layout.addWidget(field)
        layout.addWidget(group)
        return help_button

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
        widget = _ReportComboBox()
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
        guidance = PROBLEM_GUIDANCE.get(str(self.problem_type.currentData()), PROBLEM_GUIDANCE["Other / unsure"])
        self._problem_help.setToolTip(guidance)
        self._steps_help.setToolTip(guidance)
        changed = self.last_working.currentData() == "Worked before"
        self._changes_field.setVisible(changed)

    def _show_field_error(self, key: str, message: str) -> None:
        index = next(index for index, keys in enumerate(self._PAGE_FIELDS) if key in keys)
        self.tabs.setCurrentIndex(index)
        widget = getattr(self, key)
        self.tabs.widget(index).ensureWidgetVisible(widget)
        widget.setFocus()
        self.status.setText(message)
        self.status.show()

    @Slot()
    def _next(self) -> None:
        self._navigate(self.tabs.currentIndex() + 1)

    @Slot(int)
    def _navigate(self, index: int) -> None:
        if self._collection is not None or self._reply is not None or self._sent:
            return
        index = max(0, min(self._REVIEW_PAGE, index))
        required = frozenset().union(*self._PAGE_FIELDS[:index])
        for key, message in detail_errors(self._details()):
            if key in required:
                self._show_field_error(key, message)
                return
        if index == self._REVIEW_PAGE and self._reviewed is None:
            self._collect()
            return
        self.status.clear()
        self.tabs.setCurrentIndex(index)
        self._update_buttons()

    @Slot(QUrl)
    def _review_link(self, url: QUrl) -> None:
        if url.scheme() == "edit" and url.path().isdigit():
            self._navigate(int(url.path()))

    @Slot(bool)
    def _toggle_full_details(self, show: bool) -> None:
        self._raw_preview.setVisible(show)
        self.preview.setVisible(not show)

    @Slot(bool)
    def _fit_images(self, fit: bool) -> None:
        for index in range(self.image_tabs.count()):
            self.image_tabs.widget(index).set_fit(fit)

    def _render_review(self, payload: dict) -> None:
        details = payload["details"]
        text = lambda value: escape(str(value)).replace("\n", "<br>")
        def section(title: str, content: str, page: int) -> str:
            return (f'<p><b>{escape(title)}</b>&nbsp; <a href="edit:{page}">Edit</a></p>'
                    f'<p>{text(content)}</p>')
        result = [section(details["summary"],
            f'{details["problem_type"]} · {details["tool"]} · {details["frequency"]}', 0)]
        result.append(section("How to reproduce", details["steps"], 1))
        result.append(f'<p>{text(details["input_item"])}</p>')
        result.append(section("Expected result", details["expected"], 1))
        result.append(section("Actual result", details["actual"], 1))
        setup = (f'{details["game_platform"]} · {details["game_version"]}\n'
                 f'{details["mod_setup"]}\n'
                 f'Without mods: {details["clean_test"]}\n'
                 f'Worked before: {details["last_working"]}')
        if details["last_working"] == "Worked before":
            setup += f'\nRecent changes: {details["changes"]}'
        if details["contact"]:
            setup += f'\nContact: {details["contact"]}'
        result.append(section("Game and mods", setup, 2))
        evidence = ["CDMW version, system details and report context"]
        if "logs" in payload["evidence"]:
            evidence.append("Recent logs")
        if "folder_layout" in payload["evidence"]:
            evidence.append("Folder names and sizes")
        evidence.append(f'{len(payload["screenshots"])} screenshot(s)')
        result.append(section("Evidence", "\n".join(evidence), 3))
        self.preview.setHtml("".join(result))

    def _show_receipt(self, *, duplicate: bool = False, message: str = "") -> None:
        self.receipt_title.setText("Already reported" if duplicate else "Report received")
        self.receipt_reference.setText(self._receipt.split("(", 1)[0].strip())
        self.receipt_reference.setToolTip(self._receipt)
        self.receipt_summary.setText(json.loads(self._reviewed.body)["details"]["summary"])
        self.receipt_detail.setText(message if duplicate else "Private inbox · evidence kept for 90 days")
        self.tabs.setCurrentIndex(self._RECEIPT_PAGE)

    @Slot()
    def _invalidate(self) -> None:
        self._generation += 1
        self._reviewed = None
        self.consent.setChecked(False)
        self.consent.setEnabled(False)
        self.preview.clear()
        self._raw_preview.clear()
        while self.image_tabs.count():
            widget = self.image_tabs.widget(0)
            self.image_tabs.removeTab(0)
            widget.deleteLater()
        self.image_tabs.hide()
        self.fit_images.hide()
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
            self.status.show()
            return
        self._screenshots = tuple(files)
        self.screenshot_label.setText(f"{len(files)} screenshot(s) selected")
        self._invalidate()

    @Slot()
    def _clear_screenshots(self) -> None:
        self._screenshots = ()
        self.screenshot_label.setText("No screenshots · up to 3")
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
        payload = json.loads(result.body)
        if self._loading_draft:
            data = asdict(ProblemDetails(**payload["details"]))
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
            for widget, checked in ((self.include_logs, "logs" in payload["evidence"]),
                                    (self.include_layout, "folder_layout" in payload["evidence"])):
                with QSignalBlocker(widget):
                    widget.setChecked(checked)
            self._screenshots = ()
            self.screenshot_label.setText(f'{len(payload["screenshots"])} saved screenshot(s)')
            self.screenshot_label.setToolTip("Saved screenshots appear in Review. Choose them again if you edit and recollect.")
        self._render_review(payload)
        self._raw_preview.setPlainText(result.preview)
        import base64
        for shot in payload["screenshots"]:
            image = QImage.fromData(base64.b64decode(shot["data"]), "JPEG")
            scroll = _ScreenshotPreview(image)
            scroll.set_fit(self.fit_images.isChecked())
            self.image_tabs.addTab(scroll, shot["name"])
        self.image_tabs.setVisible(self.image_tabs.count() > 0)
        self.fit_images.setVisible(self.image_tabs.count() > 0)
        self.consent.setEnabled(True)
        self.tabs.setCurrentIndex(self._REVIEW_PAGE)
        self.status.setText("Draft saved locally." if report_test_token() else "Draft saved. Private test sending is unavailable.")
        self.status.setToolTip(str(result.draft_path))
        self._update_buttons()

    @Slot(int, str)
    def _failed(self, request_id: int, message: str) -> None:
        if not self._closed and request_id == self._generation:
            self.status.setText(message)
            self.status.show()

    @Slot()
    def _collection_stopped(self) -> None:
        self._collection = None
        if not self._closed:
            self._set_form_enabled(True)
            self._update_buttons()

    def _set_form_enabled(self, enabled: bool) -> None:
        for index in range(self._REVIEW_PAGE):
            self.tabs.widget(index).setEnabled(enabled)

    @Slot()
    def _update_buttons(self) -> None:
        busy = self._collection is not None or self._reply is not None
        index = self.tabs.currentIndex()
        seconds = max(0, math.ceil(self._retry_until - time.monotonic()))
        self.back_button.setVisible(index > 0 and not self._sent)
        self.back_button.setEnabled(not busy)
        self.next_button.setVisible(index < 3 and not self._sent)
        self.next_button.setEnabled(not busy)
        self.collect_button.setVisible(index == 3 and not self._sent)
        self.load_button.setEnabled(not busy and not self._sent)
        self.load_button.setVisible(not self._sent)
        self.copy_receipt_button.setVisible(bool(self._receipt))
        self.send_button.setVisible(index == self._REVIEW_PAGE and not self._sent)
        self.send_button.setText(f"Retry in {seconds // 60}:{seconds % 60:02d}" if seconds else "Send report")
        if not seconds:
            self._retry_timer.stop()
        self.collect_button.setEnabled(not busy and not self._sent)
        self.send_button.setEnabled(bool(self._reviewed and self.consent.isChecked() and report_test_token()
                                         and not busy and not self._sent and not seconds))
        for page, button in enumerate(self._step_buttons):
            with QSignalBlocker(button):
                button.setChecked(page == min(index, self._REVIEW_PAGE))
            button.setEnabled(not busy and not self._sent)
        with QSignalBlocker(self.step_picker):
            self.step_picker.setCurrentIndex(min(index, self._REVIEW_PAGE))
        self.step_picker.setEnabled(not busy and not self._sent)
        self.required_note.setVisible(self.width() >= 760 and index < self._REVIEW_PAGE and not self._sent)
        self.close_button.setText("Done" if self._sent else "Close")
        for button, active in ((self.next_button, index < 3 and not self._sent),
                               (self.collect_button, index == 3 and not self._sent),
                               (self.send_button, index == self._REVIEW_PAGE and not self._sent),
                               (self.close_button, self._sent)):
            button.setDefault(active)
        self.status.setVisible(bool(self.status.text()) and not self._sent)

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
                        self._show_receipt(duplicate=True, message=failure.message)
                    raise ValueError(failure.message)
                receipt = parse_report_receipt(body, report_id=self._reviewed.report_id)
                self._sent = True
                self._receipt = receipt
                self.status.setText(f"Report received: {receipt}\nKeep this receipt for follow-up. Local draft: {self._reviewed.draft_path}")
                self._show_receipt()
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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "rail"):
            compact = self.width() < 760
            self.rail.setVisible(not compact)
            self.step_picker.setVisible(compact)
            self.required_note.setVisible(not compact and self.tabs.currentIndex() < self._REVIEW_PAGE)

    def closeEvent(self, event) -> None:
        self._shutdown()
        super().closeEvent(event)

    def reject(self) -> None:
        self._shutdown()
        super().reject()

    def done(self, result: int) -> None:
        self._shutdown()
        super().done(result)
