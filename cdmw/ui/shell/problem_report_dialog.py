"""Describe, collect, review and explicitly submit a private problem report."""

from __future__ import annotations

import json
import math
import time
from contextlib import ExitStack
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
from cdmw.ui.shell.problem_report_catalog import (
    ACTION_HELP, GAME_INVOLVEMENT, INSTALL_METHODS, INTERFACE_ACTION, MOD_MANAGERS, MOD_STATES,
    REPORT_TOOLS, decode_item, decode_mod_setup, decode_tool, encode_item,
    encode_mod_setup, encode_tool, report_tool, tool_actions,
)


class _ReportComboBox(QComboBox):
    def enterEvent(self, event) -> None:
        # Keep long selections readable when a narrow window elides their text.
        self.setToolTip(self.currentText())
        super().enterEvent(event)

    def showPopup(self) -> None:
        for index in range(self.count()):
            self.setItemData(index, self.itemText(index), Qt.ItemDataRole.ToolTipRole)
        super().showPopup()

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
        frozenset(("summary", "problem_type", "tool", "workflow", "other_tool")),
        frozenset(("input_item", "input_source", "steps", "expected", "actual", "frequency", "waited", "progress_state")),
        frozenset(("game_involved", "game_platform", "game_version", "mod_state", "mod_manager", "install_method",
                   "mod_setup", "clean_test", "last_working", "changes", "contact")),
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
        self._restoring_form = False
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
        self._step_names = ("Problem", "Reproduce", "Setup", "Evidence", "Review")
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

        form = self._page("What went wrong?", "Choose the tool and the action that failed.")
        self.tool = self._combo(())
        for spec in REPORT_TOOLS:
            self.tool.addItem(spec.label, spec.key)
        self._add_field(form, "Tool *", self.tool,
            "Choose where the problem happened, even if another tool is currently open.")
        self.workflow = self._combo(())
        self.workflow.setEnabled(False)
        self._workflow_help = self._add_field(form, "Affected action *", self.workflow,
            "Choose the operation or panel involved. Other / not sure is available if none fits.")
        self.other_tool = self._line("Tool or feature name")
        self._add_field(form, "Other tool / feature *", self.other_tool)
        self.other_tool.parentWidget().hide()
        self.problem_type = self._combo(PROBLEM_TYPES)
        self._problem_help = self._add_field(form, "Type of problem *", self.problem_type,
            PROBLEM_GUIDANCE["Other / unsure"])
        self.summary = self._line("Briefly name the action and what went wrong")
        self._add_field(form, "Summary *", self.summary,
            "One specific problem. Example: Mesh Editor shows a black texture after importing a GLB.")
        form.addStretch(1)

        form = self._page("Help us repeat it", "Include the item and the actions you took.")
        self._reproduce_hint = form.itemAt(1).widget()
        self._input_fields = _FieldRow()
        self.input_source = self._combo(())
        self._add_field(self._input_fields.fields, "Input / source *", self.input_source,
            "Choose the source or format you actually used. Files are not attached to the report.")
        self.input_item = self._line("Item or filename")
        self._add_field(self._input_fields.fields, "Item or file *", self.input_item,
            "Use a name or game-relative path. Do not paste your full personal folder path.")
        form.addWidget(self._input_fields)
        self._item_label = self.input_item.parentWidget().findChild(QLabel, "ProblemReportFieldLabel")
        self.item_unknown = _ReportCheckBox()
        self.item_unknown.setText("I don't know the item / filename")
        form.addWidget(self.item_unknown)
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
        self._stall_fields = _FieldRow()
        self.waited = self._combo(("Under 1 minute", "1–5 minutes", "5–15 minutes", "Over 15 minutes", "Not sure"))
        self._add_field(self._stall_fields.fields, "How long did you wait? *", self.waited)
        self.progress_state = self._combo(("Progress kept changing", "Progress stopped", "App stopped responding", "No progress indicator", "Not sure"))
        self._add_field(self._stall_fields.fields, "Progress / response *", self.progress_state)
        form.addWidget(self._stall_fields)
        self.frequency = self._combo(FREQUENCIES)
        self._add_field(form, "How often? *", self.frequency)
        form.addStretch(1)

        form = self._page("Setup", "Unknown and Not tried are valid answers.")
        self.game_involved = self._combo(GAME_INVOLVEMENT)
        self._add_field(form, "Game files or mods involved? *", self.game_involved,
            "Choose No for an app-only issue. Choose Yes for game assets, exporting/installing a mod, or an in-game result.")
        self._game_fields = QWidget()
        game_form = QVBoxLayout(self._game_fields)
        game_form.setContentsMargins(0, 0, 0, 0)
        game_form.setSpacing(16)
        form.addWidget(self._game_fields)
        self.game_platform = self._combo(PLATFORMS)
        self._add_field(game_form, "Game platform *", self.game_platform)
        version_row = QWidget()
        version_layout = QHBoxLayout(version_row)
        version_layout.setContentsMargins(0, 0, 0, 0)
        self.game_version = self._line("Version shown by the game")
        self.version_unknown = _ReportCheckBox()
        self.version_unknown.setText("Unknown")
        version_layout.addWidget(self.game_version, 1)
        version_layout.addWidget(self.version_unknown)
        self._add_field(game_form, "Game version *", version_row,
            "Use the version shown in the game. Choose Unknown if you cannot check it.")
        self.mod_state = self._combo(MOD_STATES)
        self._add_field(game_form, "Installed mods *", self.mod_state)
        self._mod_fields = QWidget()
        mod_form = QVBoxLayout(self._mod_fields)
        mod_form.setContentsMargins(0, 0, 0, 0)
        mod_form.setSpacing(16)
        game_form.addWidget(self._mod_fields)
        self.mod_manager = self._combo(MOD_MANAGERS)
        self._add_field(mod_form, "Manager / installation tool *", self.mod_manager,
            "Choose what you actually used. These options describe your setup; they are not a list of supported CDMW exports.")
        self.install_method = self._combo(INSTALL_METHODS)
        self._add_field(mod_form, "Install method *", self.install_method,
            "Choose Not installed yet if export failed before installation. Use Not sure if you do not know.")
        self.mod_setup = self._text("Relevant mod names/versions and changes, or Not sure", 70)
        self._add_field(mod_form, "Relevant mods / details *", self.mod_setup,
            "Name the mods involved and any manual archive/file edits. For another manager/method, name it here.")
        self._mods_label = self.mod_setup.parentWidget().findChild(QLabel, "ProblemReportFieldLabel")
        self.clean_test = self._combo(CLEAN_TESTS)
        self._add_field(game_form, "Test without mods *", self.clean_test,
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
        self._layout_help = self._add_field(form, "", self.include_layout,
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
        self.destination = self._muted_label("Restricted GitHub inbox · evidence kept for 90 days")
        self.destination.setToolTip(REPORT_DESTINATION)
        self._privacy_help = self._add_field(review_layout, "", self.destination, REPORT_DESTINATION)
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
        self.receipt_detail = self._muted_label("Restricted GitHub inbox · evidence kept for 90 days")
        self.receipt_detail.setToolTip(REPORT_DESTINATION)
        self._add_field(receipt_layout, "", self.receipt_detail, REPORT_DESTINATION)
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
        for widget in (self.summary, self.other_tool, self.input_item, self.game_version, self.contact):
            widget.textChanged.connect(self._invalidate)
        for widget in (self.steps, self.expected, self.actual, self.mod_setup, self.changes):
            widget.textChanged.connect(self._invalidate)
        for widget in (self.frequency, self.game_platform, self.clean_test, self.last_working,
                       self.mod_manager, self.install_method, self.waited, self.progress_state):
            widget.currentIndexChanged.connect(self._invalidate)
        for widget in (self.include_layout, self.include_logs):
            widget.toggled.connect(self._invalidate)
        self.tool.currentIndexChanged.connect(self._tool_changed)
        self.workflow.currentIndexChanged.connect(self._questions_changed)
        self.input_source.currentIndexChanged.connect(self._questions_changed)
        self.problem_type.currentIndexChanged.connect(self._questions_changed)
        self.game_involved.currentIndexChanged.connect(self._questions_changed)
        self.mod_state.currentIndexChanged.connect(self._questions_changed)
        self.item_unknown.toggled.connect(self._questions_changed)
        self.version_unknown.toggled.connect(self._questions_changed)
        self.last_working.currentIndexChanged.connect(self._update_guidance)
        for key, _label, _minimum, maximum in DETAIL_RULES:
            widget = getattr(self, key)
            if isinstance(widget, QLineEdit):
                widget.setMaxLength(maximum)
        self.contact.setMaxLength(200)
        self.other_tool.setMaxLength(90)
        self.input_item.setMaxLength(240)
        self.tabs.currentChanged.connect(self._update_buttons)
        context = json.loads(snapshot.context_json)
        current = report_tool(str(context.get("current_tab", "")))
        if current.key != "other":
            self.tool.setCurrentIndex(self.tool.findData(current.key))
        if current.key == "archive_browser":
            self.input_item.setText(str(context.get("selected_archive_path", "")))
        self._questions_changed()
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
        widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        widget.setMinimumContentsLength(12)
        widget.addItem("Choose…", "")
        for choice in choices:
            widget.addItem(choice, choice)
        return widget

    @Slot()
    def _tool_changed(self) -> None:
        spec = report_tool(str(self.tool.currentData() or ""))
        for widget, choices in ((self.workflow, tool_actions(spec)), (self.input_source, spec.sources)):
            with QSignalBlocker(widget):
                widget.clear()
                widget.addItem("Choose…", "")
                for choice in choices:
                    widget.addItem(choice, choice)
        self.workflow.setEnabled(bool(self.tool.currentData()))
        with QSignalBlocker(self.problem_type):
            previous = self.problem_type.currentData()
            self.problem_type.clear()
            self.problem_type.addItem("Choose…", "")
            for choice in PROBLEM_TYPES:
                if spec.mod_output or choice not in {"Mod export / installation", "Unexpected in-game result"}:
                    self.problem_type.addItem("Incorrect result / other issue" if choice == "Other / unsure" else choice, choice)
            self.problem_type.setCurrentIndex(max(0, self.problem_type.findData(previous)))
        self.problem_type.setEnabled(bool(self.tool.currentData()))
        with QSignalBlocker(self.game_involved):
            self.game_involved.setCurrentIndex(self.game_involved.findData("Yes" if spec.game_related else "No"))
        self._questions_changed()

    def _item_applicable(self) -> bool:
        return bool(self.tool.currentData() and self.tool.currentData() != "application"
                    and self.workflow.currentData() != INTERFACE_ACTION)

    def _output_related(self) -> bool:
        spec = report_tool(str(self.tool.currentData() or ""))
        action = str(self.workflow.currentData() or "").casefold()
        return bool(spec.mod_output and (any(word in action for word in ("export", "build", "repackage", "patch"))
            or self.problem_type.currentData() in {"Mod export / installation", "Unexpected in-game result"}))

    def _mod_details_applicable(self) -> bool:
        return self.mod_state.currentData() == "Mods installed" or self._output_related()

    @Slot()
    def _questions_changed(self) -> None:
        spec = report_tool(str(self.tool.currentData() or ""))
        action = str(self.workflow.currentData() or "")
        self.other_tool.parentWidget().setVisible(self.tool.currentData() == "other")
        self._input_fields.setVisible(self._item_applicable())
        self.input_source.parentWidget().setVisible(self._item_applicable() and bool(spec.sources))
        self.input_item.parentWidget().setVisible(self._item_applicable())
        self.item_unknown.setVisible(self._item_applicable())
        self.item_unknown.setText("I don't know the exact setting / profile" if spec.key == "settings" else
                                  "I don't know the item / filename")
        self.input_item.setEnabled(not self.item_unknown.isChecked())
        self._item_label.setText(f"{spec.item_label or 'Item or file'} *")
        self.input_item.setPlaceholderText(spec.item_hint)
        self.steps.setPlaceholderText(spec.steps_hint if action != INTERFACE_ACTION else
            "1. Open the panel/window.\n2. Change the control or window size.\n3. Describe the result.")
        self._reproduce_hint.setText(f"{spec.label} · {action}" if action else "Include the item and the actions you took.")
        force_game = (self._output_related()
                      or self.problem_type.currentData() in {"Mod export / installation", "Unexpected in-game result"}
                      or action == "Game folder / archive setup"
                      or (self._item_applicable() and
                          str(self.input_source.currentData() or "").startswith(("Game ", "DDS from game"))))
        if force_game:
            with QSignalBlocker(self.game_involved):
                self.game_involved.setCurrentIndex(self.game_involved.findData("Yes"))
        self.game_involved.setEnabled(not force_game)
        game = self.game_involved.currentData() != "No"
        self._game_fields.setVisible(game)
        mods = self.mod_state.currentData()
        self._mod_fields.setVisible(self._mod_details_applicable())
        self._mods_label.setText("Relevant mods / output name *" if self._output_related() else "Relevant mods / details *")
        self.clean_test.parentWidget().setVisible(mods != "No mods installed")
        with QSignalBlocker(self.clean_test):
            previous = self.clean_test.currentData()
            self.clean_test.clear()
            self.clean_test.addItem("Choose…", "")
            for choice in CLEAN_TESTS:
                if choice != "No mods installed" or mods == "No mods installed":
                    self.clean_test.addItem(choice, choice)
            self.clean_test.setCurrentIndex(max(0, self.clean_test.findData(
                "No mods installed" if mods == "No mods installed" else previous)))
        self.game_version.setEnabled(not self.version_unknown.isChecked())
        self.include_layout.setEnabled(bool(self._snapshot.archive_root) and game)
        layout_reason = ("Not included for an app-only report." if not game else
                         "Unavailable: no game folder is configured." if not self._snapshot.archive_root else
                         "A bounded listing of relevant game folders. Links, backup folders and game file contents are excluded.")
        self.include_layout.setToolTip(layout_reason)
        self._layout_help.setToolTip(layout_reason)
        self._stall_fields.setVisible(self.problem_type.currentData() == "Slow or unresponsive")
        self._update_guidance()
        self._invalidate()

    def _details(self) -> ProblemDetails:
        spec = report_tool(str(self.tool.currentData() or ""))
        game = self.game_involved.currentData() != "No"
        item = "Unknown item / file" if self.item_unknown.isChecked() else self.input_item.text().strip()
        actual = self.actual.toPlainText().strip()
        if self.problem_type.currentData() == "Slow or unresponsive":
            actual = f"Waited: {self.waited.currentData() or ''}\nProgress: {self.progress_state.currentData() or ''}\nObserved: {actual}"
        return ProblemDetails(self.summary.text().strip(),
            encode_tool(spec, str(self.workflow.currentData() or ""), self.other_tool.text()),
            self.steps.toPlainText().strip(), self.expected.toPlainText().strip(), actual,
            str(self.frequency.currentData()),
            ("Unknown" if self.version_unknown.isChecked() else self.game_version.text().strip()) if game else "Not applicable",
            str(self.game_platform.currentData()) if game else "Other / unsure",
            encode_mod_setup(str(self.mod_state.currentData() or ""),
                             str(self.mod_manager.currentData() or "") if self._mod_details_applicable() else "",
                             str(self.install_method.currentData() or "") if self._mod_details_applicable() else "",
                             self.mod_setup.toPlainText() if self._mod_details_applicable() else "") if game else
                             "Not applicable (game files and mods are not involved)",
            str(self.clean_test.currentData()) if game else "Not tried", self.contact.text().strip(),
            str(self.problem_type.currentData()),
            encode_item(str(self.input_source.currentData() or ""), item) if self._item_applicable() else "Not applicable",
            str(self.last_working.currentData()), self.changes.toPlainText().strip())

    def _form_errors(self) -> tuple[tuple[str, str], ...]:
        errors = []
        if not self.tool.currentData():
            errors.append(("tool", "Tool: choose where the problem happened."))
        elif self.workflow.currentData() not in tool_actions(report_tool(str(self.tool.currentData()))):
            errors.append(("workflow", "Affected action: choose an operation or panel."))
        if self.tool.currentData() == "other" and len(self.other_tool.text().strip()) < 2:
            errors.append(("other_tool", "Other tool / feature: name the feature, or write Not sure."))
        spec = report_tool(str(self.tool.currentData() or ""))
        if self._item_applicable():
            if spec.sources and self.input_source.currentData() not in spec.sources:
                errors.append(("input_source", "Input / source: choose the format or source you used."))
            if not self.item_unknown.isChecked() and (len(self.input_item.text().strip()) < 4 or
                    self.input_item.text().strip().casefold() in {"none", "not applicable"}):
                errors.append(("input_item", "Item or file: name the affected item, or choose that you do not know it."))
        if self.problem_type.currentData() == "Slow or unresponsive":
            if not self.waited.currentData():
                errors.append(("waited", "How long did you wait: choose an option."))
            if not self.progress_state.currentData():
                errors.append(("progress_state", "Progress / response: choose an option."))
            if len(self.actual.toPlainText().strip()) < 10:
                errors.append(("actual", "Actual result: describe what stalled or stopped responding."))
        if not self.game_involved.currentData():
            errors.append(("game_involved", "Game files or mods involved: choose an option."))
        elif self.game_involved.currentData() != "No":
            if self.mod_state.currentData() not in MOD_STATES:
                errors.append(("mod_state", "Installed mods: choose an option."))
            if self._mod_details_applicable():
                if self.mod_manager.currentData() not in MOD_MANAGERS:
                    errors.append(("mod_manager", "Manager / installation tool: choose an option."))
                if self.install_method.currentData() not in INSTALL_METHODS:
                    errors.append(("install_method", "Install method: choose an option."))
                if len(self.mod_setup.toPlainText().strip()) < 4:
                    errors.append(("mod_setup", "Relevant mods: name the mods, or write Not sure."))
        errors.extend(detail_errors(self._details()))
        return tuple(errors)

    def _restore_details(self, data: dict) -> None:
        """Present saved choices without invalidating the exact reviewed retry body."""
        self._restoring_form = True
        try:
            with ExitStack() as stack:
                for name in ("tool", "workflow", "other_tool", "problem_type", "summary", "input_source", "input_item",
                             "item_unknown", "steps", "expected", "actual", "waited", "progress_state", "frequency",
                             "game_involved", "game_platform", "game_version", "version_unknown", "mod_state",
                             "mod_manager", "install_method", "mod_setup", "clean_test", "last_working", "changes", "contact"):
                    stack.enter_context(QSignalBlocker(getattr(self, name)))
                spec, action, other = decode_tool(data["tool"])
                self.tool.setCurrentIndex(self.tool.findData(spec.key))
                self._tool_changed()
                self.workflow.setCurrentIndex(max(0, self.workflow.findData(action)))
                self.other_tool.setText(other)
                source, item = decode_item(data["input_item"])
                self.input_source.setCurrentIndex(max(0, self.input_source.findData(source)))
                self.item_unknown.setChecked(item == "Unknown item / file")
                self.input_item.setText("" if self.item_unknown.isChecked() else item)
                for key in ("summary", "contact"):
                    getattr(self, key).setText(data[key])
                for key in ("steps", "expected", "changes"):
                    getattr(self, key).setPlainText(data[key])
                actual = data["actual"]
                if actual.startswith("Waited: ") and "\nObserved: " in actual:
                    timing, actual = actual.split("\nObserved: ", 1)
                    fields = dict(line.split(": ", 1) for line in timing.splitlines() if ": " in line)
                    self.waited.setCurrentIndex(max(0, self.waited.findData(fields.get("Waited", ""))))
                    self.progress_state.setCurrentIndex(max(0, self.progress_state.findData(fields.get("Progress", ""))))
                self.actual.setPlainText(actual)
                for key in ("frequency", "problem_type", "game_platform", "last_working"):
                    widget = getattr(self, key)
                    widget.setCurrentIndex(max(0, widget.findData(data[key])))
                game = not (data["game_version"] == "Not applicable" and data["mod_setup"].startswith("Not applicable"))
                self.game_involved.setCurrentIndex(self.game_involved.findData("Yes" if game else "No"))
                self.version_unknown.setChecked(data["game_version"] == "Unknown")
                self.game_version.setText("" if self.version_unknown.isChecked() else data["game_version"])
                state, manager, method, notes = decode_mod_setup(data["mod_setup"])
                self.mod_state.setCurrentIndex(max(0, self.mod_state.findData(state)))
                self.mod_manager.setCurrentIndex(max(0, self.mod_manager.findData(manager)))
                self.install_method.setCurrentIndex(max(0, self.install_method.findData(method)))
                self.mod_setup.setPlainText(notes)
                self._questions_changed()
                self.clean_test.setCurrentIndex(max(0, self.clean_test.findData(data["clean_test"])))
        finally:
            self._restoring_form = False

    @Slot()
    def _update_guidance(self) -> None:
        guidance = PROBLEM_GUIDANCE.get(str(self.problem_type.currentData()), PROBLEM_GUIDANCE["Other / unsure"])
        self._problem_help.setToolTip(guidance)
        spec = report_tool(str(self.tool.currentData() or ""))
        action_help = ACTION_HELP.get(str(self.workflow.currentData() or ""), spec.help)
        self._workflow_help.setToolTip(action_help)
        self._steps_help.setToolTip(f"{action_help}\n\n{guidance}")
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
        for key, message in self._form_errors():
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
        setup = ("Game files and mods are not involved.\n" if details["game_version"] == "Not applicable" and
                 details["mod_setup"].startswith("Not applicable") else
                 f'{details["game_platform"]} · {details["game_version"]}\n{details["mod_setup"]}\n'
                 f'Without mods: {details["clean_test"]}\n')
        setup += f'Worked before: {details["last_working"]}'
        if details["last_working"] == "Worked before":
            setup += f'\nRecent changes: {details["changes"]}'
        if details["contact"]:
            setup += f'\nContact: {details["contact"]}'
        result.append(section("Setup", setup, 2))
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
        self.receipt_detail.setText(message if duplicate else "Restricted GitHub inbox · evidence kept for 90 days")
        self.tabs.setCurrentIndex(self._RECEIPT_PAGE)

    @Slot()
    def _invalidate(self) -> None:
        if self._restoring_form:
            return
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
        errors = self._form_errors()
        if errors:
            self._show_field_error(*errors[0])
            return
        self._invalidate()
        request = ProblemReportRequest(details, self._snapshot, self.include_logs.isChecked(),
                                       self.include_layout.isChecked() and self.include_layout.isEnabled(), self._screenshots)
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
            self._restore_details(data)
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
