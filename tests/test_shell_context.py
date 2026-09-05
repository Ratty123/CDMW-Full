from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QTabWidget, QWidget

from cdmw.app.events import AppEventBus
from cdmw.ui.shell.close_controller import (
    WORKER_TAB_NAMES,
    iter_tab_shutdown_workers,
    request_tab_shutdowns,
)
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.shell.tab_registry import TabRegistry


class ShellContextTests(unittest.TestCase):
    def test_context_from_settings_reuses_one_settings_instance(self) -> None:
        settings = QSettings("CDMWTests", "ContextReuse")

        context = AppContext.from_settings(settings)

        self.assertIs(settings, context.settings)
        self.assertIs(settings, context.services.settings)

    def test_event_bus_delivers_payload(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        bus = AppEventBus()
        bus.subscribe("startup", lambda event: events.append((event.name, event.payload)))

        published = bus.publish("startup", phase="tabs")

        self.assertEqual(published.name, "startup")
        self.assertEqual(events, [("startup", {"phase": "tabs"})])

    def test_default_app_context_contains_services_and_event_bus(self) -> None:
        context = AppContext.create_default()

        self.assertIs(context.services.settings, context.settings)
        self.assertIsInstance(context.event_bus, AppEventBus)

    def test_registry_owns_the_widget_and_native_title_once(self) -> None:
        app = QApplication.instance() or QApplication([])
        registry = TabRegistry()
        widget = QLabel("Sample")
        registry.register("archive_browser", widget, "Archive Browser")
        self.assertIs(registry.widgets["archive_browser"], widget)
        self.assertEqual(registry.titles["archive_browser"], "Browse Archives")
        with self.assertRaises(ValueError):
            registry.register("archive_browser", QWidget(), "Second copy")
        widget.deleteLater()
        app.processEvents()

    def test_close_controller_discovers_and_requests_tab_shutdown(self) -> None:
        class WorkerTab:
            def __init__(self) -> None:
                self.shutdown_requested = False

            def iter_shutdown_workers(self) -> tuple[tuple[str, object, object], ...]:
                return (("scan", object(), object()),)

            def request_shutdown(self) -> None:
                self.shutdown_requested = True

        class Owner:
            text_search_tab = WorkerTab()

        owner = Owner()

        workers = list(iter_tab_shutdown_workers(owner, tab_names=("text_search_tab",)))
        request_tab_shutdowns(owner, tab_names=("text_search_tab",))

        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0][0], "text_search_tab.scan")
        self.assertTrue(owner.text_search_tab.shutdown_requested)

    def test_close_controller_default_tracks_mesh_editor_tab_shutdown(self) -> None:
        class WorkerTab:
            def __init__(self) -> None:
                self.shutdown_requested = False

            def iter_shutdown_workers(self) -> tuple[tuple[str, object, object], ...]:
                return (
                    ("standalone_file_load", object(), object()),
                    ("standalone_native_package", object(), object()),
                )

            def request_shutdown(self) -> None:
                self.shutdown_requested = True

        class Owner:
            mesh_editor_tab = WorkerTab()

        owner = Owner()

        workers = list(iter_tab_shutdown_workers(owner))
        request_tab_shutdowns(owner)
        worker_names = [name for name, _thread, _worker in workers]

        self.assertIn("mesh_editor_tab.standalone_file_load", worker_names)
        self.assertIn("mesh_editor_tab.standalone_native_package", worker_names)
        self.assertTrue(owner.mesh_editor_tab.shutdown_requested)

    def test_close_controller_default_tracks_settings_tab_shutdown(self) -> None:
        class WorkerTab:
            def __init__(self) -> None:
                self.shutdown_requested = False

            def iter_shutdown_workers(self) -> tuple[tuple[str, object, object], ...]:
                return (("asset_authoring_helper_versions", object(), object()),)

            def request_shutdown(self) -> None:
                self.shutdown_requested = True

        class Owner:
            settings_tab = WorkerTab()

        owner = Owner()

        workers = list(iter_tab_shutdown_workers(owner))
        request_tab_shutdowns(owner)
        worker_names = [name for name, _thread, _worker in workers]

        self.assertIn("settings_tab.asset_authoring_helper_versions", worker_names)
        self.assertTrue(owner.settings_tab.shutdown_requested)

    def test_close_controller_tracks_every_lazy_import_owner(self) -> None:
        self.assertIn("format_explorer_tab", WORKER_TAB_NAMES)
        self.assertIn("translation_studio_tab", WORKER_TAB_NAMES)


if __name__ == "__main__":
    unittest.main()
