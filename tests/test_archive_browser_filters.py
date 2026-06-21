from __future__ import annotations

import threading
import unittest
from pathlib import Path

from cdmw.domain.archives.filters import (
    archive_browser_entry_category,
    archive_filter_text_explicitly_requests_item_name,
    archive_filter_text_needs_item_name_search,
    build_archive_category_entry_index,
)
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.ui.archive_browser.filters import (
    archive_browser_entry_category as ui_archive_browser_entry_category,
    build_archive_category_entry_index as ui_build_archive_category_entry_index,
)


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


if __name__ == "__main__":
    unittest.main()
