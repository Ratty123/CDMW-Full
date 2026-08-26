"""Compact-only presentation adapters for the fifteen production tool widgets.

The adapters do not construct, clone, or reparent tools.  They tighten the
existing layouts, keep one-pixel structural splitter dividers, hide log/status
chrome already represented by the compact shell, and give each authoritative
splitter responsive proportions.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QWidget,
)

from cdmw.ui.shell.compact.config import COMPACT_SHELL_VARIANT, read_shell_variant


@dataclass(frozen=True, slots=True)
class CompactSplitterRule:
    orientation: Qt.Orientation
    ordinal: int
    ratios: tuple[int, ...]
    minimum_spans: tuple[int | None, ...] = ()
    maximum_spans: tuple[int | None, ...] = ()


@dataclass(frozen=True, slots=True)
class CompactPresentationSpec:
    reference_filename: str
    root_margin: int = 8
    splitter_rules: tuple[CompactSplitterRule, ...] = ()
    hidden_attributes: tuple[tuple[str, str], ...] = ()
    hidden_text_prefixes: tuple[str, ...] = ()


_HORIZONTAL = Qt.Orientation.Horizontal
_VERTICAL = Qt.Orientation.Vertical


COMPACT_PRESENTATION_SPECS: Mapping[str, CompactPresentationSpec] = MappingProxyType(
    {
        "archive_browser": CompactPresentationSpec(
            "01-browse-archives.png",
            splitter_rules=(
                CompactSplitterRule(
                    _HORIZONTAL,
                    0,
                    (18, 32, 50),
                    (190, 240, 260),
                    (330, None, None),
                ),
            ),
            hidden_attributes=(("archive_log_view", "parent"),),
        ),
        "model_library": CompactPresentationSpec(
            "02-model-library.png",
            splitter_rules=(
                CompactSplitterRule(_HORIZONTAL, 0, (16, 84), (190, 460), (300, None)),
                CompactSplitterRule(_HORIZONTAL, 1, (52, 48), (240, 260)),
            ),
            hidden_attributes=(("status_label", "widget"),),
        ),
        "item_icons": CompactPresentationSpec(
            "03-item-icons.png",
            splitter_rules=(
                CompactSplitterRule(
                    _HORIZONTAL,
                    0,
                    (18, 45, 37),
                    (160, 260, 250),
                    (280, None, None),
                ),
            ),
            hidden_attributes=(
                ("roots_status_label", "widget"),
                ("library_status_label", "widget"),
            ),
        ),
        "new_item_studio": CompactPresentationSpec(
            "04-create-new-item.png",
            root_margin=0,
        ),
        # The current Mesh Editor is resident-renderer-first.  Its retired Qt
        # palette panes stay hidden; only generic compact spacing/dividers apply.
        "mesh_editor": CompactPresentationSpec(
            "05-mesh-editor.png",
            root_margin=0,
        ),
        "placement_studio": CompactPresentationSpec(
            "06-placement-animation.png",
            root_margin=0,
            splitter_rules=(
                CompactSplitterRule(_VERTICAL, 0, (78, 22), (280, 96)),
                CompactSplitterRule(_HORIZONTAL, 0, (22, 48, 30), (180, 340, 260)),
            ),
        ),
        "texture_workflow": CompactPresentationSpec(
            "07-upscale-process-textures.png",
            splitter_rules=(
                CompactSplitterRule(_HORIZONTAL, 0, (36, 64), (230, 340), (480, None)),
                CompactSplitterRule(_VERTICAL, 0, (44, 56), (170, 220)),
                CompactSplitterRule(_HORIZONTAL, 1, (50, 50), (180, 180)),
            ),
        ),
        "replace_assistant": CompactPresentationSpec(
            "08-replace-textures.png",
            splitter_rules=(
                CompactSplitterRule(
                    _HORIZONTAL,
                    0,
                    (34, 40, 26),
                    (220, 260, 210),
                    (520, None, 420),
                ),
            ),
            hidden_attributes=(("log_view", "widget"), ("status_label", "widget")),
        ),
        "recolor_variants": CompactPresentationSpec(
            "09-recolor-variants.png",
            splitter_rules=(
                CompactSplitterRule(
                    _HORIZONTAL,
                    0,
                    (21, 46, 33),
                    (190, 300, 240),
                    (390, None, None),
                ),
            ),
            hidden_attributes=(("log_edit", "section"),),
        ),
        "texture_editor": CompactPresentationSpec(
            "10-texture-editor.png",
            root_margin=8,
            splitter_rules=(
                CompactSplitterRule(
                    _HORIZONTAL,
                    0,
                    (18, 52, 30),
                    (170, 320, 240),
                    (280, None, 420),
                ),
            ),
            hidden_attributes=(("status_label", "widget"),),
        ),
        "mod_package_retrofit": CompactPresentationSpec(
            "11-repackage-mods.png",
            splitter_rules=(
                CompactSplitterRule(_HORIZONTAL, 0, (60, 40), (340, 260)),
            ),
            hidden_attributes=(("status_label", "widget"),),
            hidden_text_prefixes=(
                "Scan loose or zipped mod packages and repackage them",
                "Choose a target profile per row",
                "Scan to see package readiness summary.",
                "Status: Ready packages",
            ),
        ),
        # Source-authoritative Format Explorer keeps its proven table-over-detail
        # orientation; the mockup's hierarchy is preserved without reparenting.
        "format_explorer": CompactPresentationSpec("12-inspect-file-formats.png"),
        "translation_studio": CompactPresentationSpec("13-edit-translations.png"),
        "research": CompactPresentationSpec(
            "14-asset-research.png",
            splitter_rules=(
                CompactSplitterRule(_HORIZONTAL, 0, (68, 32), (380, 260)),
                CompactSplitterRule(_HORIZONTAL, 1, (42, 58), (220, 300)),
            ),
            hidden_attributes=(
                ("refresh_status_label", "widget"),
                ("refresh_progress", "widget"),
            ),
        ),
        "text_search": CompactPresentationSpec(
            "15-search-file-text.png",
            splitter_rules=(
                CompactSplitterRule(_HORIZONTAL, 0, (27, 33, 40), (190, 220, 250)),
            ),
            hidden_attributes=(("log_view", "section"),),
            hidden_text_prefixes=(
                "Read-only search across archive or loose text-like files.",
            ),
        ),
    }
)


def _is_compact_window(window: object) -> bool:
    for name in ("is_compact_shell", "_compact_shell_active", "compact_shell_active"):
        value = getattr(window, name, None)
        if callable(value):
            try:
                value = value()
            except TypeError:
                value = False
        if value is True:
            return True
    for name in ("shell_variant", "_shell_variant"):
        if str(getattr(window, name, "") or "").strip() == COMPACT_SHELL_VARIANT:
            return True
    settings = getattr(window, "settings", None)
    return settings is not None and read_shell_variant(settings) == COMPACT_SHELL_VARIANT


def _compact_layout(layout: QLayout, *, root_margin: int | None = None) -> None:
    if root_margin is not None:
        layout.setContentsMargins(root_margin, root_margin, root_margin, root_margin)
    else:
        margins = layout.contentsMargins()
        if max(margins.left(), margins.top(), margins.right(), margins.bottom()) > 12:
            layout.setContentsMargins(
                min(margins.left(), 10),
                min(margins.top(), 10),
                min(margins.right(), 10),
                min(margins.bottom(), 10),
            )
    if layout.spacing() > 8:
        layout.setSpacing(6)


def _hide_presentation_attribute(
    window: object,
    widget: QWidget,
    attribute: str,
    scope: str,
) -> None:
    candidate = None
    for owner in (widget, getattr(widget, "_retrofit_ui", None), window):
        if owner is not None:
            candidate = getattr(owner, attribute, None)
        if candidate is not None:
            break
    if not isinstance(candidate, QWidget):
        return
    target = candidate
    if scope == "parent" and candidate.parentWidget() is not None:
        target = candidate.parentWidget()
    elif scope == "section":
        current = candidate.parentWidget()
        fallback = current
        for _depth in range(5):
            if current is None or current is widget:
                break
            if isinstance(current, QGroupBox) or type(current).__name__ == "FlatSectionPanel":
                target = current
                break
            current = current.parentWidget()
        else:
            target = fallback or candidate
    target.setVisible(False)


def _replace_new_item_label(text: str) -> str:
    return str(text or "").replace("New Item Studio", "Create New Item")


def _apply_compact_tool_labels(key: str, widget: QWidget) -> None:
    if key not in {"archive_browser", "model_library", "new_item_studio"}:
        return
    for button in widget.findChildren(QAbstractButton):
        replaced = _replace_new_item_label(button.text())
        if replaced != button.text():
            button.setText(replaced)
    for label in widget.findChildren(QLabel):
        replaced = _replace_new_item_label(label.text())
        if replaced != label.text():
            label.setText(replaced)
    for action in widget.findChildren(QAction):
        replaced = _replace_new_item_label(action.text())
        if replaced != action.text():
            action.setText(replaced)
    for child in (widget, *widget.findChildren(QWidget)):
        tooltip = child.toolTip()
        replaced = _replace_new_item_label(tooltip)
        if replaced != tooltip:
            child.setToolTip(replaced)


def _hide_redundant_text(widget: QWidget, spec: CompactPresentationSpec) -> None:
    if not spec.hidden_text_prefixes:
        return
    for label in widget.findChildren(QLabel):
        text = str(label.text() or "").strip()
        if any(text.startswith(prefix) for prefix in spec.hidden_text_prefixes):
            label.setVisible(False)


def _apply_tool_specific_presentation(window: object, key: str, widget: QWidget) -> None:
    if key == "archive_browser":
        _build_archive_command_strip(window, widget)

    elif key == "new_item_studio":
        highlight = widget.palette().color(QPalette.ColorRole.Highlight)
        stylesheet = widget.styleSheet()
        if "#078de5" in stylesheet.lower():
            widget.setStyleSheet(stylesheet.replace("#078de5", highlight.name()))
        steps = getattr(widget, "steps", None)
        if isinstance(steps, QWidget):
            steps._active_color = highlight  # type: ignore[attr-defined]
            steps.update()
            for button in getattr(steps, "_buttons", ()):
                if isinstance(button, QWidget):
                    button.update()

    elif key == "texture_workflow":
        root_layout = widget.layout()
        if root_layout is not None and not bool(widget.property("compactActionsMoved")):
            for index in range(root_layout.count() - 1, -1, -1):
                item = root_layout.itemAt(index)
                action_layout = item.layout() if item is not None else None
                if action_layout is None:
                    continue
                root_layout.takeAt(index)
                root_layout.insertLayout(0, action_layout)
                widget.setProperty("compactActionsMoved", True)
                break

        paths_section = getattr(window, "paths_section", None)
        left_panel = getattr(window, "left_panel", None)
        left_layout = left_panel.layout() if isinstance(left_panel, QWidget) else None
        if (
            isinstance(paths_section, QWidget)
            and left_layout is not None
            and left_layout.indexOf(paths_section) < 0
        ):
            left_layout.insertWidget(0, paths_section)
            set_expanded = getattr(paths_section, "set_expanded", None)
            if callable(set_expanded):
                set_expanded(True)

    elif key == "research":
        refresh_button = getattr(widget, "refresh_button", None)
        if isinstance(refresh_button, QAbstractButton):
            refresh_button.setMaximumWidth(160)

    elif key == "text_search":
        for panel in widget.findChildren(QWidget):
            title_label = getattr(panel, "title_label", None)
            header_widget = getattr(panel, "header_widget", None)
            if (
                isinstance(title_label, QLabel)
                and title_label.text().strip() == "Text Search"
                and isinstance(header_widget, QWidget)
            ):
                header_widget.setVisible(False)
                break


def _build_archive_command_strip(window: object, widget: QWidget) -> None:
    existing = getattr(widget, "_cdmw_compact_archive_command_strip", None)
    if isinstance(existing, QWidget):
        return
    root_layout = widget.layout()
    if root_layout is None:
        return

    names = (
        "archive_scan_button",
        "archive_refresh_scan_button",
        "archive_asset_catalog_button",
        "archive_filter_edit",
        "archive_path_search_button",
        "archive_extension_filter_combo",
        "archive_extension_picker_button",
    )
    controls = [getattr(window, name, None) for name in names]
    if not all(isinstance(control, QWidget) for control in controls):
        return
    search_group = controls[0].parentWidget()

    strip = QFrame(widget)
    strip.setObjectName("CompactArchiveCommandStrip")
    strip.setFrameShape(QFrame.Shape.NoFrame)
    layout = QHBoxLayout(strip)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(8)
    scan, refresh, finder, search_edit, search_button, extension, extension_picker = controls
    for button in (scan, refresh, finder):
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(button)
    search_edit.setMinimumWidth(120)
    search_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    layout.addWidget(search_edit, stretch=1)
    layout.addWidget(search_button)
    extension.setMinimumWidth(90)
    extension.setMaximumWidth(180)
    layout.addWidget(extension)
    layout.addWidget(extension_picker)

    filters_group = next(
        (
            group
            for group in getattr(window, "archive_controls_group", widget).findChildren(QGroupBox)
            if group.title().strip() == "Filters"
        ),
        None,
    )
    more_filters = QPushButton("More Filters")
    more_filters.setCheckable(True)
    more_filters.setToolTip("Show or hide Archive Browser filters only.")
    if isinstance(filters_group, QGroupBox):
        filters_group.setVisible(False)
        more_filters.toggled.connect(filters_group.setVisible)
    else:
        more_filters.setEnabled(False)
    layout.addWidget(more_filters)
    if isinstance(search_group, QGroupBox):
        search_group.setVisible(False)
    root_layout.insertWidget(0, strip)
    widget._cdmw_compact_archive_command_strip = strip  # type: ignore[attr-defined]
    widget._cdmw_compact_archive_more_filters_button = more_filters  # type: ignore[attr-defined]


def _span(splitter: QSplitter) -> int:
    return splitter.width() if splitter.orientation() == _HORIZONTAL else splitter.height()


def _apply_span_bounds(splitter: QSplitter, rule: CompactSplitterRule) -> None:
    for index in range(min(splitter.count(), len(rule.ratios))):
        child = splitter.widget(index)
        minimum = rule.minimum_spans[index] if index < len(rule.minimum_spans) else None
        maximum = rule.maximum_spans[index] if index < len(rule.maximum_spans) else None
        if splitter.orientation() == _HORIZONTAL:
            if minimum is not None:
                child.setMinimumWidth(minimum)
            if maximum is not None:
                child.setMaximumWidth(maximum)
        else:
            if minimum is not None:
                child.setMinimumHeight(minimum)
            if maximum is not None:
                child.setMaximumHeight(maximum)


def _tune_splitter(splitter: QSplitter, rule: CompactSplitterRule) -> None:
    if splitter.count() != len(rule.ratios):
        return
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(1)
    splitter.setOpaqueResize(True)
    _apply_span_bounds(splitter, rule)
    for index, ratio in enumerate(rule.ratios):
        splitter.setStretchFactor(index, max(0, int(ratio)))

    available = max(0, _span(splitter) - splitter.handleWidth() * (splitter.count() - 1))
    if available < splitter.count() * 10:
        return
    total = max(1, sum(max(0, ratio) for ratio in rule.ratios))
    target = [max(1, round(available * max(0, ratio) / total)) for ratio in rule.ratios]
    current = splitter.sizes()
    if len(current) != len(target) or any(abs(left - right) > 2 for left, right in zip(current, target)):
        splitter.setSizes(target)


def _apply_splitter_rules(widget: QWidget, spec: CompactPresentationSpec) -> None:
    splitters = widget.findChildren(QSplitter)
    for splitter in splitters:
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
    by_orientation = {
        orientation: [splitter for splitter in splitters if splitter.orientation() == orientation]
        for orientation in (_HORIZONTAL, _VERTICAL)
    }
    for rule in spec.splitter_rules:
        matching = by_orientation[rule.orientation]
        if 0 <= rule.ordinal < len(matching):
            _tune_splitter(matching[rule.ordinal], rule)


class _CompactPresentationResizeFilter(QObject):
    def __init__(self, widget: QWidget, spec: CompactPresentationSpec) -> None:
        super().__init__(widget)
        self.widget = widget
        self.spec = spec
        self._refreshing = False

    def refresh(self) -> None:
        widget = getattr(self, "widget", None)
        if not isinstance(widget, QWidget) or getattr(self, "_refreshing", False):
            return
        self._refreshing = True
        try:
            _apply_splitter_rules(widget, self.spec)
        finally:
            self._refreshing = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt contract
        if watched is getattr(self, "widget", None) and event.type() in {
            QEvent.Type.Show,
            QEvent.Type.Resize,
        }:
            self.refresh()
        return False


def apply_compact_presentation(window: object, key: str, widget: QWidget) -> bool:
    """Adapt one existing production widget when the active shell is compact.

    Returns ``True`` when ``key`` has a registered compact presentation and the
    current window is compact.  Repeated calls retune geometry without adding
    another event filter.
    """

    tool_key = str(key or "").strip()
    spec = COMPACT_PRESENTATION_SPECS.get(tool_key)
    if spec is None or not isinstance(widget, QWidget) or not _is_compact_window(window):
        return False

    widget.setProperty("compactPresentation", True)
    widget.setProperty("compactToolKey", tool_key)
    widget.setProperty("compactReferenceFilename", spec.reference_filename)
    root_layout = widget.layout()
    if root_layout is not None:
        _compact_layout(root_layout, root_margin=spec.root_margin)
    for layout in widget.findChildren(QLayout):
        if layout is not root_layout:
            _compact_layout(layout)
    for attribute, scope in spec.hidden_attributes:
        _hide_presentation_attribute(window, widget, attribute, scope)
    _hide_redundant_text(widget, spec)
    _apply_compact_tool_labels(tool_key, widget)
    _apply_tool_specific_presentation(window, tool_key, widget)
    _apply_splitter_rules(widget, spec)

    resize_filter = getattr(widget, "_cdmw_compact_presentation_filter", None)
    if not isinstance(resize_filter, _CompactPresentationResizeFilter):
        resize_filter = _CompactPresentationResizeFilter(widget, spec)
        widget.installEventFilter(resize_filter)
        widget._cdmw_compact_presentation_filter = resize_filter  # type: ignore[attr-defined]
    else:
        resize_filter.spec = spec
    resize_filter.refresh()
    return True


__all__ = [
    "COMPACT_PRESENTATION_SPECS",
    "CompactPresentationSpec",
    "CompactSplitterRule",
    "apply_compact_presentation",
]
