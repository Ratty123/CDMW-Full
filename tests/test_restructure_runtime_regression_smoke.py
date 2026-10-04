from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from cdmw.app.events import AppEventBus
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import configure_synthetic_archive_context
from cdmw.models import ArchiveEntry
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _entry(path: str, root: Path) -> ArchiveEntry:
    pamt_path = root / "0009" / "0009.pamt"
    paz_path = root / "0009" / "0.paz"
    pamt_path.parent.mkdir(parents=True, exist_ok=True)
    return ArchiveEntry(
        path=path,
        pamt_path=pamt_path,
        paz_file=paz_path,
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class RestructureRuntimeRegressionSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Scoped to this case rather than set at import. As a module-level
        # `os.environ.setdefault` it stayed set for the rest of the pytest process, and
        # `_startup_archive_path_prompt_needed` returns False whenever it is "1" -- so
        # the first-run prompt tests silently stopped exercising the prompt whenever
        # this file was collected before them.
        self._smoke_env = patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"})
        self._smoke_env.start()
        self.addCleanup(self._smoke_env.stop)
        _app()
        self._temp_dir = tempfile.TemporaryDirectory()
        settings = create_settings(settings_file_path=Path(self._temp_dir.name) / "cdmw-test.cfg")
        settings.setValue("ui/shell_variant", "legacy")
        context = AppContext(
            settings=settings,
            services=ServiceContainer.create_default(settings=settings),
            event_bus=AppEventBus(),
        )
        self.window = MainWindow(app_context=context)
        # Navigation starts lazy tools only when the selected tab is visible.
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.window.show()
        _app().processEvents()

    def tearDown(self) -> None:
        self.window._finalize_close()
        self.window.deleteLater()
        _app().processEvents()
        self._temp_dir.cleanup()

    def _wait_for_created_tool(self, widget: QWidget) -> QWidget:
        created_widget = getattr(widget, "widget_if_created", None)
        if not callable(created_widget):
            return widget
        deadline = time.monotonic() + 10.0
        while created_widget() is None and time.monotonic() < deadline:
            _app().processEvents()
            time.sleep(0.001)
        created = created_widget()
        self.assertIsNotNone(created)
        return created

    def test_shell_exposes_and_activates_all_primary_tools(self) -> None:
        navigation = self.window.classic_navigation
        self.assertIsNotNone(navigation)
        self.assertEqual(
            ["Assets", "Authoring", "Utilities"],
            [navigation.groups.tabText(i) for i in range(navigation.groups.count())],
        )
        expected_tools = {
            "archive_browser", "model_library", "item_icons", "new_item_studio",
            "mesh_editor", "placement_studio", "textures", "mod_management", "mod_package_retrofit",
            "format_explorer", "translation_studio", "research", "text_search", "settings",
        }
        self.assertEqual(expected_tools, set(self.window.tab_registry.widgets))
        self.assertEqual(len(expected_tools), self.window.tool_stack.count())
        window_actions = [
            action.text().replace("&", "")
            for action in self.window.window_menu.actions()
            if not action.isSeparator()
        ]
        self.assertEqual(
            ["Detach Current Tool", "Reattach Current Tool", "Reattach All Tools"],
            window_actions[:3],
        )
        self.window._handle_language_changed("de")
        self.assertEqual("de", self.window.ui_localizer.language_code)
        self.assertEqual(
            self.window.ui_localizer.translate("Assets"), navigation.groups.tabText(0)
        )
        for key in sorted(expected_tools):
            widget = self.window.tab_registry.widgets[key]
            self.window._activate_tool_key(key)
            self.assertIs(self.window._current_navigation_widget(), widget, key)
            self.assertIsNotNone(self._wait_for_created_tool(widget), key)
            if key != "settings":
                index = navigation.tools.currentIndex()
                self.assertEqual(key, navigation.tools.tabData(index))
                self.assertEqual(
                    self.window.ui_localizer.translate(self.window.tab_registry.titles[key]),
                    navigation.tools.tabText(index),
                )

    def test_new_user_opens_archive_browser_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = create_settings(settings_file_path=Path(temp_dir) / "cdmw-test.cfg")
            context = AppContext(
                settings=settings,
                services=ServiceContainer.create_default(settings=settings),
                event_bus=AppEventBus(),
            )
            window = MainWindow(app_context=context)
            try:
                self.assertIs(window.tool_stack.currentWidget(), window.archive_browser_tab)
                self.assertEqual("archive_browser", window._tool_key_for_widget(window._current_navigation_widget()))
            finally:
                window._finalize_close()
                window.deleteLater()
                _app().processEvents()
            self.assertEqual("archive_browser", settings.value("ui/active_tool_key"))

    def test_startup_archive_autoload_reaches_standalone_backend_after_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            self.window.archive.archive_package_root_edit.setText(str(package_root))
            self.window.show_first_run_guide_on_launch = False
            self.window._previous_session_unclean = False
            self.window._startup_archive_autoload_dispatched = False
            self.window.worker_thread = None
            self.window.archive.archive_entries = []
            bridge = self.window.archive.archive_remote_bridge
            self.assertIsNotNone(bridge)

            with patch(
                "cdmw.ui.archive_browser.scan_lifecycle.QThreadPool",
            ) as pool, patch.object(bridge, "open_archive") as open_archive:
                self.window._maybe_autoload_archive_on_startup()
                start_task = pool.globalInstance.return_value.start
                start_task.assert_not_called()
                deadline = time.monotonic() + 5.0
                while not start_task.called and time.monotonic() < deadline:
                    _app().processEvents()
                    time.sleep(0.001)
                start_task.assert_called_once()
                task = start_task.call_args.args[0]
                self.assertEqual(package_root, task.root)
                self.assertIs(task, self.window.archive.archive_game_fingerprint_task)
                open_archive.assert_not_called()

                task.signals.completed.emit(task.generation, ({}, (), False))
                _app().processEvents()
                open_archive.assert_called_once_with(package_root, force_refresh=False, activate_tab=False)
                self.assertIsNone(self.window.archive.archive_game_fingerprint_task)

    def test_retrofit_repackage_action_opens_tab_not_modal_dialog(self) -> None:
        with patch("cdmw.ui.tools.mod_package_retrofit.ArchiveModPackageRetrofitDialogMixin._show_mod_package_retrofit_dialog") as open_dialog:
            self.window.mod_package_tool_action.trigger()

        menu_titles = {action.text().replace("&", "") for action in self.window.menuBar().actions()}
        self.assertNotIn("Tools", menu_titles)
        self.assertIs(self.window.tool_stack.currentWidget(), self.window.mod_package_retrofit_tab)
        self.assertEqual("Retrofit/Repackage Mods", self.window.mod_package_tool_action.text())
        self.assertEqual("Repackage Mods", self.window.tab_registry.titles["mod_package_retrofit"])
        retrofit_tool = self._wait_for_created_tool(self.window.mod_package_retrofit_tab)
        button_labels = {
            button.text()
            for button in retrofit_tool.findChildren(QPushButton)
        }
        self.assertIn("Scan", button_labels)
        self.assertIn("Preview Package Plan", button_labels)
        self.assertNotIn("Refresh Game Index", button_labels)
        label_text = " ".join(
            label.text()
            for label in self.window.mod_package_retrofit_tab.findChildren(QLabel)
        )
        self.assertIn("Scan loose or zipped mod packages", label_text)
        self.assertNotIn("Game build", label_text)
        self.assertNotIn("current game", label_text)
        self.assertFalse(
            any(label.startswith("Open ") and "Repackage Tool" in label for label in button_labels)
        )
        open_dialog.assert_not_called()

    def test_archive_hkx_edit_button_opens_editor_for_current_hkx_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload_path = root / "sample.hkx"
            payload_path.write_bytes(b"HKX")
            entry = _entry("character/bin__/meshphysics/sample.hkx", root)
            configure_synthetic_archive_context(self.window, entry)
            self.window.archive.archive_preview_showing_loose = False
            self.window.worker_thread = None
            self.window.archive._update_archive_model_action_controls(None)
            self.assertTrue(self.window.archive.archive_hkx_edit_button.isEnabled())

            opened: list[tuple[ArchiveEntry, str]] = []

            def run_utility_task(*, task, on_complete, **_kwargs):
                on_complete(task(lambda _message: None, threading.Event()))

            self.window._run_utility_task = run_utility_task  # type: ignore[method-assign]
            self.window.archive.archive_entries_by_normalized_path = {}
            self.window.archive.archive_entries_by_basename = {}
            self.window.archive._open_archive_hkx_editor_dialog = (  # type: ignore[method-assign]
                lambda current_entry, document_text, **_kwargs: opened.append((current_entry, document_text))
            )

            with patch(
                "cdmw.ui.archive_browser.hkx_document_actions.ensure_archive_preview_source",
                return_value=(payload_path, ""),
            ), patch(
                "cdmw.ui.archive_browser.hkx_document_actions.build_hkx_editable_geometry_xml",
                return_value="<hkx/>",
            ):
                self.window.archive.archive_hkx_edit_button.click()

        self.assertEqual([(entry, "<hkx/>")], opened)


if __name__ == "__main__":
    unittest.main()
