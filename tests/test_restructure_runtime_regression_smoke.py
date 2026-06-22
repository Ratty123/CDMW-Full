from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

from PySide6.QtWidgets import QApplication, QPushButton

from cdmw.app.events import AppEventBus
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
        _app()
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window._finalize_close()
        self.window.deleteLater()
        _app().processEvents()

    def test_shell_exposes_and_activates_all_primary_tools(self) -> None:
        visible_main_tabs = [
            self.window.main_tabs.tabText(index)
            for index in range(self.window.main_tabs.count())
            if self.window.main_tabs.isTabVisible(index)
        ]
        self.assertEqual(["Assets", "Textures", "Research", "Tools"], visible_main_tabs)
        self.assertFalse(self.window.main_tabs.isTabVisible(self.window.main_tabs.indexOf(self.window.settings_tab)))

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
            "settings",
        }
        self.assertTrue(expected_tools.issubset(self.window._tool_widgets_by_key))

        for key in sorted(expected_tools):
            widget = self.window._tool_widgets_by_key[key]
            self.window._activate_tool_widget(widget)
            self.assertIs(self.window._current_navigation_widget(), widget, key)

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
        button_labels = {
            button.text()
            for button in self.window.mod_package_retrofit_tab.findChildren(QPushButton)
        }
        self.assertIn("Scan", button_labels)
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
                on_complete(task(lambda _message: None))

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
