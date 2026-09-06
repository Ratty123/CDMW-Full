"""Source generations, Arabic exports, authoritative bases and stale publication."""
from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.item_sources import resolve_item_data_sources
from cdmw.core.paloc_format import parse_paloc
from cdmw.core.storeinfo_table import encode_store_row, parse_store_table
from cdmw.core.iteminfo_row import parse_iteminfo_row, rebuild_stat_block
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.spec import NewItemSpec
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_mod_base import build_mod_base_snapshot, mod_folder_payloads
from cdmw.services.new_item_provenance import StaleNewItemSource
from tests.test_new_item_service import synthetic_files, build_package, _read, TEMPLATE, BIN, MC_ROW_0, MC_ROW_1
from tests.test_storeinfo_table import _table


def current_files():
    original = synthetic_files()
    body = original[f"{BIN}/iteminfo.pabgb"]
    head = original[f"{BIN}/iteminfo.pabgh"]
    chunks = []
    for _row, start, end in parse_pabgh_table(head, payload=body).row_spans(len(body)):
        item = parse_iteminfo_row(body[start:end])
        chunks.append(rebuild_stat_block(replace(item, stat_block_marker=0x12)) if item.stat_block_offset is not None else item.raw)
    original[f"{BIN}/iteminfo.pabgb"] = b"".join(chunks)
    stores = parse_store_table(original[f"{BIN}/storeinfo.pabgb"], original[f"{BIN}/storeinfo.pabgh"])
    raw = [encode_store_row(replace(s, layout="current", prefix=s.prefix + b"\0",
              entries=tuple(replace(e, condition_data=b"\0" * 8) for e in s.entries))) for s in stores]
    original[f"{BIN}/storeinfo.pabgb"], original[f"{BIN}/storeinfo.pabgh"] = _table(raw)
    files = {}
    for path, data in original.items():
        if path.startswith(BIN + "/"):
            path = path.replace(BIN, "gamedata/binarystaticinfo__/bin").replace(".pabgb", ".staticinfobody").replace(".pabgh", ".staticinfoheader")
        if "localizationstring_" in path:
            language = path.rsplit("_", 1)[1][:-6]
            path = f"gamedata/stringtable/binary__/{language}/item.paloc"
        files[path] = data
    files["gamedata/stringtable/binary__/ara/item.paloc"] = files["gamedata/stringtable/binary__/eng/item.paloc"]
    from tests.new_item_current_fixture_tables import current_recipe_tables
    files.update(current_recipe_tables(TEMPLATE, (MC_ROW_0, MC_ROW_1)))
    return files


def setup_game(root, current=True):
    pamt = build_package(root / "game", current_files() if current else synthetic_files())
    entries = parse_archive_pamt(pamt)
    service = NewItemService()
    return service, service.build_snapshot(entries, read_entry=_read), entries


def spec(name="First"):
    return NewItemSpec(template_key=TEMPLATE, internal_name=name, display_names={"eng": name, "ara": "سيف جديد"})


def test_current_generation_and_arabic_export(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    plan = service.plan(spec(), snapshot)
    assert plan.manifest["generation"] == "current"
    assert plan.manifest["tables"]["iteminfo"]["payload_sha256"]
    for language in ("eng", "ara", "ger"):
        table = parse_paloc(plan.loose_files[f"gamedata/stringtable/binary__/{language}/item.paloc"])
        assert table.index()[plan.spec.name_key].text == ("سيف جديد" if language == "ara" else "First")
    service.export_loose(plan, tmp_path / "output", manager="JMM")
    assert json.loads((tmp_path / "output/new-item.json").read_text(encoding="utf-8"))["item_key"] == plan.spec.item_key


def test_incomplete_current_pair_cannot_fall_back_to_legacy(tmp_path):
    _, _, entries = setup_game(tmp_path, current=False)
    partial = replace(entries[0], path="gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody")
    with pytest.raises(ValueError, match="Incomplete iteminfo"):
        resolve_item_data_sources([*entries, partial])


def test_unreadable_archive_index_cannot_expose_older_tables(tmp_path, monkeypatch):
    from cdmw.workers.new_item_workers import list_archive_entries
    import cdmw.core.archive_format as archive_format
    _,_,legacy = setup_game(tmp_path, current=False)
    damaged = tmp_path / "game" / "0008" / "0.pamt"
    damaged.parent.mkdir(parents=True, exist_ok=True)
    damaged.write_bytes(b"invalid current archive directory")
    monkeypatch.setattr(archive_format,"discover_pamt_files",lambda root:[damaged,legacy[0].pamt_path])
    with pytest.raises(ValueError,match="0008.*complete source catalogue"):
        list_archive_entries(tmp_path/"game",lambda message:None,None)


def test_legacy_mod_is_reported_and_preserved(tmp_path):
    service, snapshot, _ = setup_game(tmp_path / "current")
    older, old_snapshot, _ = setup_game(tmp_path / "legacy", current=False)
    old_plan = older.plan(NewItemSpec(template_key=TEMPLATE, internal_name="Old_Custom", display_names={"eng": "Old"}), old_snapshot)
    folder = tmp_path / "old-mod"
    older.export_loose(old_plan, folder, manager="JMM")
    before = {p: f.read_bytes() for p, f in mod_folder_payloads(folder).items()}
    with pytest.raises(ValueError, match="Incompatible.*Old_Custom"):
        build_mod_base_snapshot(service, snapshot, folder, read_entry=_read)
    assert before == {p: f.read_bytes() for p, f in mod_folder_payloads(folder).items()}


def test_second_item_carries_extra_assets_and_records_to_different_folder(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    first = service.plan(spec(), snapshot)
    source = tmp_path / "first"
    service.export_loose(first, source, manager="JMM")
    extra = source / "character/model/prior-owned.pac"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b"synthetic owned asset")
    base = build_mod_base_snapshot(service, snapshot, source, read_entry=_read)
    second = service.plan(spec("Second"), base)
    assert first.spec.item_key in base.rows
    assert second.spec.item_key != first.spec.item_key
    assert second.loose_files["character/model/prior-owned.pac"] == extra.read_bytes()
    assert any(a.path == "character/model/prior-owned.pac" for a in second.additions)
    assert second.manifest["previous_items"][0]["item_key"] == first.spec.item_key
    service.export_loose(second, tmp_path / "combined", manager="JMM")
    assert (tmp_path / "combined/character/model/prior-owned.pac").read_bytes() == extra.read_bytes()
    extra.write_bytes(b"changed after plan")
    with pytest.raises(StaleNewItemSource, match="Source changed"):
        service.export_loose(second, tmp_path / "stale", manager="JMM")
    assert not (tmp_path / "stale").exists()


def test_changed_archive_and_in_memory_reader_reject_stale_plan(tmp_path):
    service, snapshot, entries = setup_game(tmp_path)
    plan = service.plan(spec(), snapshot)
    archive = Path(entries[0].paz_file)
    with archive.open("ab") as file:
        file.write(b"changed")
    with pytest.raises(StaleNewItemSource, match="Source changed"):
        service.export_loose(plan, tmp_path / "stale", manager="JMM")
