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

        # A whole tab, so it does not get left for the collector to destroy at
        # some later test's expense.
        from PySide6.QtWidgets import QApplication

        tab.close()
        tab.deleteLater()
        QApplication.processEvents()

    def test_an_empty_model_answers_without_a_catalogue(self) -> None:
        from tools.translation_studio.table_model import TranslationTableModel

        model = TranslationTableModel()
        self.assertEqual(model.rowCount(), 0)
        self.assertIsNone(model.data(model.index(0, 0)))


class LanguageIndexTests(unittest.TestCase):
    """The cache that turned a 3.6 s tab open into an 11 ms one."""

    def setUp(self) -> None:
        from tools.translation_studio import language_index

        self.module = language_index
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "game"
        self.root.mkdir()
        self._previous = os.environ.get("CDMW_TS_WORK_ROOT")
        os.environ["CDMW_TS_WORK_ROOT"] = str(Path(self._tmp.name) / "work")
        self.tables = {}
        for package in ("0000", "0019", "0020"):
            path = self.root / package / "0.pamt"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"x" * (len(package) + 1))
            self.tables[package] = path
        self._install_fakes()

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("CDMW_TS_WORK_ROOT", None)
        else:
            os.environ["CDMW_TS_WORK_ROOT"] = self._previous
        self._restore()
        self._tmp.cleanup()

    def _install_fakes(self) -> None:
        """Stand in for the archive reader: 33 real tables are not a unit test."""

        import cdmw.core.archive_format as archive_format

        self.contents = {
            self.tables["0000"]: ["character/model/x.pac"] * 3,
            self.tables["0019"]: ["gamedata/stringtable/binary__/localizationstring_eng.paloc"],
            self.tables["0020"]: ["gamedata/stringtable/binary__/localizationstring_kor.paloc"],
        }
        self.parsed = []

        class _Entry:
            def __init__(self, path):
                self.path = path

        def _parse(pamt, paz_dir=None):
            self.parsed.append(Path(pamt))
            return [_Entry(path) for path in self.contents[Path(pamt)]]

        self._real_parse = archive_format.parse_archive_pamt
        self._real_tables = self.module._package_tables
        archive_format.parse_archive_pamt = _parse
        self.module._package_tables = lambda root: (
            sorted(self.tables.values()) if Path(root) == self.root else []
        )

    def _restore(self) -> None:
        import cdmw.core.archive_format as archive_format

        archive_format.parse_archive_pamt = self._real_parse
        self.module._package_tables = self._real_tables

    def test_it_finds_every_language_and_where_it_lives(self) -> None:
        index = self.module.build_index(self.root)
        self.assertEqual(index.languages, ("eng", "kor"))
        self.assertEqual(index.source_for("eng"), self.tables["0019"])
        self.assertIsNone(index.source_for("fre"))

    def test_a_second_open_reads_the_cache_instead_of_the_archives(self) -> None:
        self.module.build_index(self.root)
        self.parsed.clear()
        index = self.module.language_index(self.root)
        self.assertEqual(index.languages, ("eng", "kor"))
        self.assertEqual(self.parsed, [], "a warm open must not parse a package table")

    def test_a_changed_package_invalidates_the_cache(self) -> None:
        self.module.build_index(self.root)
        self.tables["0019"].write_bytes(b"y" * 99)
        self.assertIsNone(self.module.load_cached(self.root))
        self.parsed.clear()
        self.assertEqual(self.module.language_index(self.root).languages, ("eng", "kor"))
        self.assertTrue(self.parsed, "an invalid cache must fall back to the sweep")

    def test_the_cache_is_not_reused_for_another_game_root(self) -> None:
        self.module.build_index(self.root)
        self.assertIsNone(self.module.load_cached(self.root.parent / "elsewhere"))

    def test_a_missing_cache_is_not_an_error(self) -> None:
        self.assertIsNone(self.module.load_cached(self.root))
        self.assertFalse(self.module.is_warm(self.root))

    def test_a_corrupt_cache_is_not_an_error(self) -> None:
        self.module.build_index(self.root)
        self.module.cache_path().write_text("{ not json", encoding="utf-8")
        self.assertIsNone(self.module.load_cached(self.root))

    def test_the_highest_package_wins_when_two_carry_the_same_language(self) -> None:
        """A patch package overwrites an earlier one, the way baseline extraction reads it."""

        self.contents[self.tables["0000"]] = [
            "gamedata/stringtable/binary__/localizationstring_eng.paloc"
        ]
        index = self.module.build_index(self.root)
        self.assertEqual(index.source_for("eng"), self.tables["0019"])


class PlaceholderTests(unittest.TestCase):
    """Markup is the thing a machine translation actually breaks."""

    def setUp(self) -> None:
        from tools.translation_studio import ai_translate

        self.module = ai_translate

    def test_it_recognises_the_markup_the_game_uses(self) -> None:
        found = self.module.tokens(
            "A<br/>B {Key:Key_Roll} {Money:Money_Copper:1} {emoji:cd_icon_x} {Param0} %1 [EMPTY]"
        )
        self.assertEqual(
            found,
            ("%1", "<br/>", "[EMPTY]", "{Key:Key_Roll}", "{Money:Money_Copper:1}",
             "{Param0}", "{emoji:cd_icon_x}"),
        )

    def test_prose_in_brackets_is_not_markup(self) -> None:
        """`[Effect]` is a heading the player reads; `[EMPTY]` is a sentinel."""

        self.assertEqual(self.module.tokens("[Effect] Restores Health"), ())

    def test_a_translated_placeholder_is_caught(self) -> None:
        changed = self.module.token_mismatch(
            "Press {Key:Key_Roll} to roll", "Tryck {Tangent:Key_Roll} för att rulla"
        )
        self.assertEqual(changed, ("{Key:Key_Roll}", "{Tangent:Key_Roll}"))

    def test_a_dropped_line_break_is_caught(self) -> None:
        self.assertEqual(self.module.token_mismatch("a<br/>b<br/>c", "a<br/>bc"), ("<br/>",))

    def test_a_faithful_translation_passes(self) -> None:
        self.assertEqual(
            self.module.token_mismatch("Take the sword.<br/>{Key:Key_Roll}",
                                       "Ta svärdet.<br/>{Key:Key_Roll}"),
            (),
        )

    def test_reordering_the_prose_around_a_token_is_fine(self) -> None:
        self.assertEqual(
            self.module.token_mismatch("{Param0} gold", "guld: {Param0}"), ()
        )


class BatchingTests(unittest.TestCase):
    def _lines(self, count: int, length: int = 10):
        from tools.translation_studio.ai_translate import Line

        return [Line(index=i, text="x" * length) for i in range(count)]

    def test_batches_respect_the_line_count(self) -> None:
        from tools.translation_studio.ai_translate import build_batches

        batches = build_batches(self._lines(25), batch_size=10)
        self.assertEqual([len(batch) for batch in batches], [10, 10, 5])

    def test_a_batch_of_long_lines_is_split_by_size(self) -> None:
        """Twenty item names and twenty quest paragraphs are not the same request."""

        from tools.translation_studio.ai_translate import build_batches

        batches = build_batches(self._lines(10, length=2000), batch_size=10, max_chars=6000)
        self.assertGreater(len(batches), 1)
        self.assertTrue(all(len(batch) <= 3 for batch in batches))

    def test_every_line_survives_the_split(self) -> None:
        from tools.translation_studio.ai_translate import build_batches

        lines = self._lines(37)
        seen = [line.index for batch in build_batches(lines, batch_size=7) for line in batch]
        self.assertEqual(seen, [line.index for line in lines])


class RequestShapeTests(unittest.TestCase):
    """Three providers, three request shapes, one place they differ."""

    def _config(self, preset: str, **kwargs):
        from tools.translation_studio.ai_provider import ProviderConfig

        return ProviderConfig(preset=preset, model="m", api_key="secret", **kwargs)

    def test_anthropic(self) -> None:
        import json

        from tools.translation_studio.ai_translate import build_request

        request = build_request(self._config("anthropic"), "SYS", "USER")
        self.assertEqual(request.url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.headers["x-api-key"], "secret")
        self.assertEqual(request.headers["anthropic-version"], "2023-06-01")
        body = json.loads(request.body)
        self.assertEqual(body["system"], "SYS")
        self.assertEqual(body["messages"][0]["content"], "USER")
        self.assertEqual(body["thinking"], {"type": "disabled"})

    def test_anthropic_can_leave_thinking_alone(self) -> None:
        import json

        from tools.translation_studio.ai_translate import build_request

        request = build_request(self._config("anthropic", disable_thinking=False), "S", "U")
        self.assertNotIn("thinking", json.loads(request.body))

    def test_openai(self) -> None:
        import json

        from tools.translation_studio.ai_translate import build_request

        request = build_request(self._config("openai"), "SYS", "USER")
        self.assertEqual(request.url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer secret")
        roles = [m["role"] for m in json.loads(request.body)["messages"]]
        self.assertEqual(roles, ["system", "user"])

    def test_an_openai_compatible_endpoint_keeps_its_own_base_url(self) -> None:
        from tools.translation_studio.ai_translate import build_request

        config = self._config("openai_compatible", base_url="https://openrouter.ai/api/")
        self.assertEqual(
            build_request(config, "S", "U").url,
            "https://openrouter.ai/api/v1/chat/completions",
        )

    def test_gemini_puts_the_key_in_a_header_not_the_url(self) -> None:
        from tools.translation_studio.ai_translate import build_request

        request = build_request(self._config("gemini"), "S", "U")
        self.assertIn(":generateContent", request.url)
        self.assertNotIn("secret", request.url)
        self.assertEqual(request.headers["x-goog-api-key"], "secret")

    def test_a_local_model_sends_no_credentials(self) -> None:
        from tools.translation_studio.ai_provider import ProviderConfig
        from tools.translation_studio.ai_translate import build_request

        request = build_request(ProviderConfig(preset="ollama", model="llama3.1"), "S", "U")
        self.assertTrue(request.url.startswith("http://localhost:11434/"))
        self.assertNotIn("Authorization", request.headers)


class ResponseParsingTests(unittest.TestCase):
    def test_each_provider_puts_the_text_somewhere_else(self) -> None:
        from tools.translation_studio.ai_translate import extract_text

        self.assertEqual(
            extract_text("anthropic", {"content": [{"type": "text", "text": "hi"}]}), "hi"
        )
        self.assertEqual(
            extract_text("openai", {"choices": [{"message": {"content": "hi"}}]}), "hi"
        )
        self.assertEqual(
            extract_text("gemini", {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}),
            "hi",
        )

    def test_an_empty_reply_is_not_a_crash(self) -> None:
        from tools.translation_studio.ai_translate import extract_text

        for api in ("anthropic", "openai", "gemini"):
            self.assertEqual(extract_text(api, {}), "")

    def test_a_plain_json_array(self) -> None:
        from tools.translation_studio.ai_translate import parse_translations

        self.assertEqual(
            parse_translations('[{"i": 3, "t": "tre"}, {"i": 1, "t": "ett"}]'),
            {3: "tre", 1: "ett"},
        )

    def test_a_fenced_array_with_a_preamble(self) -> None:
        from tools.translation_studio.ai_translate import parse_translations

        reply = 'Sure, here you go:\n```json\n[{"i": 0, "t": "noll"}]\n```\nHope that helps.'
        self.assertEqual(parse_translations(reply), {0: "noll"})

    def test_an_object_keyed_by_id(self) -> None:
        from tools.translation_studio.ai_translate import parse_translations

        self.assertEqual(parse_translations('{"0": "noll", "1": "ett"}'), {0: "noll", 1: "ett"})

    def test_a_reply_with_no_json_at_all_is_reported(self) -> None:
        from tools.translation_studio.ai_translate import ProviderError, parse_translations

        with self.assertRaises(ProviderError):
            parse_translations("I'm sorry, I can't help with that.")

    def test_a_providers_own_error_message_is_surfaced(self) -> None:
        from tools.translation_studio.ai_translate import describe_error

        message = describe_error(401, b'{"error": {"message": "invalid x-api-key"}}')
        self.assertIn("invalid x-api-key", message)
        self.assertIn("401", message)


class BatchCheckTests(unittest.TestCase):
    def _batch(self):
        from tools.translation_studio.ai_translate import Line

        return (
            Line(index=10, text="Take the sword.<br/>"),
            Line(index=11, text="Press {Key:Key_Roll}"),
            Line(index=12, text="Greymane"),
            Line(index=13, text="262897"),
        )

    def _check(self, replies, skip=True):
        from tools.translation_studio.ai_job import check_batch

        return check_batch(1, self._batch(), replies, skip_on_mismatch=skip)

    def test_a_faithful_batch_is_accepted(self) -> None:
        result = self._check({10: "Ta svärdet.<br/>", 11: "Tryck {Key:Key_Roll}"})
        self.assertEqual(set(result.accepted), {10, 11})

    def test_a_broken_placeholder_is_left_alone_and_explained(self) -> None:
        result = self._check({10: "Ta svärdet.", 11: "Tryck {Key:Key_Roll}"})
        self.assertNotIn(10, result.accepted)
        self.assertEqual(result.rejected[0][0], 10)
        self.assertIn("<br/>", result.rejected[0][1])

    def test_the_check_can_be_turned_off(self) -> None:
        result = self._check({10: "Ta svärdet."}, skip=False)
        self.assertEqual(result.accepted[10], "Ta svärdet.")

    def test_a_line_the_model_dropped_is_reported(self) -> None:
        result = self._check({10: "Ta svärdet.<br/>"})
        dropped = {index for index, _reason in result.rejected}
        self.assertEqual(dropped, {11, 12, 13})

    def test_an_unchanged_line_is_not_recorded_as_an_edit(self) -> None:
        """A numeric or markup-only line legitimately comes back identical."""

        result = self._check({13: "262897"})
        self.assertNotIn(13, result.accepted)
        self.assertNotIn(13, {index for index, _reason in result.rejected})


class JobRunTests(unittest.TestCase):
    """A whole pass, retries and cancellation included, without a network or a key."""

    def _lines(self, count: int):
        from tools.translation_studio.ai_translate import Line

        return [Line(index=i, text=f"line {i}<br/>") for i in range(count)]

    def _config(self, **kwargs):
        from tools.translation_studio.ai_provider import ProviderConfig

        options = {"preset": "anthropic", "model": "m", "api_key": "k", "batch_size": 5,
                   "parallel": 1}
        options.update(kwargs)
        return ProviderConfig(**options)

    def _brief(self):
        from tools.translation_studio.ai_translate import TranslationBrief

        return TranslationBrief(target_language="Swedish", source_language="English")

    def _reply(self, request):
        """Echo back a plausible translation for whatever ids the request carried."""

        import json
        import re

        payload = json.loads(request.body)
        user = payload["messages"][-1]["content"]
        ids = [int(found) for found in re.findall(r'"i": (\d+)', user)]
        answer = [{"i": i, "t": f"rad {i}<br/>"} for i in ids]
        return 200, json.dumps(
            {"content": [{"type": "text", "text": json.dumps(answer)}]}
        ).encode("utf-8")

    def test_every_line_comes_back_translated(self) -> None:
        from tools.translation_studio.ai_job import run_job

        applied = {}
        summary = run_job(
            config=self._config(),
            brief=self._brief(),
            lines=self._lines(12),
            transport=lambda request, timeout: self._reply(request),
            on_result=lambda result: applied.update(result.accepted),
        )
        self.assertEqual(summary.translated, 12)
        self.assertEqual(summary.rejected, 0)
        self.assertEqual(applied[7], "rad 7<br/>")

    def test_partial_work_is_applied_as_it_lands(self) -> None:
        """Batches arrive one at a time, so stopping keeps what was paid for."""

        from tools.translation_studio.ai_job import run_job

        seen = []
        run_job(
            config=self._config(batch_size=5),
            brief=self._brief(),
            lines=self._lines(12),
            transport=lambda request, timeout: self._reply(request),
            on_result=lambda result: seen.append(len(result.accepted)),
        )
        self.assertEqual(seen, [5, 5, 2])

    def test_a_rate_limit_is_retried(self) -> None:
        from tools.translation_studio.ai_job import run_job

        calls = []

        def _transport(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                return 429, b'{"error": {"message": "slow down"}}'
            return self._reply(request)

        summary = run_job(
            config=self._config(), brief=self._brief(), lines=self._lines(3),
            transport=_transport,
            # A retry that actually slept would make this test two seconds long.
            should_stop=lambda: False,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(summary.translated, 3)

    def test_a_bad_key_is_not_retried_and_is_reported(self) -> None:
        from tools.translation_studio.ai_job import run_job

        calls = []

        def _transport(request, timeout):
            calls.append(request)
            return 401, b'{"error": {"message": "invalid x-api-key"}}'

        summary = run_job(
            config=self._config(), brief=self._brief(), lines=self._lines(3),
            transport=_transport,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary.failed_batches, 1)
        self.assertEqual(summary.translated, 0)
        self.assertIn("invalid x-api-key", summary.errors[0])

    def test_cancelling_stops_queueing_and_keeps_what_landed(self) -> None:
        from tools.translation_studio.ai_job import run_job

        state = {"stop": False, "batches": 0}

        def _transport(request, timeout):
            state["batches"] += 1
            state["stop"] = True  # cancel the moment the first request is served
            return self._reply(request)

        summary = run_job(
            config=self._config(batch_size=5), brief=self._brief(), lines=self._lines(50),
            transport=_transport, should_stop=lambda: state["stop"],
        )
        self.assertTrue(summary.cancelled)
        self.assertLess(state["batches"], 10)
        self.assertEqual(summary.translated, 5 * state["batches"])

    def test_an_empty_reply_is_reported_as_a_failed_request(self) -> None:
        """Usually a token ceiling; "the model dropped every line" would misdirect."""

        import json

        from tools.translation_studio.ai_job import run_job

        summary = run_job(
            config=self._config(), brief=self._brief(), lines=self._lines(3),
            transport=lambda request, timeout: (
                200, json.dumps({"content": []}).encode("utf-8")
            ),
        )
        self.assertEqual(summary.failed_batches, 1)
        self.assertEqual(summary.rejected, 0)
        self.assertIn("max reply tokens", summary.errors[0])

    def test_a_broken_reply_fails_one_batch_not_the_pass(self) -> None:
        from tools.translation_studio.ai_job import run_job

        def _transport(request, timeout):
            import json

            if b"line 0<" in request.body:
                return 200, json.dumps(
                    {"content": [{"type": "text", "text": "Sorry, no."}]}
                ).encode("utf-8")
            return self._reply(request)

        summary = run_job(
            config=self._config(batch_size=5), brief=self._brief(), lines=self._lines(12),
            transport=_transport,
        )
        self.assertEqual(summary.failed_batches, 1)
        self.assertEqual(summary.translated, 7)


class ProviderConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._previous = os.environ.get("CDMW_TS_WORK_ROOT")
        os.environ["CDMW_TS_WORK_ROOT"] = self._tmp.name

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("CDMW_TS_WORK_ROOT", None)
        else:
            os.environ["CDMW_TS_WORK_ROOT"] = self._previous
        self._tmp.cleanup()

    def test_a_key_round_trips_through_storage(self) -> None:
        from tools.translation_studio.ai_provider import protect_secret, unprotect_secret

        stored, _encrypted = protect_secret("sk-ant-secret-value")
        self.assertEqual(unprotect_secret(stored), "sk-ant-secret-value")

    def test_the_key_is_never_written_in_the_clear_on_windows(self) -> None:
        from tools.translation_studio.ai_provider import (
            ProviderConfig,
            config_path,
            save_config,
        )

        saved = save_config(ProviderConfig(model="m", api_key="sk-ant-secret-value"))
        written = config_path().read_text(encoding="utf-8")
        self.assertNotIn("sk-ant-secret-value", written)
        if sys.platform == "win32":
            self.assertTrue(saved.key_is_encrypted)
            self.assertIn("dpapi:", written)

    def test_a_saved_config_loads_back(self) -> None:
        from tools.translation_studio.ai_provider import (
            ProviderConfig,
            load_config,
            save_config,
        )

        save_config(
            ProviderConfig(preset="gemini", model="gemini-x", api_key="k", batch_size=7,
                           parallel=3, disable_thinking=False)
        )
        loaded = load_config()
        self.assertEqual(loaded.preset, "gemini")
        self.assertEqual(loaded.model, "gemini-x")
        self.assertEqual(loaded.api_key, "k")
        self.assertEqual(loaded.batch_size, 7)
        self.assertFalse(loaded.disable_thinking)

    def test_a_missing_config_is_the_default_one(self) -> None:
        from tools.translation_studio.ai_provider import DEFAULT_PRESET, load_config

        self.assertEqual(load_config().preset, DEFAULT_PRESET)

    def test_a_config_says_what_is_still_missing(self) -> None:
        from tools.translation_studio.ai_provider import ProviderConfig

        self.assertIn("no model", ProviderConfig(api_key="k").problems())
        self.assertIn("no API key", ProviderConfig(model="m").problems())
        self.assertTrue(ProviderConfig(model="m", api_key="k").is_ready)

    def test_a_local_model_needs_no_key(self) -> None:
        from tools.translation_studio.ai_provider import ProviderConfig

        self.assertTrue(ProviderConfig(preset="ollama", model="llama3.1").is_ready)

    def test_garbage_in_the_file_does_not_break_the_panel(self) -> None:
        from tools.translation_studio.ai_provider import config_path, load_config

        config_path().parent.mkdir(parents=True, exist_ok=True)
        config_path().write_text("not json at all", encoding="utf-8")
        self.assertFalse(load_config().is_ready)


class TabAiTests(unittest.TestCase):
    """The panel's side of it: scopes in, translations into the same edit map."""

    @classmethod
    def setUpClass(cls) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._built_tabs: list = []

    def tearDown(self) -> None:
        # Every test here builds a whole TranslationStudioTab and none of them
        # were ever destroyed, so the widget trees accumulated across the class
        # and the interpreter died part-way through this file at 98% of a full
        # run -- on 3.14 only, while 3.11 finished clean. close() then one
        # processEvents() pass, not a forced delete, which crashes a widget
        # mid-teardown.
        from PySide6.QtWidgets import QApplication

        while self._built_tabs:
            tab = self._built_tabs.pop()
            tab.close()
            tab.deleteLater()
        QApplication.processEvents()

    def _tab(self):
        from tools.translation_studio.tab import TranslationStudioTab

        tab = TranslationStudioTab()
        self._built_tabs.append(tab)
        cat = load_catalogue(ENGLISH, "eng")
        tab._catalogue = cat
        tab.model.set_catalogue(cat)
        tab.category_box.addItem("All groups", None)
        tab._refresh_view()
        return tab, cat

    def test_the_language_list_arrives_after_the_tab_is_built(self) -> None:
        """The sweep behind this used to run in the constructor and cost 3.6 seconds."""

        tab, _cat = self._tab()
        tab.language_box.clear()
        tab.reference_box.clear()
        tab.load_button.setEnabled(False)
        tab._on_languages(("eng", "kor"), "")
        self.assertEqual(tab.language_box.count(), 2)
        self.assertTrue(tab.load_button.isEnabled())

    def test_a_failed_listing_says_so_rather_than_raising(self) -> None:
        tab, _cat = self._tab()
        tab._on_languages(None, "the archives are not where you said")
        self.assertIn("not where you said", tab.status_label.text())

    def test_scopes_cover_the_view_and_the_whole_table(self) -> None:
        tab, cat = self._tab()
        labels = [label for label, _lines in tab.ai_scopes()]
        self.assertIn("The lines shown below", labels)
        self.assertIn(f"Every line in {cat.language}", labels)

    def test_a_search_offers_its_own_matches_as_a_scope(self) -> None:
        tab, _cat = self._tab()
        tab.search_box.setText("questdialog")
        scopes = dict(tab.ai_scopes())
        self.assertEqual(len(scopes["The lines shown below"]), 2)

    def test_an_empty_line_is_never_sent_for_translation(self) -> None:
        tab, cat = self._tab()
        every = dict(tab.ai_scopes())[f"Every line in {cat.language}"]
        self.assertEqual(len(every), 3, "the blank fourth line has nothing to translate")

    def test_a_line_carries_its_group_as_context(self) -> None:
        tab, _cat = self._tab()
        line = tab._lines_for([0])[0]
        self.assertTrue(line.context, "the model is told which group a line belongs to")

    def test_translations_land_in_the_same_edit_map_as_a_hand_edit(self) -> None:
        tab, cat = self._tab()
        applied = tab.apply_ai_translations({0: "Gråmanarna rider i gryningen."})
        self.assertEqual(applied, 1)
        self.assertEqual(cat.edit_count, 1)
        self.assertTrue(cat.row(0).edited)
        self.assertTrue(tab.export_button.isEnabled())

    def test_an_out_of_range_index_does_not_lose_the_batch(self) -> None:
        tab, cat = self._tab()
        applied = tab.apply_ai_translations({0: "Ny text.", 9999: "nonsense"})
        self.assertEqual(applied, 1)
        self.assertEqual(cat.edit_count, 1)

    def test_a_machine_translation_can_be_reverted_like_any_other_edit(self) -> None:
        tab, cat = self._tab()
        tab.apply_ai_translations({0: "Ny text.", 1: "Ta yxan."})
        cat.revert(0)
        self.assertEqual(cat.edit_count, 1)


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
