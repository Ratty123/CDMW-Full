"""Archive Browser's native command bar and secondary menus."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import QAbstractButton, QFrame, QGroupBox, QHBoxLayout, QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget


class _ArchiveFiltersPopup(QFrame):
    """Keep filter widgets in a popup without QMenu's widget-action handoff."""

    def __init__(self, filters: QGroupBox, button: QToolButton, name: str = "CompactArchiveFiltersMenu") -> None:
        super().__init__(button, Qt.WindowType.Popup)
        self.setObjectName(name)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(filters)
        self._button = button

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
            return
        self.adjustSize()
        position = self._button.mapToGlobal(QPoint(0, self._button.height()))
        screen = self._button.screen()
        if screen is not None:
            bounds = screen.availableGeometry()
            position.setX(max(bounds.left(), min(position.x(), bounds.right() - self.width() + 1)))
            position.setY(max(bounds.top(), min(position.y(), bounds.bottom() - self.height() + 1)))
        self.move(position)
        self.show()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self._button.setFocus(Qt.FocusReason.PopupFocusReason)
            event.accept()
        else:
            super().keyPressEvent(event)


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
    strip.setProperty("commandBar", True)
    layout = QHBoxLayout(strip)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(6)
    scan, refresh, finder, search_edit, search_button, extension, extension_picker = controls
    extension_picker.setObjectName("CompactArchiveSelectButton")
    character_finder = getattr(archive, "archive_character_finder_button", None)
    buttons = (scan, refresh, finder, character_finder) if isinstance(character_finder, QWidget) else (scan, refresh, finder)
    npc_finder = getattr(archive, "archive_npc_finder_button", None)
    if isinstance(npc_finder, QWidget):
        buttons = (*buttons, npc_finder)
    action_charts = getattr(archive, "archive_action_chart_button", None)
    if isinstance(action_charts, QWidget):
        buttons = (*buttons, action_charts)
    for button in buttons:
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(button)
    search_edit.setMinimumWidth(100)
    search_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    layout.addWidget(search_edit, stretch=1)
    layout.addWidget(search_button)
    extension.setMinimumWidth(78)
    extension.setMaximumWidth(160)
    layout.addWidget(extension)
    extension_picker.setMinimumWidth(0)
    extension_picker.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
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
        getattr(archive, "archive_export_paths_button", None),
        getattr(archive, "archive_resolve_in_research_button", None),
    ):
        if not isinstance(source, QAbstractButton):
            continue
        action = actions_menu.addAction(source.text())
        action.setToolTip(source.toolTip())
        action.triggered.connect(lambda _checked=False, source=source: source.click())
        action_pairs.append((action, source))

    # Compact Workspace hides the controls pane, so its panels open from here.
    panel_actions: dict[str, QAction] = {}
    edited_group = getattr(archive, "archive_edited_results_group", None)
    dmm_group = getattr(archive, "archive_dmm_added_files_group", None)
    if isinstance(edited_group, QGroupBox) or isinstance(dmm_group, QGroupBox):
        actions_menu.addSeparator()

    def add_panel(group: QGroupBox, action: QAction, key: str, popup_name: str) -> None:
        group.setMinimumWidth(360)
        popup = _ArchiveFiltersPopup(group, actions_button, popup_name)
        action.setToolTip(group.toolTip() or group.title())
        action.triggered.connect(lambda _checked=False: (group.show(), popup.toggle()))
        panel_actions[key] = action

    if isinstance(edited_group, QGroupBox):
        add_panel(edited_group, actions_menu.addAction("Edited Results..."), "edited_results",
                  "CompactArchiveEditedResultsPanel")
    if isinstance(dmm_group, QGroupBox):
        add_panel(dmm_group, actions_menu.addAction("Files DMM Adds (Experimental)..."), "dmm_added_files",
                  "CompactArchiveDmmAddedFilesPanel")

    def sync_actions() -> None:
        for action, source in action_pairs:
            action.setText(source.text())
            action.setToolTip(source.toolTip())
            action.setEnabled(source.isEnabled())
            action.setVisible(not source.isHidden())
        edited = getattr(archive, "archive_edited_results_list", None)
        if "edited_results" in panel_actions and edited is not None:
            panel_actions["edited_results"].setEnabled(edited.count() > 0)

    actions_menu.aboutToShow.connect(sync_actions)
    sync_actions()
    actions_button.setMenu(actions_menu)
    actions_button.setEnabled(bool(action_pairs or panel_actions))
    layout.addWidget(actions_button)

    more_filters = QToolButton(strip)
    more_filters.setObjectName("CompactArchiveMoreFiltersButton")
    more_filters.setText("More Filters")
    more_filters.setToolTip("Show or hide Archive Browser filters only.")
    if isinstance(filters_group, QGroupBox):
        filters_group.setTitle("")
        filters_group.setProperty("compactStructural", True)
        filter_popup = _ArchiveFiltersPopup(filters_group, more_filters)
        more_filters.clicked.connect(filter_popup.toggle)
    else:
        more_filters.setEnabled(False)
    layout.addWidget(more_filters)
    for command_button in (extension_picker, actions_button, more_filters):
        command_button.setAutoRaise(False)
        command_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        command_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
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
    widget._cdmw_compact_archive_panel_actions = panel_actions  # type: ignore[attr-defined]
    widget._cdmw_compact_archive_more_filters_button = more_filters  # type: ignore[attr-defined]
