from __future__ import annotations

import os
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox

from cdmw.domain.archives.filters import (
    archive_browser_entry_category,
    archive_filter_text_explicitly_requests_item_name,
    archive_filter_text_needs_item_name_search,
    build_archive_category_entry_index,
)
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.ui.archive_browser.filters import (
    ArchiveFilterStateMixin,
    archive_browser_entry_category as ui_archive_browser_entry_category,
    build_archive_category_entry_index as ui_build_archive_category_entry_index,
)
from cdmw.ui.archive_browser.filter_workers import _record_archive_filter_worker_lifecycle
from cdmw.ui.archive_browser.workers import _record_archive_worker_lifecycle
from cdmw.ui.texture_workflow.workflow_profiles_panel import TextureWorkflowProfilesPanelMixin


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("test.pamt"),
        paz_file=Path("test.paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class ArchiveBrowserFilterTests(unittest.TestCase):
    def test_editable_extension_filter_removes_all_files_prefix(self) -> None:
        app = QApplication.instance() or QApplication([])
        host_type = type("ArchiveFilterHost", (ArchiveFilterStateMixin, TextureWorkflowProfilesPanelMixin), {})
        host = host_type()
        host.archive_extension_filter_combo = QComboBox()
        host.archive_extension_filter_combo.setEditable(True)
        host._add_combo_choice(host.archive_extension_filter_combo, "All files", "*")
        host._add_combo_choice(host.archive_extension_filter_combo, ".pac (12,962)", ".pac")
        line_edit = host.archive_extension_filter_combo.lineEdit()
        line_edit.editingFinished.connect(host._canonicalize_archive_extension_filter_control)

        host.archive_extension_filter_combo.setEditText("All files.pac")
        line_edit.editingFinished.emit()

        self.assertEqual(".pac", host._combo_value(host.archive_extension_filter_combo))
        self.assertEqual(".pac (12,962)", host.archive_extension_filter_combo.currentText())
        self.assertIs(app, QApplication.instance())

    def test_archive_browser_entry_category_uses_asset_extension_and_path(self) -> None:
        self.assertEqual("Texture", archive_browser_entry_category(_entry("texture/foo.dds")))
        self.assertEqual("Physics", archive_browser_entry_category(_entry("meshphysics/foo.hkx")))
        self.assertEqual("Mesh", archive_browser_entry_category(_entry("model/foo.pac")))
        self.assertEqual("Text/Metadata", archive_browser_entry_category(_entry("metadata/foo.prefab")))
        self.assertEqual("Other", archive_browser_entry_category(_entry("unknown/foo.bin")))

    def test_category_entry_index_groups_entries_and_honors_cancellation(self) -> None:
        entries = (_entry("texture/a.dds"), _entry("model/a.pac"), _entry("texture/b.png"))
        grouped = build_archive_category_entry_index(entries)

        self.assertEqual([0, 2], grouped["Texture"])
        self.assertEqual([1], grouped["Mesh"])

        stop_event = threading.Event()
        stop_event.set()
        with self.assertRaises(RunCancelled):
            build_archive_category_entry_index(entries, stop_event=stop_event)

    def test_item_name_search_helpers_match_saved_filter_behavior(self) -> None:
        self.assertTrue(archive_filter_text_explicitly_requests_item_name("name: sword"))
        self.assertTrue(archive_filter_text_needs_item_name_search("damian"))
        self.assertTrue(archive_filter_text_needs_item_name_search("name: damian"))
        self.assertFalse(archive_filter_text_needs_item_name_search("character/model/*.pac"))
        self.assertFalse(archive_filter_text_needs_item_name_search(""))

    def test_ui_filter_module_preserves_legacy_helper_imports(self) -> None:
        self.assertIs(ui_archive_browser_entry_category, archive_browser_entry_category)
        self.assertIs(ui_build_archive_category_entry_index, build_archive_category_entry_index)

    def test_archive_worker_lifecycle_helpers_emit_explicit_reasons(self) -> None:
        class Recorder:
            def __init__(self) -> None:
                self.events: list[tuple[str, dict[str, object]]] = []

            def _record_runtime_event(self, event: str, **fields: object) -> None:
                self.events.append((event, fields))

        archive_recorder = Recorder()
        filter_recorder = Recorder()

        _record_archive_worker_lifecycle(
            archive_recorder,
            "archive_preview_worker_cancelled",
            reason="cancelled_by_new_request",
        )
        _record_archive_filter_worker_lifecycle(
            filter_recorder,
            "archive_filter_result_ignored",
            reason="stale_result_ignored",
        )

        self.assertEqual("archive_preview_worker_cancelled", archive_recorder.events[0][0])
        self.assertEqual("cancelled_by_new_request", archive_recorder.events[0][1]["reason"])
        self.assertEqual("archive_filter_result_ignored", filter_recorder.events[0][0])
        self.assertEqual("stale_result_ignored", filter_recorder.events[0][1]["reason"])

    def test_archive_worker_sources_name_cancellation_and_failure_states(self) -> None:
        workers_source = Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        filter_source = Path("cdmw/ui/archive_browser/filter_workers.py").read_text(encoding="utf-8")
        combined = workers_source + "\n" + filter_source

        for reason in (
            "cancelled_by_new_request",
            "cancelled_by_filter_change",
            "cancelled_by_shutdown",
            "stale_result_ignored",
            "worker_failed",
        ):
            self.assertIn(reason, combined)


if __name__ == "__main__":
    unittest.main()
