from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from cdmw.app.events import AppEventBus
from cdmw.domain.archives.backend_mode import ArchiveBackendMode, ArchiveBackendSelection
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
        settings.setValue("ui/shell_variant", "classic")
        context = AppContext(
            settings=settings,
            services=ServiceContainer.create_default(settings=settings),
            event_bus=AppEventBus(),
        )
        self.window = MainWindow(app_context=context)

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
        visible_main_tabs = [
            self.window.main_tabs.tabText(index)
            for index in range(self.window.main_tabs.count())
            if self.window.main_tabs.isTabVisible(index)
        ]
        # Mesh Editor and Placement are direct workspaces rather than members of a group.
        # Doubled ampersands are how a Qt tab bar stores literal ampersands.
        self.assertEqual(
            [
                "Assets",
                "Mesh Editor",
                "Placement && Animations",
                "Texture Upscaling && Editing",
                "Tools",
            ],
            visible_main_tabs,
        )
        self.assertEqual(1, self.window.main_tabs.indexOf(self.window.mesh_editor_tab))
        self.assertEqual(2, self.window.main_tabs.indexOf(self.window.placement_studio_tab))
        self.assertEqual(-1, self.window.assets_tabs.indexOf(self.window.mesh_editor_tab))
        self.assertEqual(
            ["Archive Browser", "Model Library", "Icon Creator", "Create New Item"],
            [
                self.window.assets_tabs.tabText(index)
                for index in range(self.window.assets_tabs.count())
            ],
        )
        self.assertEqual(
            ["Texture Workflow", "Texture Replacer", "Texture Recolor", "Texture Editor"],
            [
                self.window.texture_tabs.tabText(index)
                for index in range(self.window.texture_tabs.count())
            ],
        )
        self.assertEqual(
            ["Retrofit/Repackage", "Format Explorer", "Translations", "Research", "Text Search"],
            [
                self.window.tools_tabs.tabText(index)
                for index in range(self.window.tools_tabs.count())
            ],
        )
        self.assertFalse(hasattr(self.window, "research_tabs"))
        self.assertFalse(self.window.main_tabs.isTabVisible(self.window.main_tabs.indexOf(self.window.settings_tab)))
        window_actions = [
            action.text().replace("&", "")
            for action in self.window.window_menu.actions()
            if not action.isSeparator()
        ]
        self.assertEqual(
            ["Detach Current Tool", "Reattach Current Tool", "Reattach All Tools"],
            window_actions[:3],
        )

        expected_tools = {
            "texture_workflow",
            "replace_assistant",
            "recolor_variants",
            "texture_editor",
            "archive_browser",
            "mesh_editor",
            "model_library",
            "item_icons",
            "research",
            "text_search",
            "mod_package_retrofit",
            "placement_studio",
            "new_item_studio",
            "settings",
        }
        self.assertTrue(expected_tools.issubset(self.window._tool_widgets_by_key))
        self.window._handle_language_changed("de")
        self.assertEqual("de", self.window.ui_localizer.language_code)
        self.assertEqual(
            self.window.ui_localizer.translate("Assets"),
            self.window.main_tabs.tabText(
                self.window.main_tabs.indexOf(self.window.assets_tabs)
            ),
        )
        for widget, source in (
            (self.window.mesh_editor_tab, "Mesh Editor"),
            (self.window.placement_studio_tab, "Placement & Animations"),
            (self.window.texture_tabs, "Texture Upscaling & Editing"),
            (self.window.tools_tabs, "Tools"),
        ):
            self.assertEqual(
                self.window.ui_localizer.translate_mnemonic(source.replace("&", "&&")),
                self.window.main_tabs.tabText(self.window.main_tabs.indexOf(widget)),
                source,
            )
        # The Settings page is closed, so it is deliberately left at the old
        # revision and translated when it is opened; asserting its text here
        # would require walking every hidden page on every language change.
        # tests/test_localization_catalog_contracts.py covers the reveal.
        self.assertEqual(
            "Export Language File...",
            self.window.settings_tab.export_language_button.text(),
        )

        for key in sorted(expected_tools):
            widget = self.window._tool_widgets_by_key[key]
            self.window._activate_tool_widget(widget)
            self.assertIs(self.window._current_navigation_widget(), widget, key)
            self.assertIsNotNone(self._wait_for_created_tool(widget), key)

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
                self.assertIs(window.main_tabs.currentWidget(), window.assets_tabs)
                self.assertIs(window.assets_tabs.currentWidget(), window.archive_browser_tab)
                self.assertEqual("archive_browser", settings.value("ui/active_tool_key"))
            finally:
                window._finalize_close()
                window.deleteLater()
                _app().processEvents()

    def test_startup_archive_autoload_reaches_scan_after_root_preflight(self) -> None:
        class ScanReached(RuntimeError):
            pass

        def stop_before_worker(*_args: object, **_kwargs: object) -> None:
            raise ScanReached

        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            inspected_roots: list[Path] = []
            self.window.archive_package_root_edit.setText(str(package_root))
            self.window.show_quick_start_on_launch = False
            self.window._previous_session_unclean = False
            self.window.worker_thread = None
            self.window.archive_entries = []
            self.window.archive_remote_bridge = None
            self.window._check_archive_cache_health = lambda _root: {}  # type: ignore[method-assign]
            self.window._warn_if_archive_cache_stale = lambda *_args: None  # type: ignore[method-assign]
            self.window._set_archive_cache_health = stop_before_worker  # type: ignore[method-assign]

            with patch(
                "cdmw.ui.archive_browser.scan_lifecycle.find_suspicious_archive_tree_roots",
                side_effect=lambda root: inspected_roots.append(root) or (),
            ), self.assertRaises(ScanReached):
                self.window._maybe_autoload_archive_on_startup()

        self.assertEqual([package_root], inspected_roots)

    def test_retrofit_repackage_action_opens_tab_not_modal_dialog(self) -> None:
        with patch.object(self.window, "_show_mod_package_retrofit_dialog") as open_dialog:
            self.window.mod_package_tool_action.trigger()

        menu_titles = {action.text().replace("&", "") for action in self.window.menuBar().actions()}
        self.assertNotIn("Tools", menu_titles)
        self.assertIs(self.window.main_tabs.currentWidget(), self.window.tools_tabs)
        self.assertIs(self.window.tools_tabs.currentWidget(), self.window.mod_package_retrofit_tab)
        self.assertEqual("Retrofit/Repackage Mods", self.window.mod_package_tool_action.text())
        self.assertEqual(
            "Retrofit/Repackage",
            self.window.tools_tabs.tabText(self.window.tools_tabs.indexOf(self.window.mod_package_retrofit_tab)),
        )
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
            if self.window.archive_remote_bridge is not None:
                self.window.archive_remote_bridge.deactivate()
            self.window.archive_remote_bridge = None
            self.window.archive_backend_selection = ArchiveBackendSelection(
                ArchiveBackendMode.LEGACY,
                "test_session_legacy",
                True,
            )
            self.window.archive_backend_mode = ArchiveBackendMode.LEGACY
            self.window.archive_tree.use_legacy_model()
            self.window.archive_filtered_entries = [entry]
            self.window.archive_tree.set_archive_state([entry], mode="flat")
            item = self.window.archive_tree.find_item_for_entry(0)
            self.assertIsNotNone(item)
            self.window.archive_tree.setCurrentItem(item)
            self.window.archive_preview_showing_loose = False
            self.window.worker_thread = None
            self.window._update_archive_model_action_controls(None)
            self.assertTrue(self.window.archive_hkx_edit_button.isEnabled())

            opened: list[tuple[ArchiveEntry, str]] = []

            def run_utility_task(*, task, on_complete, **_kwargs):
                on_complete(task(lambda _message: None, threading.Event()))

            self.window._run_utility_task = run_utility_task  # type: ignore[method-assign]
            self.window.archive_entries_by_normalized_path = {}
            self.window.archive_entries_by_basename = {}
            self.window._open_archive_hkx_editor_dialog = (  # type: ignore[method-assign]
                lambda current_entry, document_text, **_kwargs: opened.append((current_entry, document_text))
            )

            with patch(
                "cdmw.ui.archive_browser.hkx_document_actions.ensure_archive_preview_source",
                return_value=(payload_path, ""),
            ), patch(
                "cdmw.ui.archive_browser.hkx_document_actions.build_hkx_editable_geometry_xml",
                return_value="<hkx/>",
            ):
                self.window.archive_hkx_edit_button.click()

        self.assertEqual([(entry, "<hkx/>")], opened)


if __name__ == "__main__":
    unittest.main()
