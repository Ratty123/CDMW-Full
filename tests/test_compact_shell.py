from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.settings_tab import SettingsTab
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.shell.app_startup import read_shell_startup_theme_key
from cdmw.ui.shell.compact.activity import (
    ActivityHistory,
    CompactStatusSnapshot,
    tool_log_adapter_for,
)
from cdmw.ui.shell.compact.config import (
    COMPACT_SHELL_THEME_SETTING,
    COMPACT_SHELL_VARIANT,
    DEFAULT_COMPACT_SHELL_THEME,
    LEGACY_SHELL_VARIANT,
    SHELL_VARIANT_SETTING,
    active_shell_theme_key,
    normalize_shell_variant,
    read_compact_shell_theme_key,
    read_shell_variant,
)
from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS
from cdmw.ui.shell.compact.snapshots import compact_status_snapshot_for
from cdmw.ui.shell.compact.workspace import (
    CompactWorkspace,
    append_compact_activity,
    sync_compact_workspace_selection,
)
from cdmw.ui.shell.lazy_tool_tab import LazyToolTab
from cdmw.ui.shell.theme_controller import ThemeControllerMixin
from cdmw.ui.themes import UI_THEME_SCHEMES


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _CompactOwner(QMainWindow):
    def __init__(self, settings) -> None:
        super().__init__()
        self.settings = settings
        self.requested_keys: list[str] = []
        menu_bar = self.menuBar()
        self.profile_menu = menu_bar.addMenu("Profile")
        self.export_profile_action = self.profile_menu.addAction("Export Profile...")
        self.import_profile_action = self.profile_menu.addAction("Import Profile...")
        self.window_menu = menu_bar.addMenu("Window")
        self.detach_current_tab_action = self.window_menu.addAction("Detach Current Tool")
        self.attach_current_tool_action = self.window_menu.addAction("Reattach Current Tool")
        self.attach_all_tools_action = self.window_menu.addAction("Reattach All Tools")
        self.help_menu = menu_bar.addMenu("Help")
        self.quick_start_menu_action = self.help_menu.addAction("Quick Start")
        self.open_documentation_action = self.help_menu.addAction("Documentation")
        self.export_diagnostics_action = self.help_menu.addAction("Export Diagnostics...")
        self.copy_problem_summary_action = self.help_menu.addAction("Copy Latest Problem Summary")
        self.open_crash_reports_action = self.help_menu.addAction("Open Crash Reports Folder")
        self.open_about_action = menu_bar.addAction("About")
        self.open_settings_action = menu_bar.addAction("Settings")
        self.mod_package_tool_action = menu_bar.addAction("Retrofit/Repackage Mods")
        self.support_corner_button = QPushButton("Support Me")
        self.archive_scan_progress_label = QLabel("Ready")
        self.archive_scan_progress_bar = QProgressBar()
        self.archive_cache_status_chip = QLabel("Cache: Unknown")
        self.archive_log_view = QPlainTextEdit()
        self.clear_archive_scan_log = self.archive_log_view.clear
        self._tool_widgets_by_key: dict[str, object] = {}

    def _activate_tool_key(self, key: str) -> None:
        self.requested_keys.append(key)


def test_shell_setting_normalization_and_theme_independence(tmp_path: Path) -> None:
    settings = create_settings(settings_file_path=tmp_path / "compact-settings.cfg")
    settings.setValue(SHELL_VARIANT_SETTING, "future-shell")
    settings.setValue("appearance/theme", "graphite")

    assert normalize_shell_variant(None) == LEGACY_SHELL_VARIANT
    assert read_shell_variant(settings) == LEGACY_SHELL_VARIANT
    assert read_compact_shell_theme_key(settings) == DEFAULT_COMPACT_SHELL_THEME
    assert active_shell_theme_key(settings) == "graphite"

    settings.setValue(SHELL_VARIANT_SETTING, COMPACT_SHELL_VARIANT)
    settings.setValue(COMPACT_SHELL_THEME_SETTING, "crimson_desert")
    assert active_shell_theme_key(settings) == "crimson_desert"
    assert read_shell_startup_theme_key(settings) == "crimson_desert"
    assert settings.value("appearance/theme") == "graphite"


def test_compact_registry_has_the_stable_fifteen_tool_contract() -> None:
    assert len(COMPACT_TOOL_SPECS) == 15
    assert len({spec.key for spec in COMPACT_TOOL_SPECS}) == 15
    assert [(spec.category, spec.label) for spec in COMPACT_TOOL_SPECS] == [
        ("Assets", "Browse Archives"),
        ("Assets", "Model Library"),
        ("Assets", "Item Icons"),
        ("Assets", "Create New Item"),
        ("Authoring", "Mesh Editor"),
        ("Authoring", "Placement & Animation"),
        ("Textures", "Upscale & Process Textures"),
        ("Textures", "Replace Textures"),
        ("Textures", "Recolor Variants"),
        ("Textures", "Texture Editor"),
        ("Utilities", "Repackage Mods"),
        ("Utilities", "Inspect File Formats"),
        ("Utilities", "Edit Translations"),
        ("Utilities", "Asset Research"),
        ("Utilities", "Search File Text"),
    ]


def test_compact_theme_payload_applies_only_the_independent_compact_theme() -> None:
    owner = type(
        "ThemeOwner",
        (),
        {"is_compact_shell": True, "current_theme_key": "crimson_desert"},
    )()
    classic_payload = ThemeControllerMixin._normalize_appearance_change_payload(
        owner,
        {
            "theme_key": "graphite",
            "changed": ("theme",),
            "requires_theme_apply": True,
        },
    )
    compact_payload = ThemeControllerMixin._normalize_appearance_change_payload(
        owner,
        {
            "theme_key": "graphite",
            "theme_target": COMPACT_SHELL_THEME_SETTING,
            "changed": ("theme",),
            "requires_theme_apply": True,
        },
    )

    assert classic_payload["changed"] == ()
    assert classic_payload["theme_key"] == "crimson_desert"
    assert not classic_payload["requires_theme_apply"]
    assert compact_payload["changed"] == ("theme",)
    assert compact_payload["theme_key"] == "graphite"
    assert compact_payload["requires_theme_apply"]


def test_activity_history_coalesces_and_caps_events() -> None:
    assert ActivityHistory().capacity == 2000
    history = ActivityHistory(capacity=3, coalesce_ms=250)
    started = datetime(2026, 8, 26, 12, 0, 0)
    history.append("Scanning", tool_key="archive_browser", timestamp=started)
    history.append(
        "Scanning",
        tool_key="archive_browser",
        timestamp=started + timedelta(milliseconds=240),
    )
    assert len(history.events) == 1
    history.append("One", timestamp=started + timedelta(seconds=1))
    history.append("Two", timestamp=started + timedelta(seconds=2))
    history.append("Three", timestamp=started + timedelta(seconds=3))
    assert [event.message for event in history.events] == ["One", "Two", "Three"]


def test_tool_log_adapter_reuses_the_existing_document() -> None:
    _app()
    owner = type("Owner", (), {})()
    owner.archive_log_view = QPlainTextEdit()
    owner.archive_log_view.setPlainText("Existing archive log")
    owner.clear_archive_scan_log = owner.archive_log_view.clear
    adapter = tool_log_adapter_for(owner, "archive_browser")

    assert adapter.document is owner.archive_log_view.document()
    assert adapter.copy() == "Existing archive log"
    assert _app().clipboard().text() == "Existing archive log"
    adapter.clear()
    assert owner.archive_log_view.toPlainText() == ""

    new_item_tab = QWidget()
    output_panel = QWidget(new_item_tab)
    output_panel.log = QPlainTextEdit(output_panel)  # type: ignore[attr-defined]
    output_panel.log.setPlainText("Existing New Item output")  # type: ignore[attr-defined]
    new_item_tab.output_panel = output_panel  # type: ignore[attr-defined]
    owner._tool_widgets_by_key = {"new_item_studio": new_item_tab}
    new_item_adapter = tool_log_adapter_for(owner, "new_item_studio")

    assert new_item_adapter.document is output_panel.log.document()  # type: ignore[attr-defined]
    assert new_item_adapter.text() == "Existing New Item output"
    new_item_adapter.clear()
    assert output_panel.log.toPlainText() == ""  # type: ignore[attr-defined]


def test_compact_status_snapshots_cover_all_tools_without_constructing_lazy_tabs() -> None:
    _app()
    owner = QWidget()
    owner._tool_widgets_by_key = {}
    constructed: list[str] = []
    containers: list[LazyToolTab] = []
    for spec in COMPACT_TOOL_SPECS:
        container = LazyToolTab(
            lambda key=spec.key: constructed.append(key) or QWidget()
        )
        container.setParent(owner)
        owner._tool_widgets_by_key[spec.key] = container
        containers.append(container)

    first = [compact_status_snapshot_for(owner, spec.key) for spec in COMPACT_TOOL_SPECS]
    second = [compact_status_snapshot_for(owner, spec.key) for spec in COMPACT_TOOL_SPECS]

    assert [snapshot.tool_key for snapshot in first] == [spec.key for spec in COMPACT_TOOL_SPECS]
    assert [snapshot.label for snapshot in first] == [spec.label for spec in COMPACT_TOOL_SPECS]
    assert first == second
    assert constructed == []
    assert all(container.widget_if_created() is None for container in containers)
    owner.deleteLater()
    _app().processEvents()


def test_compact_status_snapshots_render_representative_existing_facts() -> None:
    _app()
    owner = QWidget()
    owner._tool_widgets_by_key = {}

    owner.archive_entries = list(range(10))
    owner.archive_filtered_entries = list(range(4))
    owner.archive_tree = QTreeWidget(owner)
    owner.archive_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
    for index in range(4):
        item = QTreeWidgetItem([f"File {index}"])
        owner.archive_tree.addTopLevelItem(item)
        item.setSelected(index < 2)

    owner.total_files_value = QLabel("10", owner)
    owner.converted_value = QLabel("6", owner)
    owner.skipped_value = QLabel("1", owner)
    owner.failed_value = QLabel("1", owner)

    new_item = QWidget(owner)
    new_item._current_step = 3
    new_item.pages = QStackedWidget(new_item)
    for _index in range(7):
        new_item.pages.addWidget(QWidget())
    new_item.controller = SimpleNamespace(busy=True)
    new_item._pending_template = None
    new_item._pending_model_import = object()
    owner._tool_widgets_by_key["new_item_studio"] = new_item

    mesh_editor = QWidget(owner)
    mesh_editor.current_edit_mode = "edit"
    mesh_editor.current_selection_mode = "brush"
    mesh_editor.current_selection_empty = False
    owner._tool_widgets_by_key["mesh_editor"] = mesh_editor

    assert compact_status_snapshot_for(owner, "archive_browser").facts == (
        "2 selected",
        "4/10 files",
    )
    assert compact_status_snapshot_for(owner, "texture_workflow").facts == (
        "6 processed",
        "1 failed",
        "2 pending",
    )
    assert compact_status_snapshot_for(owner, "new_item_studio").facts == (
        "Step 4/7",
        "Working",
        "1 pending",
    )
    assert compact_status_snapshot_for(owner, "mesh_editor").facts == (
        "Edit mode",
        "Brush selection",
        "Selection active",
    )
    owner.deleteLater()
    _app().processEvents()


def test_compact_workspace_refreshes_bottom_status_and_retains_explicit_snapshot(
    tmp_path: Path,
) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "snapshot-settings.cfg")
    owner = _CompactOwner(settings)
    owner.archive_entries = list(range(5))
    owner.archive_filtered_entries = list(range(2))
    owner.archive_tree = QTreeWidget(owner)
    workspace = CompactWorkspace(owner, QTabWidget())
    owner.setCentralWidget(workspace)

    workspace.set_active_tool("archive_browser")
    assert workspace.status_strip.snapshot_label.text() == "Browse Archives  |  2/5 files"
    owner.archive_filtered_entries.append(2)
    workspace.append_activity("Filter updated", tool_key="archive_browser")
    assert workspace.status_strip.snapshot_label.text() == "Browse Archives  |  3/5 files"

    workspace.set_active_tool("format_explorer")
    workspace.append_activity("Format list refreshed", tool_key="format_explorer")
    assert workspace.status_strip.snapshot_label.text() == (
        "Inspect File Formats  |  Format list refreshed"
    )

    workspace.set_status_snapshot(
        CompactStatusSnapshot(
            tool_key="archive_browser",
            label="Browse Archives",
            facts=("Pinned selection",),
        )
    )
    owner.archive_filtered_entries.append(3)
    workspace.append_activity("Another filter update", tool_key="archive_browser")
    workspace.set_active_tool("archive_browser")
    assert workspace.status_strip.snapshot_label.text() == (
        "Browse Archives  |  Pinned selection"
    )

    owner.close()
    owner.deleteLater()
    app.processEvents()


def test_compact_activity_and_selection_helpers_are_classic_noops() -> None:
    owner = SimpleNamespace(compact_workspace=None)

    append_compact_activity(owner, "Classic status", tool_key="archive_browser")

    assert sync_compact_workspace_selection(owner, "archive_browser") == ""


def test_compact_workspace_executes_rail_footer_status_and_drawer_contracts(tmp_path: Path) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "rail-settings.cfg")
    owner = _CompactOwner(settings)
    main_tabs = QTabWidget()
    main_tabs.addTab(QLabel("Tool"), "Tool")
    workspace = CompactWorkspace(owner, main_tabs)
    owner.setCentralWidget(workspace)
    owner.resize(1120, 720)
    owner.show()
    app.processEvents()

    assert workspace.rail.width() == 236
    assert set(workspace.rail.tool_buttons) == {spec.key for spec in COMPACT_TOOL_SPECS}
    row = workspace.rail.tool_buttons["archive_browser"]
    QTest.mouseClick(row, Qt.LeftButton)
    assert owner.requested_keys == ["archive_browser"]
    assert row.isChecked()
    assert row.focusPolicy() == Qt.StrongFocus
    row.setFocus()
    QTest.keyClick(row, Qt.Key_Space)
    assert owner.requested_keys == ["archive_browser", "archive_browser"]
    for spec in COMPACT_TOOL_SPECS[1:]:
        QTest.mouseClick(workspace.rail.tool_buttons[spec.key], Qt.LeftButton)
    assert owner.requested_keys[2:] == [spec.key for spec in COMPACT_TOOL_SPECS[1:]]

    assets_header = workspace.rail.category_headers["Assets"]
    assets_header.setFocus()
    QTest.keyClick(assets_header, Qt.Key_Space)
    app.processEvents()
    assert not assets_header.isChecked()
    assert str(settings.value("ui/compact_rail/categories/assets/expanded")).lower() in {
        "false",
        "0",
    }
    reloaded_settings = create_settings(settings_file_path=tmp_path / "rail-settings.cfg")
    assert str(
        reloaded_settings.value("ui/compact_rail/categories/assets/expanded")
    ).lower() in {"false", "0"}
    assert all(
        state in workspace.rail.styleSheet()
        for state in (":hover", ":pressed", ":disabled", ":checked", ":focus")
    )
    disabled_tool = QLabel("Disabled")
    disabled_tool.setEnabled(False)
    owner._tool_widgets_by_key["archive_browser"] = disabled_tool
    workspace.refresh_tool_enabled_states()
    assert not row.isEnabled()
    disabled_tool.setEnabled(True)
    workspace.refresh_tool_enabled_states()
    assert row.isEnabled()

    assert workspace.rail.settings_button.defaultAction() is owner.open_settings_action
    assert workspace.rail.help_button.menu() is owner.help_menu
    assert workspace.rail.support_button is owner.support_corner_button
    assert owner.profile_menu.menuAction() in workspace.rail.overflow_menu.actions()
    assert owner.window_menu.menuAction() in workspace.rail.overflow_menu.actions()
    assert owner.mod_package_tool_action in workspace.rail.overflow_menu.actions()
    assert workspace.status_strip.ready_label is owner.archive_scan_progress_label
    assert workspace.status_strip.progress_bar is owner.archive_scan_progress_bar
    assert workspace.status_strip.cache_label is owner.archive_cache_status_chip
    assert workspace.status_strip.progress_bar.size().width() == 76
    assert workspace.status_strip.progress_bar.size().height() == 10
    assert workspace.drawer.isHidden()
    QTest.mouseClick(workspace.status_strip.activity_button, Qt.LeftButton)
    app.processEvents()
    assert workspace.drawer.isVisible()
    workspace.append_activity("Ready", tool_key="archive_browser")
    QTest.qWait(60)
    assert workspace.activity_history.events[-1].message == "Ready"
    assert "Ready" in workspace.drawer.activity_view.toPlainText()
    QTest.mouseClick(workspace.drawer.copy_button, Qt.LeftButton)
    assert "Ready" in app.clipboard().text()
    QTest.mouseClick(workspace.drawer.clear_button, Qt.LeftButton)
    assert workspace.activity_history.events == ()

    workspace.set_active_tool("archive_browser")
    assert workspace.drawer._tool_adapter.document is owner.archive_log_view.document()
    assert workspace.drawer.tool_log_empty_label.text() == "This tool's log is empty."
    owner.archive_log_view.setPlainText("Archive detail")
    workspace.drawer.tabs.setCurrentIndex(1)
    app.processEvents()
    QTest.mouseClick(workspace.drawer.copy_button, Qt.LeftButton)
    assert app.clipboard().text() == "Archive detail"
    QTest.mouseClick(workspace.drawer.clear_button, Qt.LeftButton)
    assert owner.archive_log_view.toPlainText() == ""

    owner.close()
    owner.deleteLater()
    app.processEvents()


def test_settings_layout_controls_are_exposed_and_persist_independently(tmp_path: Path) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "settings-tab.cfg")
    settings.setValue("appearance/theme", "graphite")
    settings.setValue(SHELL_VARIANT_SETTING, COMPACT_SHELL_VARIANT)
    tab = SettingsTab(
        settings=settings,
        theme_key="graphite",
    )
    emitted: list[dict[str, object]] = []
    tab.appearance_changed.connect(emitted.append)
    tab.application_layout_combo.setCurrentIndex(
        tab.application_layout_combo.findData(LEGACY_SHELL_VARIANT)
    )
    alternate_theme = next(key for key in UI_THEME_SCHEMES if key != "graphite")
    index = tab.compact_shell_theme_combo.findData(alternate_theme)
    tab.compact_shell_theme_combo.setCurrentIndex(index)
    app.processEvents()

    assert not tab.application_layout_group.isHidden()
    assert "Restart required" in tab.application_layout_restart_label.text()
    assert [payload["theme_key"] for payload in emitted] == [alternate_theme]
    assert emitted[0]["theme_target"] == COMPACT_SHELL_THEME_SETTING
    assert emitted[0]["changed"] == ("theme",)
    tab.flush_settings_save()
    assert settings.value(SHELL_VARIANT_SETTING) == LEGACY_SHELL_VARIANT
    assert settings.value(COMPACT_SHELL_THEME_SETTING) == alternate_theme
    assert settings.value("appearance/theme") == "graphite"
    tab.deleteLater()
    app.processEvents()


def test_real_main_window_compact_wrapper_preserves_tool_authority(tmp_path: Path) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "compact-main-window.cfg")
    settings.setValue(SHELL_VARIANT_SETTING, COMPACT_SHELL_VARIANT)
    settings.setValue(COMPACT_SHELL_THEME_SETTING, "crimson_desert")
    settings.setValue("appearance/theme", "graphite")
    context = AppContext(
        settings=settings,
        services=ServiceContainer.create_default(settings=settings),
        event_bus=AppEventBus(),
    )
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=context)
    try:
        assert window.is_compact_shell
        assert window.compact_workspace is not None
        assert window.menuBar().isHidden()
        assert all(
            tabs.tabBar().isHidden()
            for tabs in (window.main_tabs, window.assets_tabs, window.texture_tabs, window.tools_tabs)
        )
        assert set(window._tool_widgets_by_key) >= {spec.key for spec in COMPACT_TOOL_SPECS}
        assert "format_explorer" not in window._detachable_tool_order
        assert "translation_studio" not in window._detachable_tool_order
        assert window._tool_key_for_widget(window.format_explorer_tab) == "format_explorer"
        assert window._tool_key_for_widget(window.translation_studio_tab) == "translation_studio"
        assert window.compact_workspace.rail.tool_buttons["archive_browser"].isChecked()

        window._activate_tool_key("format_explorer")
        app.processEvents()
        assert window._tool_key_for_widget(window._current_navigation_widget()) == "format_explorer"
        assert window.compact_workspace.rail.tool_buttons["format_explorer"].isChecked()
        window._activate_tool_key("archive_browser")
        app.processEvents()
        assert window.compact_workspace.rail.tool_buttons["archive_browser"].isChecked()

        compact_theme = next(
            key
            for key in UI_THEME_SCHEMES
            if key not in {"crimson_desert", "graphite"}
        )
        window.settings_tab.compact_shell_theme_combo.setCurrentIndex(
            window.settings_tab.compact_shell_theme_combo.findData(compact_theme)
        )
        deadline = time.monotonic() + 4.0
        while window.current_theme_key != compact_theme and time.monotonic() < deadline:
            QTest.qWait(40)
        assert window.current_theme_key == compact_theme
        assert window.compact_workspace.status_strip.progress_bar.height() == 10
        assert settings.value(COMPACT_SHELL_THEME_SETTING) == compact_theme
        assert settings.value("appearance/theme") == "graphite"

        archive_widget = window.archive_browser_tab
        window._detach_tool_key("archive_browser")
        app.processEvents()
        assert window._tool_widgets_by_key["archive_browser"] is archive_widget
        assert window._detached_tool_windows["archive_browser"].windowTitle() == "Browse Archives"
        assert window.compact_workspace.rail.tool_buttons["archive_browser"].isChecked()
        window._attach_detached_tool("archive_browser")
        app.processEvents()
        assert window._tool_widgets_by_key["archive_browser"] is archive_widget
        assert window.assets_tabs.indexOf(archive_widget) >= 0
        assert window.compact_workspace.rail.tool_buttons["archive_browser"].isChecked()
        assert (
            window.compact_workspace.drawer._tool_adapter.document
            is window.archive_log_view.document()
        )
    finally:
        window._finalize_close()
        window.deleteLater()
        app.processEvents()
