"""Gates for the Format Explorer: the rows, the headline, and the panel."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.format_explorer.catalogue import (  # noqa: E402
    MANIFEST,
    READ_WORDS,
    TOOLS,
    WRITE_WORDS,
    filter_rows,
    groups,
    headline,
    load_rows,
)


class RowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load_rows()

    def test_every_manifest_entry_becomes_a_row(self) -> None:
        entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["extensions"]
        self.assertEqual(len(self.rows), len(entries))

    def test_rows_are_ordered_by_how_much_the_game_ships(self) -> None:
        counts = [row.files for row in self.rows]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_every_status_word_has_a_plain_english_label(self) -> None:
        for row in self.rows:
            self.assertIn(row.decode, READ_WORDS)
            self.assertIn(row.write, WRITE_WORDS)

    def test_moddable_means_shipped_and_writable(self) -> None:
        for row in self.rows:
            expected = row.files > 0 and row.write in ("full", "constrained")
            self.assertEqual(row.moddable, expected, row.extension)

    def test_a_format_the_build_does_not_ship_is_never_moddable(self) -> None:
        """A phantom format must not be advertised as something to edit."""

        for row in self.rows:
            if row.files == 0:
                self.assertFalse(row.moddable, row.extension)

    def test_known_formats_name_the_tool_that_edits_them(self) -> None:
        by_extension = {row.extension: row for row in self.rows}
        self.assertEqual(by_extension[".paloc"].tool, "Translation Studio")
        self.assertEqual(by_extension[".dds"].tool, "Texture Workflow")
        self.assertEqual(by_extension[".pac"].tool, "Mesh Editor")

    def test_an_undecoded_format_offers_no_tool(self) -> None:
        by_extension = {row.extension: row for row in self.rows}
        self.assertEqual(by_extension[".padxil"].tool, "No tool yet")

    def test_every_named_tool_maps_to_a_real_extension(self) -> None:
        """A stale entry in TOOLS would advertise a tool for a format that is gone."""

        known = {row.extension for row in self.rows}
        for extension in TOOLS:
            self.assertIn(extension, known)


class HeadlineTests(unittest.TestCase):
    def test_the_headline_counts_only_what_the_build_ships(self) -> None:
        rows = load_rows()
        text = headline(rows)
        shipped = sum(1 for row in rows if row.shipped)
        self.assertIn(f"{shipped} file formats", text)
        self.assertIn("can be edited today", text)

    def test_the_headline_is_computed_not_asserted(self) -> None:
        """Numbers must follow the manifest, so they cannot go stale."""

        rows = load_rows()
        editable = [row for row in rows if row.moddable]
        self.assertIn(f"{len(editable)} of those formats", headline(rows))


class FilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load_rows()

    def test_shipped_only_is_the_default(self) -> None:
        self.assertTrue(all(row.shipped for row in filter_rows(self.rows)))

    def test_absent_formats_can_be_included(self) -> None:
        self.assertGreater(
            len(filter_rows(self.rows, shipped_only=False)),
            len(filter_rows(self.rows)),
        )

    def test_editable_only(self) -> None:
        rows = filter_rows(self.rows, editable_only=True)
        self.assertTrue(rows)
        self.assertTrue(all(row.moddable for row in rows))

    def test_search_matches_extension_area_and_tool(self) -> None:
        self.assertTrue(filter_rows(self.rows, ".paloc"))
        self.assertTrue(filter_rows(self.rows, "translation"))
        self.assertTrue(filter_rows(self.rows, "texture"))
        self.assertEqual(filter_rows(self.rows, "definitely not a format"), ())

    def test_group_filter(self) -> None:
        for group in groups(self.rows):
            rows = filter_rows(self.rows, group=group, shipped_only=False)
            self.assertTrue(all(row.group == group for row in rows))


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from tools.format_explorer.tab import FormatExplorerTab

        return FormatExplorerTab()

    def test_the_panel_fills_from_the_manifest(self) -> None:
        panel = self._panel()
        self.assertGreater(panel.table.rowCount(), 50)
        self.assertIn("can be edited today", panel.headline_label.text())

    def test_the_editable_filter_narrows_the_table(self) -> None:
        panel = self._panel()
        everything = panel.table.rowCount()
        panel.editable_only.setChecked(True)
        self.assertLess(panel.table.rowCount(), everything)
        self.assertGreater(panel.table.rowCount(), 0)

    def test_including_absent_formats_widens_it(self) -> None:
        panel = self._panel()
        shipped = panel.table.rowCount()
        panel.include_absent.setChecked(True)
        self.assertGreater(panel.table.rowCount(), shipped)

    def test_search_narrows_the_table(self) -> None:
        panel = self._panel()
        panel.search_box.setText("translation")
        self.assertGreater(panel.table.rowCount(), 0)
        panel.search_box.setText("definitely not a format")
        self.assertEqual(panel.table.rowCount(), 0)

    def test_selecting_a_row_explains_what_the_claim_rests_on(self) -> None:
        panel = self._panel()
        panel.search_box.setText(".paloc")
        panel.table.selectRow(0)
        detail = panel.detail.toHtml()
        self.assertIn("What this rests on", detail)
        self.assertIn("Translation Studio", detail)

    def test_an_empty_result_says_so_instead_of_showing_stale_detail(self) -> None:
        panel = self._panel()
        panel.search_box.setText("definitely not a format")
        self.assertIn("Nothing matches", panel.detail.toHtml())

    def test_the_selected_row_matches_what_is_on_screen(self) -> None:
        panel = self._panel()
        panel.search_box.setText(".dds")
        panel.table.selectRow(0)
        row = panel.selected_row()
        self.assertIsNotNone(row)
        self.assertEqual(panel.table.item(0, 0).text(), row.extension)
