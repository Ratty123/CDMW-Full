"""Gates for Translation Studio: the catalogue, the virtualised model, and the panel."""

from __future__ import annotations

import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.paloc_format import (  # noqa: E402
    LocalizationEntry,
    LocalizationTable,
    PalocFormatError,
    encode_paloc,
    parse_paloc,
)
from tools.translation_studio.catalogue import (  # noqa: E402
    attach_reference,
    game_path_for,
    language_of,
    load_catalogue,
)


def _table(*rows: tuple[int, str, str]) -> bytes:
    return encode_paloc(
        LocalizationTable(
            entries=tuple(
                LocalizationEntry(category=c, key=k, text=t) for c, k, t in rows
            )
        )
    )


ENGLISH = _table(
    (38, "questdialog_main_00001", "The Greymanes ride at dawn."),
    (38, "questdialog_main_00002", "Take the sword."),
    (9, "262897", "Unavailable during combat."),
    (9, "262898", ""),
)
KOREAN = _table(
    (38, "questdialog_main_00001", "회색 갈기는 새벽에 달린다."),
    (38, "questdialog_main_00002", "검을 가져가라."),
    (9, "262897", "전투 중에는 사용할 수 없습니다."),
)


class PathTests(unittest.TestCase):
    def test_language_round_trips_through_the_game_path(self) -> None:
        self.assertEqual(language_of(game_path_for("eng")), "eng")
        self.assertEqual(language_of(game_path_for("zho-cn")), "zho-cn")

    def test_an_unrelated_path_has_no_language(self) -> None:
        self.assertEqual(language_of("character/model/x.pac"), "")
        self.assertEqual(language_of("gamedata/stringtable/binary__/other.paloc"), "")


class CatalogueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cat = load_catalogue(ENGLISH, "eng")

    def test_it_loads_every_line(self) -> None:
        self.assertEqual(len(self.cat), 4)

    def test_search_matches_text_and_key_case_insensitively(self) -> None:
        self.assertEqual(len(self.cat.find("greymanes")), 1)
        self.assertEqual(len(self.cat.find("QUESTDIALOG_MAIN")), 2)
        self.assertEqual(self.cat.find("nothing here"), ())

    def test_an_empty_search_returns_everything(self) -> None:
        self.assertEqual(len(self.cat.find("")), 4)

    def test_search_can_be_limited_by_group(self) -> None:
        self.assertEqual(len(self.cat.find("", category=9)), 2)

    def test_search_finds_a_line_by_its_new_wording(self) -> None:
        """Editing a line must not make it unfindable."""

        self.cat.set_text(1, "Take the axe.")
        self.assertEqual(len(self.cat.find("axe")), 1)
        self.assertEqual(self.cat.find("sword"), ())

    def test_a_limit_caps_the_result(self) -> None:
        self.assertEqual(len(self.cat.find("", limit=2)), 2)

    def test_regex_search(self) -> None:
        self.assertEqual(len(self.cat.find_regex(r"main_0000[12]")), 2)

    def test_editing_marks_the_row_and_counts_it(self) -> None:
        self.assertTrue(self.cat.set_text(0, "The Greymanes ride at noon."))
        self.assertEqual(self.cat.edit_count, 1)
        self.assertTrue(self.cat.row(0).edited)
        self.assertEqual(self.cat.row(0).text, "The Greymanes ride at noon.")

    def test_setting_a_line_back_to_shipped_text_clears_the_edit(self) -> None:
        shipped = self.cat.table.entries[0].text
        self.cat.set_text(0, "changed")
        self.assertEqual(self.cat.edit_count, 1)
        self.assertFalse(self.cat.set_text(0, shipped))
        self.assertEqual(self.cat.edit_count, 0)

    def test_revert_and_reset(self) -> None:
        self.cat.set_text(0, "a")
        self.cat.set_text(1, "b")
        self.cat.revert(0)
        self.assertEqual(self.cat.edit_count, 1)
        self.cat.reset()
        self.assertEqual(self.cat.edit_count, 0)

    def test_editing_out_of_range_raises(self) -> None:
        with self.assertRaises(PalocFormatError):
            self.cat.set_text(99, "x")

    def test_edited_only_filter(self) -> None:
        self.cat.set_text(2, "Not while fighting.")
        self.assertEqual(self.cat.find("", edited_only=True), (2,))

    def test_an_empty_line_is_still_editable(self) -> None:
        self.cat.set_text(3, "Now it says something.")
        self.assertEqual(self.cat.row(3).text, "Now it says something.")


class ReferenceTests(unittest.TestCase):
    def test_a_reference_language_shows_beside_the_working_one(self) -> None:
        cat = attach_reference(load_catalogue(ENGLISH, "eng"), KOREAN, "kor")
        self.assertEqual(cat.reference_language, "kor")
        self.assertEqual(cat.row(0).reference, "회색 갈기는 새벽에 달린다.")

    def test_a_key_absent_from_the_reference_shows_nothing(self) -> None:
        cat = attach_reference(load_catalogue(ENGLISH, "eng"), KOREAN, "kor")
        self.assertEqual(cat.row(3).reference, "")

    def test_the_reference_is_not_editable(self) -> None:
        cat = attach_reference(load_catalogue(ENGLISH, "eng"), KOREAN, "kor")
        cat.set_text(0, "changed")
        self.assertEqual(cat.row(0).reference, "회색 갈기는 새벽에 달린다.")


class ExportTests(unittest.TestCase):
    def test_an_unedited_catalogue_exports_nothing(self) -> None:
        self.assertEqual(load_catalogue(ENGLISH, "eng").changed_files(), {})

    def test_an_edit_exports_the_right_game_path(self) -> None:
        cat = load_catalogue(ENGLISH, "eng")
        cat.set_text(0, "Rewritten.")
        files = cat.changed_files()
        self.assertEqual(list(files), ["gamedata/stringtable/binary__/localizationstring_eng.paloc"])

    def test_the_exported_table_carries_the_edit_and_nothing_else(self) -> None:
        cat = load_catalogue(ENGLISH, "eng")
        cat.set_text(1, "Take the axe.")
        rebuilt = parse_paloc(list(cat.changed_files().values())[0])
        original = parse_paloc(ENGLISH)
        changed = [
            (a.key, a.text) for a, b in zip(rebuilt.entries, original.entries)
            if a.text != b.text
        ]
        self.assertEqual(changed, [("questdialog_main_00002", "Take the axe.")])

    def test_a_longer_line_is_safe(self) -> None:
        """Nothing in the format is offset-addressed, so length may change freely."""

        cat = load_catalogue(ENGLISH, "eng")
        cat.set_text(2, "Unavailable while you are engaged in combat with an enemy.")
        rebuilt = parse_paloc(list(cat.changed_files().values())[0])
        self.assertEqual(len(rebuilt), len(parse_paloc(ENGLISH)))
        self.assertIn("engaged in combat", rebuilt.entries[2].text)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _model(self):
        from tools.translation_studio.table_model import TranslationTableModel

        cat = attach_reference(load_catalogue(ENGLISH, "eng"), KOREAN, "kor")
        return TranslationTableModel(cat), cat

    def test_the_model_exposes_every_row_and_column(self) -> None:
        model, _cat = self._model()
        self.assertEqual(model.rowCount(), 4)
        self.assertEqual(model.columnCount(), 4)

    def test_a_view_filters_without_touching_the_catalogue(self) -> None:
        model, cat = self._model()
        model.set_view(cat.find("greymanes"))
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(len(cat), 4)

    def test_only_the_text_column_is_editable(self) -> None:
        from PySide6.QtCore import Qt

        model, _cat = self._model()
        self.assertTrue(model.flags(model.index(0, 2)) & Qt.ItemIsEditable)
        for column in (0, 1, 3):
            self.assertFalse(model.flags(model.index(0, column)) & Qt.ItemIsEditable)

    def test_setting_data_records_the_edit(self) -> None:
        from PySide6.QtCore import Qt

        model, cat = self._model()
        self.assertTrue(model.setData(model.index(0, 2), "Changed.", Qt.EditRole))
        self.assertEqual(cat.edit_count, 1)
        self.assertEqual(model.data(model.index(0, 2), Qt.DisplayRole), "Changed.")

    def test_an_edited_row_is_marked_and_keeps_the_shipped_text_in_reach(self) -> None:
        from PySide6.QtCore import Qt

        model, _cat = self._model()
        model.setData(model.index(0, 2), "Changed.", Qt.EditRole)
        self.assertIsNotNone(model.data(model.index(0, 0), Qt.BackgroundRole))
        self.assertIn("Ships as:", str(model.data(model.index(0, 2), Qt.ToolTipRole)))

    def test_reverting_a_row_clears_the_mark(self) -> None:
        from PySide6.QtCore import Qt

        model, cat = self._model()
        model.setData(model.index(0, 2), "Changed.", Qt.EditRole)
        model.revert_row(0)
        self.assertEqual(cat.edit_count, 0)
        self.assertIsNone(model.data(model.index(0, 0), Qt.BackgroundRole))

    def test_the_reference_column_shows_the_other_language(self) -> None:
        from PySide6.QtCore import Qt

        model, _cat = self._model()
        self.assertEqual(
            model.data(model.index(0, 3), Qt.DisplayRole), "회색 갈기는 새벽에 달린다."
        )

    def test_filtering_does_not_stack_selection_connections(self) -> None:
        """Reconnecting per keystroke left one duplicate slot per filter change."""

        from tools.translation_studio.tab import TranslationStudioTab

        tab = TranslationStudioTab()
        cat = load_catalogue(ENGLISH, "eng")
        tab._catalogue = cat
        tab.model.set_catalogue(cat)
        tab.category_box.addItem("All groups", None)
        signal = "2selectionChanged(QItemSelection,QItemSelection)"
        before = tab.table.selectionModel().receivers(signal)
        for text in ("a", "ab", "abc", "greymanes"):
            tab.search_box.setText(text)
        # QTableView keeps internal connections of its own, so the count is not 1; what
        # matters is that filtering does not add to it.
        self.assertEqual(tab.table.selectionModel().receivers(signal), before)

    def test_an_empty_model_answers_without_a_catalogue(self) -> None:
        from tools.translation_studio.table_model import TranslationTableModel

        model = TranslationTableModel()
        self.assertEqual(model.rowCount(), 0)
        self.assertIsNone(model.data(model.index(0, 0)))


@pytest.mark.real_game
class VanillaTranslationTests(unittest.TestCase):
    """The shipped tables: 187,521 lines each, fourteen languages."""

    def _data(self, language: str):
        from tools.placement_studio import corpus
        from tools.translation_studio.catalogue import read_language

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        return read_language(language)

    def test_the_english_table_loads_and_searches(self) -> None:
        cat = load_catalogue(self._data("eng"), "eng")
        self.assertGreater(len(cat), 100_000)
        self.assertTrue(cat.find("the"))

    def test_an_edit_round_trips_through_the_export(self) -> None:
        cat = load_catalogue(self._data("eng"), "eng")
        hits = cat.find("questdialog", limit=1)
        self.assertTrue(hits)
        cat.set_text(hits[0], "A line a mod wrote.")
        rebuilt = parse_paloc(list(cat.changed_files().values())[0])
        self.assertEqual(rebuilt.entries[hits[0]].text, "A line a mod wrote.")
        self.assertEqual(len(rebuilt), len(cat))

    def test_every_shipped_language_is_offered(self) -> None:
        from tools.placement_studio import corpus
        from tools.translation_studio.catalogue import available_languages

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        languages = available_languages()
        self.assertGreaterEqual(len(languages), 10)
        self.assertIn("eng", languages)
