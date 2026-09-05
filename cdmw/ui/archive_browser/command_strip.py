"""Archive Browser's native command bar and secondary menus."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractButton, QFrame, QGroupBox, QHBoxLayout, QMenu, QSizePolicy, QToolButton, QWidget, QWidgetAction

def build_archive_command_strip(archive, widget: QWidget) -> None:
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
    controls = [getattr(archive, name) for name in names]
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

    filters_group = archive.archive_filters_group
    actions_group = archive.archive_actions_group

    actions_button = QToolButton(strip)
    actions_button.setObjectName("CompactArchiveActionsButton")
    actions_button.setText("Actions")
    actions_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    actions_menu = QMenu(actions_button)
    action_pairs: list[tuple[QAction, QAbstractButton]] = []
    for source in (
        getattr(archive, "archive_extract_selected_button", None),
        getattr(archive, "archive_extract_filtered_button", None),
        getattr(archive, "archive_resolve_in_research_button", None),
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
    controls_scroll = getattr(archive, "archive_controls_scroll", None)
    if isinstance(controls_scroll, QWidget):
        controls_scroll.setMinimumWidth(0)
        controls_scroll.setMaximumWidth(0)
        controls_scroll.setVisible(False)
    root_layout.insertWidget(0, strip)
    widget._cdmw_compact_archive_command_strip = strip  # type: ignore[attr-defined]
    widget._cdmw_compact_archive_actions_button = actions_button  # type: ignore[attr-defined]
    widget._cdmw_compact_archive_more_filters_button = more_filters  # type: ignore[attr-defined]
