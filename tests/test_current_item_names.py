"""Current game metadata joins, using owned archives and the real readers."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.item_index import (
    _friendly_internal_item_name, build_archive_item_search_index,
    _collect_archive_item_index_sources, _try_build_archive_item_search_index_native,
)
from cdmw.core.item_sources import resolve_item_data_sources, STATIC_TABLE_ROOT
from cdmw.core.paloc_format import LocalizationEntry, encode_paloc
from cdmw.core.papgt_format import PapgtDirectory, serialize_papgt
from cdmw.domain.archives.item_names import compact_item_name
from cdmw.domain.new_item.spec import NewItemSpec
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_snapshot import build_snapshot
from cdmw.ui.new_item.controller import NewItemStudioController
from test_new_item_service import (
    BIN, LOC, NAME_KEY, DESC_KEY, TEMPLATE, STEM, PAC, synthetic_files, build_package, _read,
)


def current_files():
    files = {}
    for path, payload in synthetic_files().items():
        if path.startswith(BIN + "/"):
            path = path.replace(BIN, STATIC_TABLE_ROOT).replace(".pabgb", ".staticinfobody").replace(".pabgh", ".staticinfoheader")
        elif "localizationstring_" in path:
            language = path.rsplit("_", 1)[1].removesuffix(".paloc")
            path = f"{LOC}/{language}/item.paloc"
        files[path] = payload
    # A non-item domain must never replace the item's name.
    files[f"{LOC}/eng/quest.paloc"] = encode_paloc([LocalizationEntry(7, NAME_KEY, "Wrong domain")])
    files[f"{LOC}/ara/item.paloc"] = encode_paloc([
        LocalizationEntry(7, NAME_KEY, "سيف الاختبار"), LocalizationEntry(7, DESC_KEY, "سيف"),
    ])
    return files


@pytest.fixture
def current_entries(tmp_path):
    return parse_archive_pamt(build_package(tmp_path, current_files()))


def test_current_snapshot_and_template_search_share_all_languages(current_entries):
    snapshot = build_snapshot(current_entries, read_entry=_read)
    assert snapshot.item_display_names()[TEMPLATE] == "Wolf's Fang"
    assert snapshot.languages == ("ara", "eng", "ger")
    controller = SimpleNamespace(snapshot=snapshot)
    for query in ("Wolf's Fang", "Wolfszahn", "سيف الاختبار", str(TEMPLATE)):
        rows = NewItemStudioController.template_options(controller, query, limit=None)
        assert [row[0] for row in rows] == [TEMPLATE]
        assert rows[0][2] == "Wolf's Fang"


def test_current_plan_keeps_current_table_and_localization_paths(current_entries):
    snapshot = build_snapshot(current_entries, read_entry=_read)
    spec = NewItemSpec(template_key=TEMPLATE, internal_name="Current_Clone_OneHandSword",
                       display_names={"eng": "Current Clone"})
    plan = NewItemService().plan(spec, snapshot)
    paths = {patch.entry.path for patch in plan.patches}
    assert f"{STATIC_TABLE_ROOT}/iteminfo.staticinfobody" in paths
    assert f"{STATIC_TABLE_ROOT}/iteminfo.staticinfoheader" in paths
    assert f"{LOC}/eng/item.paloc" in paths
    assert not any(".pabg" in path or "localizationstring_" in path for path in paths)


@pytest.mark.parametrize("native", [False, True])
def test_current_index_resolves_prefabs_and_retains_items_without_models(current_entries, monkeypatch, native):
    if native:
        sources = _collect_archive_item_index_sources(current_entries)
        index = _try_build_archive_item_search_index_native(current_entries, sources)
        assert index is not None, "the rebuilt native item index must satisfy the current contract"
        from cdmw.core.item_prefab_names import enrich_prefab_names
        index = enrich_prefab_names(index, sources.model_entries)
    else:
        monkeypatch.setenv("CDMW_DISABLE_NATIVE_ITEM_INDEX", "1")
        index = build_archive_item_search_index(current_entries)
    assert len(index.items) == 8
    item = next(item for item in index.items if item.item_id == TEMPLATE)
    assert item.display_name == "Wolf's Fang"
    assert "Wolfszahn" in item.localized_names and "سيف الاختبار" in item.localized_names
    assert item.equip_type == "OneHandSword"
    assert PAC in item.pac_files
    archived_pacs = {Path(entry.path).name.lower() for entry in current_entries if entry.path.endswith(".pac")}
    assert all(Path(path).name.lower() in archived_pacs for path in item.pac_files)
    assert index.model_base_exact_display_names[STEM] == "Wolf's Fang"
    assert any(item.item_id == 11 for item in index.items), "name-only records are still findable"


@pytest.mark.parametrize("native", [False, True])
def test_missing_english_is_not_promoted_from_another_language(tmp_path, monkeypatch, native):
    files = current_files()
    files[f"{LOC}/eng/item.paloc"] = encode_paloc([LocalizationEntry(7, "99999999", "Other")])
    entries = parse_archive_pamt(build_package(tmp_path, files))
    snapshot = build_snapshot(entries, read_entry=_read)
    assert not snapshot.item_display_names().get(TEMPLATE)
    monkeypatch.setenv("CDMW_DISABLE_NATIVE_ITEM_INDEX", "0" if native else "1")
    index = build_archive_item_search_index(entries)
    item = next(item for item in index.items if item.item_id == TEMPLATE)
    assert item.display_name == ""
    assert "Wolfszahn" in item.localized_names
    assert STEM not in index.model_base_exact_display_names


def test_legacy_overlay_cannot_replace_current_tables_or_names(current_entries):
    legacy = [replace(entry, path=entry.path.replace(STATIC_TABLE_ROOT, BIN)
                      .replace(".staticinfobody", ".pabgb").replace(".staticinfoheader", ".pabgh"),
                      pamt_path=entry.pamt_path.parent.parent / "0036" / "0.pamt")
              for entry in current_entries if entry.path.startswith(STATIC_TABLE_ROOT)]
    mount_path = current_entries[0].pamt_path.parent.parent / "meta" / "0.papgt"
    mount_path.write_bytes(serialize_papgt([PapgtDirectory(name, 0x7FFF00, 0) for name in ("0036", "0009")]))
    sources = resolve_item_data_sources([*legacy, *current_entries])
    assert sources.tables["iteminfo"][0] in current_entries
    assert all(not sources.accepts(entry) for entry in legacy)


def test_mount_order_wins_over_numeric_package_order(tmp_path):
    entries = parse_archive_pamt(build_package(tmp_path, current_files()))
    overlay = [replace(entry, pamt_path=tmp_path / "0036" / "0.pamt") for entry in entries]
    newer = [replace(entry, pamt_path=tmp_path / "0037" / "0.pamt") for entry in entries]
    mounts = [PapgtDirectory(name, 0x7FFF00, 0) for name in ("0036", "0037", "0009")]
    (tmp_path / "meta" / "0.papgt").write_bytes(serialize_papgt(mounts))
    sources = resolve_item_data_sources([*entries, *newer, *overlay])
    assert sources.tables["iteminfo"][0].pamt_path.parent.name == "0036"
    assert sources.localizations["eng"].pamt_path.parent.name == "0036"
    broken = [entry for entry in overlay if not entry.path.endswith("iteminfo.staticinfoheader")]
    with pytest.raises(ValueError, match="Incomplete iteminfo"):
        resolve_item_data_sources([*entries, *newer, *broken])


def test_pairs_cannot_mix_pamt_files_in_one_package(current_entries):
    entries = [replace(entry, pamt_path=entry.pamt_path.with_name("1.pamt"))
               if entry.path.endswith("iteminfo.staticinfoheader") else entry for entry in current_entries]
    with pytest.raises(ValueError, match="Incomplete iteminfo"):
        resolve_item_data_sources(entries)


def test_name_cache_detects_mount_changes_even_with_unchanged_entry_metadata(current_entries, tmp_path):
    from cdmw.core.archive_index_cache import save_archive_derived_index_cache, load_archive_derived_index_cache
    cache = tmp_path / "cache"
    metadata = "a" * 64
    save_archive_derived_index_cache(tmp_path, cache, current_entries, entry_metadata_signature=metadata, entry_metadata_sources=())
    assert load_archive_derived_index_cache(tmp_path, cache, current_entries, entry_metadata_signature=metadata) is not None
    (tmp_path / "meta" / "0.papgt").write_bytes(serialize_papgt([PapgtDirectory("0036", 0x7FFF00, 0)]))
    assert load_archive_derived_index_cache(tmp_path, cache, current_entries, entry_metadata_signature=metadata) is None


def test_shared_name_label_counts_distinct_names_and_friendly_case_is_preserved():
    assert compact_item_name("Blade / Long Blade / Blade") == "Shared asset (2 names)"
    assert compact_item_name("Blade") == "Blade"
    assert _friendly_internal_item_name("LightSaber_TwoHandSword") == "Light Saber Two Hand Sword"
