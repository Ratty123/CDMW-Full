from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab
from cdmw.ui.shell.settings_autosave import SettingsAutosaveMixin


class _ProbeTool(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_requests = 0
        self.shutdown_calls = 0
        self.flush_calls = 0

    def ping(self) -> str:
        return "pong"

    def request_shutdown(self) -> None:
        self.shutdown_requests += 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def flush_settings_save(self) -> None:
        self.flush_calls += 1


class LazyToolTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_constructs_once_on_first_selection_and_forwards_explicit_use(self) -> None:
        builds: list[_ProbeTool] = []

        def build() -> _ProbeTool:
            tool = _ProbeTool()
            builds.append(tool)
            return tool

        tabs = QTabWidget()
        tabs.addTab(QWidget(), "Eager")
        lazy = LazyToolTab(build)
        tabs.addTab(lazy, "Lazy")
        tabs.show()
        self.app.processEvents()

        self.assertEqual([], builds)
        tabs.setCurrentWidget(lazy)
        self.app.processEvents()
        self.assertEqual(1, len(builds))
        self.assertEqual("pong", lazy.ping())
        tabs.setCurrentIndex(0)
        tabs.setCurrentWidget(lazy)
        self.app.processEvents()
        self.assertEqual(1, len(builds))

        lazy.request_shutdown()
        lazy.request_shutdown()
        lazy.shutdown()
        lazy.shutdown()
        lazy.flush_settings_save()
        self.assertEqual(1, builds[0].shutdown_requests)
        self.assertEqual(1, builds[0].shutdown_calls)
        self.assertEqual(1, builds[0].flush_calls)
        tabs.close()
        self.app.processEvents()

    def test_unopened_lifecycle_does_not_construct_tool(self) -> None:
        builds: list[_ProbeTool] = []
        lazy = LazyToolTab(lambda: builds.append(_ProbeTool()) or builds[-1])

        self.assertEqual((), tuple(lazy.iter_shutdown_workers()))
        lazy.request_shutdown()
        lazy.shutdown()
        lazy.flush_settings_save()

        self.assertEqual([], builds)
        self.assertIsNone(lazy.widget_if_created())

    def test_tool_selection_debounces_settings_write(self) -> None:
        activated: list[object] = []
        scheduled: list[bool] = []
        widget = object()
        window = SimpleNamespace(
            _current_navigation_widget=lambda: widget,
            _handle_tool_activated=activated.append,
            _update_window_menu_state=lambda: None,
            schedule_settings_save=lambda: scheduled.append(True),
            _save_settings=lambda: (_ for _ in ()).throw(AssertionError("synchronous settings write")),
        )

        SettingsAutosaveMixin._handle_main_tab_changed(window, 1)  # type: ignore[arg-type]
        SettingsAutosaveMixin._handle_tool_group_tab_changed(window, 1)  # type: ignore[arg-type]

        self.assertEqual([widget, widget], activated)
        self.assertEqual([True, True], scheduled)

    def test_main_window_first_show_keeps_unused_heavy_modules_unloaded(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.ini"
            script = "\n".join(
                (
                    "import os, sys",
                    "from pathlib import Path",
                    "os.environ['QT_QPA_PLATFORM'] = 'offscreen'",
                    "os.environ['CDMW_MAIN_WINDOW_CLASS_ONLY'] = '1'",
                    "from PySide6.QtWidgets import QApplication",
                    "import cdmw.ui.shell.app_window as app_window",
                    "from cdmw.app.events import AppEventBus",
                    "from cdmw.services.service_container import ServiceContainer",
                    "from cdmw.services.settings_service import create_settings",
                    "from cdmw.ui.shell.app_context import AppContext",
                    f"settings_path = Path({str(settings_path)!r})",
                    "app_window.resolve_settings_file_path = lambda: settings_path",
                    "app = QApplication.instance() or QApplication([])",
                    "MainWindow = app_window.run_gui()",
                    "settings = create_settings(settings_file_path=settings_path)",
                    "context = AppContext(settings, ServiceContainer.create_default(settings=settings), AppEventBus())",
                    "window = MainWindow(app_context=context)",
                    "window.show(); app.processEvents()",
                    "targets = (",
                    "    'cdmw.ui.mesh_editor.tab', 'cdmw.ui.model_library.tab',",
                    "    'cdmw.ui.text_search.tab', 'cdmw.ui.research.tab',",
                    "    'cdmw.ui.replace_assistant_tab', 'cdmw.ui.recolor_variants_tab',",
                    "    'cdmw.ui.texture_editor_tab', 'cdmw.ui.item_icons.tab',",
                    ")",
                    "assert not any(name in sys.modules for name in targets)",
                    "window.hide(); window._finalize_close()",
                    "assert not any(name in sys.modules for name in targets)",
                    "sys.stdout.flush(); sys.stderr.flush(); os._exit(0)",
                )
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=repo_root,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )

        self.assertEqual(
            0,
            result.returncode,
            f"Lazy first-window integration failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )

    def test_main_window_keeps_heavy_tabs_unloaded_until_explicit_use(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.ini"
            script = "\n".join(
                (
                    "import os, sys",
                    "from pathlib import Path",
                    "os.environ['QT_QPA_PLATFORM'] = 'offscreen'",
                    "os.environ['CDMW_MAIN_WINDOW_CLASS_ONLY'] = '1'",
                    "from PySide6.QtWidgets import QApplication",
                    "import cdmw.ui.shell.app_window as app_window",
                    "from cdmw.app.events import AppEventBus",
                    "from cdmw.services.service_container import ServiceContainer",
                    "from cdmw.services.settings_service import create_settings",
                    "from cdmw.ui.shell.app_context import AppContext",
                    f"app_window.resolve_settings_file_path = lambda: Path({str(settings_path)!r})",
                    "app = QApplication.instance() or QApplication([])",
                    "MainWindow = app_window.run_gui()",
                    f"settings = create_settings(settings_file_path=Path({str(settings_path)!r}))",
                    "context = AppContext(settings, ServiceContainer.create_default(settings=settings), AppEventBus())",
                    "window = MainWindow(app_context=context)",
                    "targets = (",
                    "    'cdmw.ui.mesh_editor.tab',",
                    "    'cdmw.ui.model_library.tab',",
                    "    'cdmw.ui.text_search.tab',",
                    "    'cdmw.ui.research.tab',",
                    "    'cdmw.ui.replace_assistant_tab',",
                    "    'cdmw.ui.recolor_variants_tab',",
                    "    'cdmw.ui.texture_editor_tab',",
                    "    'cdmw.ui.item_icons.tab',",
                    ")",
                    "assert not any(name in sys.modules for name in targets)",
                    "lazy_names = (",
                    "    'mesh_editor_tab', 'model_library_tab', 'text_search_tab',",
                    "    'research_tab', 'replace_assistant_tab', 'recolor_variants_tab',",
                    "    'texture_editor_tab', 'item_icons_tab', 'mod_package_retrofit_tab',",
                    ")",
                    "assert all(getattr(window, name).widget_if_created() is None for name in lazy_names)",
                    "first = window.recolor_variants_tab.ensure_widget()",
                    "assert first is window.recolor_variants_tab.ensure_widget()",
                    "assert 'cdmw.ui.recolor_variants_tab' in sys.modules",
                    "window._finalize_close()",
                    "assert not any(name in sys.modules for name in targets if name != 'cdmw.ui.recolor_variants_tab')",
                    "sys.stdout.flush(); sys.stderr.flush(); os._exit(0)",
                )
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=repo_root,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )

        self.assertEqual(
            0,
            result.returncode,
            f"Lazy main-window integration failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
