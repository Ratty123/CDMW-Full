from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication, QProgressBar, QTabWidget, QWidget

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

    def _process_until(self, predicate, *, timeout: float = 3.0) -> bool:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.001)
        self.app.processEvents()
        return bool(predicate())

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
        self.assertTrue(lazy.findChild(QProgressBar, "LazyToolLoadingProgress").isVisible())
        self.assertTrue(self._process_until(lambda: lazy.widget_if_created() is not None))
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

    def test_first_selection_preloads_off_thread_and_keeps_the_ui_heartbeat_live(self) -> None:
        prepared_on: list[QThread] = []
        ui_prepared_on: list[QThread] = []
        built_on: list[QThread] = []

        def prepare() -> None:
            prepared_on.append(QThread.currentThread())
            time.sleep(0.25)

        def build() -> _ProbeTool:
            built_on.append(QThread.currentThread())
            return _ProbeTool()

        def prepare_ui() -> None:
            ui_prepared_on.append(QThread.currentThread())

        tabs = QTabWidget()
        tabs.addTab(QWidget(), "Eager")
        lazy = LazyToolTab(build, prepare=prepare, prepare_ui=prepare_ui)
        tabs.addTab(lazy, "Lazy")
        heartbeats: list[float] = []
        timer = QTimer(tabs)
        timer.setInterval(10)
        timer.timeout.connect(lambda: heartbeats.append(time.perf_counter()))
        tabs.show()
        self.app.processEvents()
        timer.start()

        started = time.perf_counter()
        tabs.setCurrentWidget(lazy)
        activation_elapsed = time.perf_counter() - started
        self.assertLess(activation_elapsed, 0.05)
        self.assertTrue(self._process_until(lambda: lazy.widget_if_created() is not None))

        timer.stop()
        self.assertTrue(prepared_on)
        self.assertIsNot(prepared_on[0], self.app.thread())
        self.assertEqual([self.app.thread()], ui_prepared_on)
        self.assertEqual([self.app.thread()], built_on)
        gaps = [later - earlier for earlier, later in zip(heartbeats, heartbeats[1:])]
        self.assertGreaterEqual(len(heartbeats), 5)
        self.assertLess(max(gaps, default=0.0), 0.2)
        tabs.close()
        self.app.processEvents()

    def test_shutdown_during_preload_drops_late_construction_and_retains_the_thread(self) -> None:
        release = threading.Event()
        builds: list[_ProbeTool] = []

        def prepare() -> None:
            release.wait(1.0)

        lazy = LazyToolTab(
            lambda: builds.append(_ProbeTool()) or builds[-1],
            prepare=prepare,
        )
        lazy.request_widget()
        self.assertTrue(self._process_until(lambda: bool(tuple(lazy.iter_shutdown_workers()))))

        lazy.request_shutdown()
        workers = tuple(lazy.iter_shutdown_workers())
        self.assertEqual("lazy tool preload", workers[0][0])
        release.set()
        self.assertTrue(self._process_until(lambda: not tuple(lazy.iter_shutdown_workers())))
        self.assertEqual([], builds)
        self.assertIsNone(lazy.widget_if_created())

    def test_shutdown_between_construction_and_publication_drops_created_callbacks(self) -> None:
        built = _ProbeTool()
        published: list[QWidget] = []
        lazy = LazyToolTab(lambda: built)
        lazy.when_created(published.append)
        lazy.request_widget()
        self.assertTrue(self._process_until(lambda: lazy._pending_widget is built))

        lazy.request_shutdown()
        self.assertTrue(self._process_until(lambda: lazy.widget_if_created() is built))
        self.assertEqual([], published)
        self.assertEqual(1, built.shutdown_requests)
        self.assertTrue(built.isHidden())

    def test_background_preload_allowlist_stays_free_of_pyside_imports(self) -> None:
        source_path = Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "shell" / "tool_tabs.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        assignments = {
            node.target.id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in {"_LAZY_TOOL_PRELOAD_MODULES", "_LAZY_TOOL_UI_MODULES"}
        }
        preload_modules = tuple(
            sorted({module for modules in assignments["_LAZY_TOOL_PRELOAD_MODULES"].values() for module in modules})
        )
        ui_keys = set(assignments["_LAZY_TOOL_UI_MODULES"])
        self.assertEqual(
            {
                "mesh_editor",
                "model_library",
                "item_icons",
                "new_item_studio",
                "replace_assistant",
                "recolor_variants",
                "texture_editor",
                "mod_package_retrofit",
                "placement_studio",
                "format_explorer",
                "translation_studio",
                "research",
                "text_search",
            },
            ui_keys,
        )
        script = (
            "import importlib, sys; "
            f"modules={preload_modules!r}; "
            "[(importlib.import_module(name), "
            "  (_ for _ in ()).throw(AssertionError(name)) "
            "  if any(module.startswith('PySide6') for module in sys.modules) else None) "
            " for name in modules]"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=source_path.parents[3],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr)

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

    def test_every_registered_tab_activation_keeps_the_qt_heartbeat_below_200_ms(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.ini"
            script = "\n".join(
                (
                    "import os, sys, time",
                    "from pathlib import Path",
                    "os.environ['QT_QPA_PLATFORM'] = 'offscreen'",
                    "os.environ['CDMW_GUI_STARTUP_SMOKE'] = '1'",
                    "os.environ['CDMW_MAIN_WINDOW_CLASS_ONLY'] = '1'",
                    "os.environ['CDMW_SINGLE_INSTANCE_SCOPE'] = f'tab-heartbeat-{os.getpid()}'",
                    "from cdmw.services import settings_service",
                    f"settings_path = Path({str(settings_path)!r})",
                    "settings_service.resolve_settings_file_path = lambda **_kwargs: settings_path",
                    "from PySide6.QtCore import QTimer",
                    "from PySide6.QtWidgets import QApplication",
                    "import cdmw.ui.shell.app_window as app_window",
                    "app_window.resolve_settings_file_path = lambda: settings_path",
                    "MainWindow = app_window.run_gui()",
                    "from cdmw.app.events import AppEventBus",
                    "from cdmw.services.service_container import ServiceContainer",
                    "from cdmw.ui.shell.app_context import AppContext",
                    "from cdmw.ui.shell.lazy_tool_tab import LazyToolTab",
                    "app = QApplication.instance() or QApplication([])",
                    "settings = settings_service.create_settings(settings_file_path=settings_path)",
                    "settings.setValue('ui/shell_variant', 'compact_rail')",
                    "context = AppContext(settings, ServiceContainer.create_default(settings=settings), AppEventBus())",
                    "window = MainWindow(app_context=context)",
                    "window.show(); app.processEvents()",
                    "keys = ('archive_browser','model_library','item_icons','new_item_studio','texture_workflow','replace_assistant','recolor_variants','texture_editor','mod_package_retrofit','format_explorer','translation_studio','research','text_search','mesh_editor','placement_studio','settings')",
                    "assert set(keys) == set(window._tool_widgets_by_key)",
                    "beats = []",
                    "timer = QTimer(); timer.setInterval(10); timer.timeout.connect(lambda: beats.append(time.perf_counter())); timer.start()",
                    "for key in keys:",
                    "    container = window._tool_widgets_by_key[key]",
                    "    beat_index = len(beats)",
                    "    started = time.perf_counter()",
                    "    window._activate_tool_key(key)",
                    "    assert time.perf_counter() - started < 0.05, key",
                    "    deadline = time.perf_counter() + 10.0",
                    "    while isinstance(container, LazyToolTab) and container.widget_if_created() is None and time.perf_counter() < deadline:",
                    "        app.processEvents(); time.sleep(0.001)",
                    "    app.processEvents()",
                    "    finished = time.perf_counter()",
                    "    assert not isinstance(container, LazyToolTab) or container.widget_if_created() is not None, key",
                    "    points = [started, *beats[beat_index:], finished]",
                    "    gaps = [later - earlier for earlier, later in zip(points, points[1:])]",
                    "    assert max(gaps, default=0.0) < 0.2, (key, max(gaps, default=0.0))",
                    "timer.stop(); window._request_tab_shutdowns(); window.hide()",
                    "for _ in range(20): app.processEvents(); time.sleep(0.005)",
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
                timeout=90,
            )

        self.assertEqual(
            0,
            result.returncode,
            f"All-tab heartbeat integration failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
