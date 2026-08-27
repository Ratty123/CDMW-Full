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
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QWidgetAction,
    QWidget,
)

from cdmw.ui.shell.compact.config import (
    COMPACT_SHELL_VARIANT,
    DEFAULT_COMPACT_SHELL_THEME,
    active_shell_theme_key,
    read_shell_variant,
)
from cdmw.ui.themes import _compact_tool_shape_override_stylesheet, get_theme


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
    root_margin: int = 6
    splitter_rules: tuple[CompactSplitterRule, ...] = ()
    hidden_attributes: tuple[tuple[str, str], ...] = ()
    hidden_text_prefixes: tuple[str, ...] = ()


_HORIZONTAL = Qt.Orientation.Horizontal
_VERTICAL = Qt.Orientation.Vertical

_COMPACT_BUTTON_LABELS: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "item_icons": MappingProxyType(
            {
                "Add Folder...": "Add",
                "Edited Folder": "Folder",
                "Save Metadata": "Save",
                "Open In Texture Editor": "Open",
                "Delete Source": "Delete",
                "Refresh Targets": "Refresh",
                "Use Archive Selection": "Use Selection",
                "Open In Archive Browser": "Open",
                "Preview Final": "Preview",
                "Export Generated Icon...": "Export",
                "Add To Existing Loose Mod...": "Add",
            }
        ),
        "mesh_editor": MappingProxyType(
            {
                "Run validation": "Check",
                "Export Mesh File": "Export",
                "Build Mod": "Build",
                "Install as Overlay": "Apply",
                "Restore Last Overlay Install": "Reset",
            }
        ),
        "placement_studio": MappingProxyType(
            {
                "Swap animations...": "Swap",
                "Recent actions...": "History",
                "Check Fit/Clipping": "Fit",
                "Revert point": "Reset",
                "New point…": "Add",
                "Aim with this": "Use",
                "Turn it the right way up": "Rotate",
                "Packages…": "Packages",
            }
        ),
        "replace_assistant": MappingProxyType(
            {
                "Open In Texture Editor": "Open",
                "Choose Local Original": "Local",
                "Choose Archive Original": "Original",
                "Clear existing output package before build": "Clear",
                "Mirror Texture Workflow": "Mirror",
                "Definitive Mod Manager": "Mod Manager",
            }
        ),
        "recolor_variants": MappingProxyType(
            {
                "Import JSON": "Import",
                "Export JSON": "Export",
                "Save Templates": "Save",
                "Review Matches": "Review",
            }
        ),
        "research": MappingProxyType(
            {
                "Refresh List": "Refresh",
                "Use In References": "References",
                "Use In Notes": "Notes",
            }
        ),
        "text_search": MappingProxyType({"Export Selected": "Export"}),
        "texture_editor": MappingProxyType({"Save Preset": "Save"}),
    }
)


COMPACT_PRESENTATION_SPECS: Mapping[str, CompactPresentationSpec] = MappingProxyType(
    {
        "archive_browser": CompactPresentationSpec(
            "01-browse-archives.png",
            splitter_rules=(
                CompactSplitterRule(
                    _HORIZONTAL,
                    0,
                    (0, 38, 62),
                    (0, 260, 360),
                    (0, None, None),
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
                    (18, 42, 40),
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
                CompactSplitterRule(_HORIZONTAL, 0, (30, 70), (230, 340), (420, None)),
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
                    (31, 38, 31),
                    (210, 260, 240),
                    (500, None, 440),
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
                    (26, 44, 30),
                    (220, 300, 240),
                    (430, None, None),
                ),
            ),
            hidden_attributes=(("log_edit", "section"),),
        ),
        "texture_editor": CompactPresentationSpec(
            "10-texture-editor.png",
            root_margin=6,
            splitter_rules=(
                CompactSplitterRule(
                    _HORIZONTAL,
                    0,
                    (17, 49, 34),
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
        # Source-authoritative Format Explorer keeps its table-and-detail split;
        # the mockup's hierarchy is preserved without shell-side reparenting.
        "format_explorer": CompactPresentationSpec("12-inspect-file-formats.png"),
        "translation_studio": CompactPresentationSpec("13-edit-translations.png"),
        "research": CompactPresentationSpec(
            "14-asset-research.png",
            splitter_rules=(
                CompactSplitterRule(_HORIZONTAL, 0, (64, 36), (360, 280)),
                CompactSplitterRule(_HORIZONTAL, 1, (42, 58), (220, 300)),
                CompactSplitterRule(_HORIZONTAL, 2, (52, 48), (130, 150)),
            ),
            hidden_attributes=(
                ("refresh_status_label", "widget"),
                ("refresh_progress", "widget"),
            ),
        ),
        "text_search": CompactPresentationSpec(
            "15-search-file-text.png",
            splitter_rules=(
                CompactSplitterRule(_HORIZONTAL, 0, (30, 32, 38), (210, 220, 250)),
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
        if max(margins.left(), margins.top(), margins.right(), margins.bottom()) > 8:
            layout.setContentsMargins(
                min(margins.left(), 6),
                min(margins.top(), 6),
                min(margins.right(), 6),
                min(margins.bottom(), 6),
            )
    if layout.spacing() > 6:
        layout.setSpacing(4)


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
    if key in {"archive_browser", "model_library", "new_item_studio"}:
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

    compact_labels = _COMPACT_BUTTON_LABELS.get(key, {})
    if not compact_labels:
        return
    app = QApplication.instance()
    localizer = app.property("_cdmw_ui_localizer") if app is not None else None
    translate = getattr(localizer, "translate", None)
    for button in widget.findChildren(QAbstractButton):
        source_text = str(button.property("_i18n_source_text") or button.text() or "")
        compact_source = compact_labels.get(source_text)
        if compact_source is None:
            continue
        original_text = str(button.text() or source_text)
        if not button.toolTip():
            button.setToolTip(original_text)
        if not button.accessibleName():
            button.setAccessibleName(original_text)
        rendered = translate(compact_source) if callable(translate) else compact_source
        button.setProperty("_i18n_source_text", compact_source)
        button.setProperty("_i18n_rendered_text", str(rendered))
        button.setText(str(rendered))


def _hide_redundant_text(widget: QWidget, spec: CompactPresentationSpec) -> None:
    if not spec.hidden_text_prefixes:
        return
    for label in widget.findChildren(QLabel):
        text = str(label.text() or "").strip()
        if any(text.startswith(prefix) for prefix in spec.hidden_text_prefixes):
            label.setVisible(False)


_REDUNDANT_SECTION_TITLES = frozenset({"Actions", "Controls", "Files", "Preview"})
_COMPACT_FLAT_SURFACE_TYPES = frozenset({"CollapsibleSection", "FlatSectionPanel"})
_COMPACT_FLAT_SURFACE_OBJECT_NAMES = frozenset(
    {
        "DdsFlowPanel",
        "DdsFlowRow",
        "EditorActionPane",
        "EditorCanvasPane",
        "EditorInspectorSidebar",
        "EditorLeftSidebar",
        "EditorSectionBody",
        "EditorToolButton",
        "EmptyStatePanel",
        "FlatSectionBody",
        "FlatSectionPanel",
        "GuidancePanel",
        "GuidanceRow",
        "SectionBody",
        "SectionToggle",
        "WorkflowProfilePanel",
    }
)
_COMPACT_STYLE_BEGIN = "/* CDMW_COMPACT_FLAT_STYLE_BEGIN */"
_COMPACT_STYLE_END = "/* CDMW_COMPACT_FLAT_STYLE_END */"


def _is_compact_flat_surface(candidate: QWidget) -> bool:
    if (
        candidate.objectName() == "GuidanceRow"
        and str(candidate.property("guidanceRole") or "") in {"warning", "override"}
    ):
        return False
    if isinstance(candidate, QGroupBox):
        return True
    if type(candidate).__name__ in _COMPACT_FLAT_SURFACE_TYPES:
        return True
    if candidate.objectName() in _COMPACT_FLAT_SURFACE_OBJECT_NAMES:
        return True
    return type(candidate) is QFrame and candidate.frameShape() not in {
        QFrame.Shape.HLine,
        QFrame.Shape.VLine,
    }


def _compact_flat_surfaces(widget: QWidget) -> tuple[QWidget, ...]:
    return tuple(
        candidate
        for candidate in (widget, *widget.findChildren(QWidget))
        if _is_compact_flat_surface(candidate)
    )


def compact_surface_contract(widget: QWidget) -> dict[str, object]:
    """Report whether every constructed decorative surface follows Compact's flat contract."""

    surfaces = _compact_flat_surfaces(widget)
    offenders: list[str] = []
    for index, surface in enumerate(surfaces):
        if bool(surface.property("compactFlatSurface")):
            continue
        offenders.append(surface.objectName() or f"{type(surface).__name__}-{index + 1}")
    return {
        "compact_surface_count": len(surfaces),
        "flat_compact_surface_count": len(surfaces) - len(offenders),
        "unflattened_compact_surface_count": len(offenders),
        "unflattened_compact_surfaces": offenders,
        "flat_style_contract": str(widget.property("compactStyleContract") or ""),
    }


def _install_compact_tool_stylesheet(window: object, widget: QWidget) -> None:
    settings = getattr(window, "settings", None)
    if settings is not None and callable(getattr(settings, "value", None)):
        theme_key = active_shell_theme_key(settings, COMPACT_SHELL_VARIANT)
    else:
        theme_key = str(getattr(window, "current_theme_key", "") or DEFAULT_COMPACT_SHELL_THEME)
    overlay = _compact_tool_shape_override_stylesheet(get_theme(theme_key)).strip()
    current = str(widget.styleSheet() or "")
    start = current.find(_COMPACT_STYLE_BEGIN)
    had_overlay = start >= 0
    if start >= 0:
        end = current.find(_COMPACT_STYLE_END, start + len(_COMPACT_STYLE_BEGIN))
        if end >= 0:
            current = current[:start] + current[end + len(_COMPACT_STYLE_END) :]
        else:
            current = current[:start]
    base = current.strip()
    widget.setProperty("compactStyleContract", "flat_square_v1")
    if not base and not had_overlay:
        return
    styled = "\n".join(
        part
        for part in (
            base,
            _COMPACT_STYLE_BEGIN,
            overlay,
            _COMPACT_STYLE_END,
        )
        if part
    )
    if styled != widget.styleSheet():
        widget.setStyleSheet(styled)


def _flatten_compact_sections(widget: QWidget) -> None:
    """Keep semantic headings while removing nested decorative panel chrome."""

    for surface in _compact_flat_surfaces(widget):
        newly_flattened = not bool(surface.property("compactFlatSurface"))
        if newly_flattened:
            surface.setProperty("compactFlatSurface", True)
        if type(surface) is QFrame and surface.frameShape() != QFrame.Shape.NoFrame:
            surface.setFrameShape(QFrame.Shape.NoFrame)
        if newly_flattened:
            surface.style().unpolish(surface)
            surface.style().polish(surface)
            surface.update()

    for panel in widget.findChildren(QWidget):
        if type(panel).__name__ != "FlatSectionPanel":
            continue
        panel.setProperty("compactSection", True)
        body = getattr(panel, "body_frame", None)
        if isinstance(body, QWidget):
            body.setProperty("compactSection", True)
        title_label = getattr(panel, "title_label", None)
        header = getattr(panel, "header_widget", None)
        title = str(title_label.text() if isinstance(title_label, QLabel) else "").strip()
        if title not in _REDUNDANT_SECTION_TITLES:
            continue
        panel.setProperty("compactStructural", True)
        if isinstance(body, QWidget):
            body.setProperty("compactStructural", True)
        if isinstance(header, QWidget):
            header.setVisible(False)
        layout = panel.layout()
        if layout is not None:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

    for group in widget.findChildren(QGroupBox):
        group.setProperty("compactSection", True)
        if group.title().strip() not in _REDUNDANT_SECTION_TITLES:
            continue
        group.setTitle("")
        group.setProperty("compactStructural", True)
        layout = group.layout()
        if layout is not None:
            layout.setContentsMargins(0, 0, 0, 0)
            if layout.spacing() > 4:
                layout.setSpacing(4)


def _apply_tool_specific_presentation(window: object, key: str, widget: QWidget) -> None:
    if key == "archive_browser":
        _build_archive_command_strip(window, widget)

    elif key == "item_icons":
        from cdmw.ui.item_icons.panels import apply_compact_item_icons_presentation

        apply_compact_item_icons_presentation(widget)

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

    elif key == "texture_editor":
        grid_checkbox = getattr(widget, "grid_checkbox", None)
        if isinstance(grid_checkbox, QAbstractButton):
            grid_checkbox.setMinimumWidth(grid_checkbox.sizeHint().width())

    elif key == "research":
        refresh_button = getattr(widget, "refresh_button", None)
        if isinstance(refresh_button, QAbstractButton):
            refresh_button.setMaximumWidth(160)
        references_button = getattr(widget, "archive_picker_use_reference_button", None)
        if isinstance(references_button, QAbstractButton):
            references_button.setMinimumWidth(references_button.sizeHint().width())

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
    strip.setProperty("compactStructural", True)
    layout = QHBoxLayout(strip)
    layout.setContentsMargins(4, 2, 4, 2)
    layout.setSpacing(4)
    scan, refresh, finder, search_edit, search_button, extension, extension_picker = controls
    extension_picker.setObjectName("CompactArchiveSelectButton")
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

    controls_group = getattr(window, "archive_controls_group", widget)
    filters_group = next(
        (
            group
            for group in controls_group.findChildren(QGroupBox)
            if group.title().strip() == "Filters"
        ),
        None,
    )
    actions_group = next(
        (
            group
            for group in controls_group.findChildren(QGroupBox)
            if group.title().strip() == "Actions"
        ),
        None,
    )

    actions_button = QToolButton(strip)
    actions_button.setObjectName("CompactArchiveActionsButton")
    actions_button.setText("Actions")
    actions_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    actions_menu = QMenu(actions_button)
    action_pairs: list[tuple[QAction, QAbstractButton]] = []
    for source in (
        getattr(window, "archive_extract_selected_button", None),
        getattr(window, "archive_extract_filtered_button", None),
        getattr(window, "archive_resolve_in_research_button", None),
    ):
        if not isinstance(source, QAbstractButton):
            continue
        action = actions_menu.addAction(source.text())
        action.setToolTip(source.toolTip())
        action.triggered.connect(lambda _checked=False, source=source: source.click())
        action_pairs.append((action, source))

    def sync_actions() -> None:
        for action, source in action_pairs:
            action.setText(source.text())
            action.setToolTip(source.toolTip())
            action.setEnabled(source.isEnabled())
            action.setVisible(not source.isHidden())

    actions_menu.aboutToShow.connect(sync_actions)
    sync_actions()
    actions_button.setMenu(actions_menu)
    actions_button.setEnabled(bool(action_pairs))
    layout.addWidget(actions_button)

    more_filters = QToolButton(strip)
    more_filters.setObjectName("CompactArchiveMoreFiltersButton")
    more_filters.setText("More Filters")
    more_filters.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    more_filters.setToolTip("Show or hide Archive Browser filters only.")
    if isinstance(filters_group, QGroupBox):
        filters_group.setTitle("")
        filters_group.setProperty("compactStructural", True)
        filter_menu = QMenu(more_filters)
        filter_menu.setObjectName("CompactArchiveFiltersMenu")
        filter_widget_action = QWidgetAction(filter_menu)
        filter_widget_action.setDefaultWidget(filters_group)
        filter_menu.addAction(filter_widget_action)
        more_filters.setMenu(filter_menu)
    else:
        more_filters.setEnabled(False)
    layout.addWidget(more_filters)
    for command_button in (extension_picker, actions_button, more_filters):
        command_button.setAutoRaise(False)
        command_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if isinstance(search_group, QGroupBox):
        search_group.setVisible(False)
    if isinstance(actions_group, QGroupBox):
        actions_group.setVisible(False)
    controls_scroll = getattr(window, "archive_controls_scroll", None)
    if isinstance(controls_scroll, QWidget):
        controls_scroll.setMinimumWidth(0)
        controls_scroll.setMaximumWidth(0)
        controls_scroll.setVisible(False)
    root_layout.insertWidget(0, strip)
    widget._cdmw_compact_archive_command_strip = strip  # type: ignore[attr-defined]
    widget._cdmw_compact_archive_actions_button = actions_button  # type: ignore[attr-defined]
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
            _flatten_compact_sections(widget)
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
    _flatten_compact_sections(widget)
    _install_compact_tool_stylesheet(window, widget)
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
    "compact_surface_contract",
]
