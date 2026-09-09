"""Folder composition uses real exported payloads and never touches its sources."""
from dataclasses import replace
import hashlib
import json
import threading

import pytest

from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.paloc_format import parse_paloc
from cdmw.core.pathc_format import PathcTable, encode_pathc, parse_pathc, register_dds
from cdmw.core.storeinfo_table import parse_store_table
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.spec import Placement, PlacementKind, UNLIMITED_STOCK
from cdmw.services.mod_merge_service import export_merged_mod, prepare_mod_merge
from cdmw.services.new_item_mod_base import build_mod_base_snapshot, mod_folder_payloads
from tests.test_new_item_provenance import setup_game, spec
from tests.new_item_service_write_tests import _fake_dds


def fingerprint(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def make_mods(tmp_path, *, current=True, shop=False, same_key=False):
    service, snapshot, entries = setup_game(tmp_path, current=current)
    plans, folders = [], []
    for index, manager in enumerate(("JMM", "DMM")):
        item = replace(spec("First" if index == 0 else "Second"),
                       item_key=1990000 + (0 if same_key else index * 100), recipes=() if current else None)
        if shop:
            item = replace(item, placement=Placement(PlacementKind.INSERT, "Store_Camp_Equipment", stock_count=UNLIMITED_STOCK))
        plan = service.plan(item, snapshot)
        folder = tmp_path / item.internal_name
        service.export_loose(plan, folder, manager=manager)
        plans.append(plan)
        folders.append(folder)
    return service, snapshot, entries, plans, folders


def payloads(folder):
    return {path: value.read_bytes() for path, value in mod_folder_payloads(folder).items()}


@pytest.mark.parametrize("current", (False, True))
def test_independent_item_mods_merge_into_readable_dmm(tmp_path, current):
    service, snapshot, entries, plans, folders = make_mods(tmp_path, current=current, shop=True)
    original = {root: fingerprint(root) for root in [tmp_path / "game", *folders]}
    plan = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    assert not plan.conflicts, plan.conflicts
    result = export_merged_mod(plan, tmp_path / "combined")
    files = payloads(result.package_root)
    body_path, head_path = snapshot.iteminfo.payload_entry.path, snapshot.iteminfo.header_entry.path
    rows = {row.row_id: parse_iteminfo_row(files[body_path][start:end]).string_key
            for row, start, end in parse_pabgh_table(files[head_path], payload=files[body_path]).row_spans(len(files[body_path]))}
    for item in plans:
        assert rows[item.spec.item_key] == item.spec.internal_name
        language_path = snapshot.paloc_entries["eng"].path
        assert parse_paloc(files[language_path]).index()[item.spec.name_key].text == item.spec.internal_name
    shops = parse_store_table(files[snapshot.storeinfo.payload_entry.path], files[snapshot.storeinfo.header_entry.path],
                              layout="current" if current else "legacy")
    camp = next(shop for shop in shops if shop.name == "Store_Camp_Equipment")
    assert all(camp.entries_for(item.spec.item_key) for item in plans)
    assert len({entry.order_index for entry in camp.entries}) == len(camp.entries)
    for root, before in original.items():
        assert fingerprint(root) == before
    combined = build_mod_base_snapshot(service, snapshot, result.package_root, read_entry=snapshot.provenance.reader)
    third = service.plan(replace(spec("Third"), item_key=1990300), combined)
    assert all(str(item.spec.item_key) in {str(row.row_id) for row, _, _ in
        parse_pabgh_table(third.loose_files[head_path], payload=third.loose_files[body_path]).row_spans(len(third.loose_files[body_path]))}
        for item in plans)


def test_duplicate_item_identity_blocks_export_and_names_the_record(tmp_path):
    _service, _snapshot, entries, _plans, folders = make_mods(tmp_path, same_key=True)
    plan = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    assert any("1990000" in issue and "Second" in issue for issue in plan.conflicts), plan.conflicts
    with pytest.raises(ValueError, match="reported conflicts"):
        export_merged_mod(plan, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()


def test_colliding_generated_recipe_ids_require_resolution(tmp_path):
    service, snapshot, entries, _plans, folders = make_mods(tmp_path)
    for index, folder in enumerate(folders):
        plan = service.plan(replace(spec(folder.name), item_key=1990000 + index * 100), snapshot)
        service.export_loose(plan, folder, manager="JMM" if index == 0 else "DMM")
    merged = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    assert any("multichangeinfo" in issue and "1990000" in issue for issue in merged.conflicts)


def test_selected_parent_mod_supplies_a_recorded_baseline_in_either_order(tmp_path):
    service, snapshot, entries, plans, folders = make_mods(tmp_path)
    inherited = build_mod_base_snapshot(service, snapshot, folders[0], read_entry=snapshot.provenance.reader)
    dependent = service.plan(replace(spec("Dependent"), item_key=1990200), inherited)
    folder = tmp_path / "dependent"
    service.export_loose(dependent, folder, manager="DMM")
    for chosen in ((folders[0], folder), (folder, folders[0])):
        plan = prepare_mod_merge(chosen, tmp_path / "game", entries=entries)
        assert not plan.conflicts, plan.conflicts
        data = {path: data for path, data, _ in plan.files}
        body, head = snapshot.iteminfo.payload_entry.path, snapshot.iteminfo.header_entry.path
        keys = {row.row_id for row, _, _ in parse_pabgh_table(data[head], payload=data[body]).row_spans(len(data[body]))}
        assert {plans[0].spec.item_key, dependent.spec.item_key} <= keys


def test_missing_or_wrong_recorded_baseline_is_reported(tmp_path):
    _service, _snapshot, entries, _plans, folders = make_mods(tmp_path)
    manifest_path = folders[0] / "new-item.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for digest in (None, "a" * 64):
        edited = dict(manifest, sources=[] if digest is None else [dict(row, sha256=digest) for row in manifest["sources"]])
        manifest_path.write_text(json.dumps(edited))
        plan = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
        assert any("baseline" in issue for issue in plan.conflicts), plan.conflicts


def texture_mod(folder, path, registry):
    folder.mkdir()
    dds = _fake_dds(4, 4)
    target = folder / path
    target.parent.mkdir(parents=True)
    target.write_bytes(dds)
    (folder / "meta").mkdir()
    (folder / "meta/0.pathc").write_bytes(encode_pathc(register_dds(registry, path, dds)))
    (folder / "new-item.json").write_text(json.dumps({"texture_registry": [path]}))


def test_texture_registrations_are_combined_and_sources_preserved(tmp_path):
    _service, _snapshot, entries = setup_game(tmp_path)
    registry = PathcTable(0, 148, (), (), (), b"")
    (tmp_path / "game/meta/0.pathc").write_bytes(encode_pathc(registry))
    paths = ("character/texture/first.dds", "character/texture/second.dds")
    folders = [tmp_path / "first", tmp_path / "second"]
    for folder, path in zip(folders, paths):
        texture_mod(folder, path, registry)
    originals = {folder: fingerprint(folder) for folder in [tmp_path / "game", *folders]}
    plan = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    assert not plan.conflicts, plan.conflicts
    result = export_merged_mod(plan, tmp_path / "combined")
    files = payloads(result.package_root)
    output_registry = parse_pathc(files["meta/0.pathc"])
    assert all(output_registry.find(path) is not None and files[path] == _fake_dds(4, 4) for path in paths)
    assert all(fingerprint(folder) == before for folder, before in originals.items())


def test_changed_input_and_unsafe_destination_cannot_publish(tmp_path):
    _service, _snapshot, entries, _plans, folders = make_mods(tmp_path)
    plan = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    assert not plan.conflicts, plan.conflicts
    for destination in (folders[0], folders[0] / "child", tmp_path, tmp_path / "game/merged"):
        with pytest.raises(ValueError, match="separate"):
            export_merged_mod(plan, destination)
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="new or empty"):
        export_merged_mod(plan, existing)
    (folders[0] / "new-file.txt").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        export_merged_mod(plan, tmp_path / "result")
    assert not (tmp_path / "result").exists()
    assert (existing / "keep.txt").read_text() == "keep"


def test_cancellation_after_archive_preparation_leaves_no_partial_package(tmp_path, monkeypatch):
    from cdmw.services import archive_overlay_package_service as writer
    _service, _snapshot, entries, _plans, folders = make_mods(tmp_path)
    plan = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    stop = threading.Event()
    original = writer.export_archive_overlay_package
    def cancel_after(*args, **kwargs):
        value = original(*args, **kwargs)
        stop.set()
        return value
    monkeypatch.setattr(writer, "export_archive_overlay_package", cancel_after)
    with pytest.raises(RunCancelled):
        export_merged_mod(plan, tmp_path / "result", stop_event=stop)
    assert not (tmp_path / "result").exists()
    assert not list(tmp_path.glob(".result.cdmw-stage-*"))


def test_input_change_during_export_keeps_destination_empty(tmp_path, monkeypatch):
    from cdmw.services import archive_overlay_package_service as writer
    _service, _snapshot, entries, _plans, folders = make_mods(tmp_path)
    plan = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    destination = tmp_path / "result"
    destination.mkdir()
    original = writer.export_archive_overlay_package
    def change_after(*args, **kwargs):
        value = original(*args, **kwargs)
        (folders[0] / "new-item.json").write_text("{}")
        return value
    monkeypatch.setattr(writer, "export_archive_overlay_package", change_after)
    with pytest.raises(ValueError, match="changed"):
        export_merged_mod(plan, destination)
    assert list(destination.iterdir()) == []
    assert not list(tmp_path.glob(".result.cdmw-stage-*"))


def test_unknown_file_conflicts_and_incomplete_tables_are_reported(tmp_path):
    _service, snapshot, entries, _plans, folders = make_mods(tmp_path)
    for index, folder in enumerate(folders):
        (folder / "character").mkdir(exist_ok=True)
        (folder / "character/shared.pac").write_bytes(bytes([index]))
    (folders[0] / snapshot.iteminfo.header_entry.path).unlink()
    plan = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    assert any("incomplete table pair" in issue for issue in plan.conflicts)
    assert any("character/shared.pac" in issue for issue in plan.conflicts)


@pytest.mark.parametrize("damage", ("undeclared", "wrong_dds", "removed"))
def test_unproven_texture_registry_changes_are_refused(tmp_path, damage):
    _service, _snapshot, entries = setup_game(tmp_path)
    baseline = register_dds(PathcTable(0, 148, (), (), (), b""), "character/texture/original.dds", _fake_dds(4, 4))
    (tmp_path / "game/meta/0.pathc").write_bytes(encode_pathc(baseline))
    folders = [tmp_path / "first", tmp_path / "second"]
    paths = [f"character/texture/{name}.dds" for name in ("first", "second")]
    for folder, path in zip(folders, paths):
        texture_mod(folder, path, baseline)
    if damage == "undeclared":
        registry = parse_pathc((folders[0] / "meta/0.pathc").read_bytes())
        registry = register_dds(registry, "character/texture/undeclared.dds", _fake_dds(4, 4))
        (folders[0] / "meta/0.pathc").write_bytes(encode_pathc(registry))
    elif damage == "wrong_dds":
        (folders[0] / paths[0]).write_bytes(_fake_dds(8, 8))
    else:
        registry = register_dds(PathcTable(0, 148, (), (), (), b""), paths[0], _fake_dds(4, 4))
        (folders[0] / "meta/0.pathc").write_bytes(encode_pathc(registry))
    plan = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    assert any("meta/0.pathc" in issue for issue in plan.conflicts), plan.conflicts
