"""Current per-language tables retain their source paths and row/reference boundaries."""

from types import SimpleNamespace

import pytest

from cdmw.core.paloc_format import LocalizationEntry, PalocFormatError, encode_paloc, parse_paloc
from tools.translation_studio import catalogue
from tools.translation_studio.language_index import LanguageIndex


def path(language, table):
    return f"gamedata/stringtable/binary__/{language}/{table}.paloc"


def table(text):
    return encode_paloc((LocalizationEntry(category=1, key="shared", text=text, reserved=7),))


def test_split_edits_export_only_the_changed_source_with_its_own_footer():
    files = {path("eng", "bank"): table("Bank"), path("eng", "ui"): table("Menu")}
    cat = catalogue.load_catalogue(files, "eng")
    assert len(cat) == 2
    cat.set_text(1, "Edited menu")
    output = cat.changed_files()
    assert list(output) == [path("eng", "ui")]
    rebuilt = parse_paloc(output[path("eng", "ui")])
    assert len(rebuilt) == 1
    assert rebuilt.entries[0].text == "Edited menu"
    assert rebuilt.entries[0].reserved == 7
    assert cat.text_at(0) == "Bank"
    cat.set_text(0, "Edited bank")
    assert set(cat.changed_files()) == set(files)
    cat.reset()
    assert cat.changed_files() == {}
    assert cat.original == files


def test_duplicate_keys_in_different_tables_use_the_matching_reference_table():
    cat = catalogue.load_catalogue({path("eng", "bank"): table("Bank"), path("eng", "ui"): table("Menu")}, "eng")
    catalogue.attach_reference(cat, {path("kor", "bank"): table("Bank reference"), path("kor", "ui"): table("UI reference")}, "kor")
    assert cat.row(0).reference == "Bank reference"
    assert cat.row(1).reference == "UI reference"
    catalogue.attach_reference(cat, {path("kor", "ui"): table("UI only")}, "kor")
    assert cat.row(0).reference == ""
    assert cat.row(1).reference == "UI only"


def test_legacy_reference_and_export_paths_remain_compatible():
    game_path = catalogue.game_path_for("eng")
    cat = catalogue.load_catalogue({game_path: table("Original")}, "eng")
    catalogue.attach_reference(cat, {catalogue.game_path_for("kor"): table("Reference")}, "kor")
    assert cat.row(0).reference == "Reference"
    cat.set_text(0, "Edited")
    assert list(cat.changed_files()) == [game_path]


def test_mismatched_language_path_is_rejected():
    with pytest.raises(PalocFormatError):
        catalogue.load_catalogue({path("kor", "bank"): table("Text")}, "eng")


@pytest.fixture
def archive(monkeypatch, tmp_path):
    from cdmw.core import archive_format, archive_extraction

    pamt = tmp_path / "0019" / "0.pamt"
    selected = {path("eng", "bank"): pamt, path("eng", "ui"): pamt}
    index = LanguageIndex(root=str(tmp_path), languages=("eng",), tables={key: str(value) for key, value in selected.items()})
    entries = [SimpleNamespace(path=key) for key in selected]
    entries.append(SimpleNamespace(path=path("kor", "ui")))
    parsed, read = [], []
    monkeypatch.setattr(catalogue, "language_index", lambda root: index)

    def parse(source):
        parsed.append(source)
        return entries

    def payload(entry):
        read.append(entry.path)
        return table(entry.path), False, ""

    monkeypatch.setattr(archive_format, "parse_archive_pamt", parse)
    monkeypatch.setattr(archive_extraction, "read_archive_entry_data", payload)
    return tmp_path, selected, entries, parsed, read


def test_reader_loads_all_indexed_files_once_and_skips_other_languages(archive):
    root, selected, _entries, parsed, read = archive
    files = catalogue.read_language_tables("eng", root)
    assert set(files) == set(selected)
    assert len(parsed) == 1
    assert read == list(selected)


def test_reader_cancels_between_tables_without_returning_partial_data(archive):
    root, _selected, _entries, _parsed, read = archive
    with pytest.raises(InterruptedError):
        catalogue.read_language_tables("eng", root, is_cancelled=lambda: bool(read))
    assert len(read) == 1


def test_missing_indexed_table_fails_instead_of_loading_an_incomplete_language(archive):
    root, _selected, entries, _parsed, _read = archive
    del entries[1]
    with pytest.raises(PalocFormatError, match="changed during loading"):
        catalogue.read_language_tables("eng", root)


def test_worker_delivers_a_complete_split_catalogue(archive):
    from tools.translation_studio.tab import _LoadWorker

    root, selected, _entries, _parsed, _read = archive
    results = []
    worker = _LoadWorker("eng", "", str(root))
    worker.done.connect(lambda cat, error: results.append((cat, error)))
    worker.run()
    cat, error = results[0]
    assert not error
    assert len(cat) == 2
    assert set(cat.source_ranges) == set(selected)
