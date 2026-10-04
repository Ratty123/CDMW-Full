"""Complete mounted-item packages, source preservation and Output wiring."""
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil
import struct
import threading
from unittest.mock import patch

import pytest

from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt
from cdmw.core.mod_compatibility import read_compatibility
from cdmw.core.papgt_format import papgt_with_directory
from cdmw.core.pathc_format import PathcTable, encode_pathc, parse_pathc
from cdmw.domain.new_item.spec import ModelSource
from cdmw.services.new_item_mod_base import mod_folder_payloads
from cdmw.services.new_item_mounted_base import prepare_mounted_item_base
from cdmw.services.new_item_planning import ModelFiles
from cdmw.services.new_item_provenance import StaleNewItemSource
from cdmw.workers.new_item_workers import plan_task
from tests.test_new_item_provenance import setup_game, spec
from tests.test_new_item_service import PAC, STEM, _fake_dds, _read, build_package


def fingerprints(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def mount_export(service, plan, root, folder, group="0036"):
    service.export_loose(plan, folder, manager="DMM", replace_existing=False)
    shutil.copytree(folder / "0036", root / group)
    pamt = root / group / "0.pamt"
    mount = root / "meta/0.papgt"
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), group, struct.unpack_from("<I", pamt.read_bytes())[0]))
    for meta in plan.meta_files:
        (root / meta.path).write_bytes(meta.payload_data)
    entries = [entry for path in discover_pamt_files(root) for entry in parse_archive_pamt(path)]
    return service.build_snapshot(entries, read_entry=_read)


def mounted_game(tmp_path, current=True):
    service, clean, _ = setup_game(tmp_path, current=current)
    root = tmp_path / "game"
    (root / "meta/0.pathc").write_bytes(encode_pathc(PathcTable(0, 148, (), (), (), b"")))
    clean = service.build_snapshot(parse_archive_pamt(root / "0009/0.pamt"), read_entry=_read)
    model = ModelFiles(pac_data=clean.payload(PAC),
                       side_files={f"character/texture/1_pc/{STEM}_d.dds": _fake_dds(4, 4) + bytes(16)})
    first = service.plan(replace(spec("Existing_Sword"), model_source=ModelSource.IMPORTED), clean, model=model)
    mounted = mount_export(service, first, root, tmp_path / "original")
    return service, clean, first, mounted, root


@pytest.mark.parametrize("manager", ["DMM", "CDUMM", "JMM"])
@pytest.mark.parametrize("current", [True, False])
def test_mounted_export_keeps_tables_assets_registry_and_clean_baselines(tmp_path, manager, current):
    service, clean, first, mounted, root = mounted_game(tmp_path, current)
    before = fingerprints(root)
    original = fingerprints(tmp_path / "original")
    plan = plan_task(spec("New_Sword"), mounted, service=service, include_mounted_items=True)(lambda _: None, None)
    assert not plan.unselected_source_items
    assert not mounted.base_payloads, "Planning must not turn the workspace snapshot into a composed base"
    assert plan.manifest["mounted_base"]["archives"] == ["0036"]
    assert plan.manifest["mounted_base"]["items"][0]["item_key"] == first.spec.item_key
    destination = tmp_path / "combined"
    result = service.export_loose(plan, destination, manager=manager, replace_existing=False, create_zip=True)
    payloads = mod_folder_payloads(destination)
    for path in first.new_paths:
        assert payloads[path].read_bytes() == first.loose_files[path]
    from cdmw.services.new_item_mounted_base import _item_rows
    table = plan.manifest["tables"]["iteminfo"]
    keys = _item_rows(payloads[table["payload_path"]].read_bytes(), payloads[table["header_path"]].read_bytes())
    assert first.spec.item_key in keys and plan.spec.item_key in keys
    registry = parse_pathc(next(meta.payload_data for meta in plan.meta_files if meta.path == "meta/0.pathc"))
    for path in first.new_paths:
        if path.endswith(".dds"):
            assert registry.find(path) is not None
            assert path in plan.manifest["texture_registry"]
    compatibility = read_compatibility(destination)
    assert compatibility.originals[table["payload_path"]] == clean.iteminfo.payload
    assert all(compatibility.originals[path] is None for path in first.new_paths)
    assert "meta/0.pathc" not in compatibility.originals
    assert result.zip_path.is_file()
    instructions = (destination / "README.txt").read_text(encoding="utf-8")
    assert "Existing_Sword" in instructions and "0036" in instructions
    assert "disable" in instructions and "re-enable the originals" in instructions
    assert fingerprints(root) == before
    assert fingerprints(tmp_path / "original") == original


def test_changed_mount_or_archive_blocks_export_before_publication(tmp_path):
    service, _clean, _first, mounted, root = mounted_game(tmp_path)
    plan = plan_task(spec("Second"), mounted, service=service, include_mounted_items=True)(lambda _: None, None)
    with (root / "0036/0.paz").open("ab") as stream:
        stream.write(b"changed after planning")
    with pytest.raises(StaleNewItemSource, match="Source changed"):
        service.export_loose(plan, tmp_path / "stale", replace_existing=False, create_zip=True)
    assert not (tmp_path / "stale").exists() and not (tmp_path / "stale.zip").exists()


def test_mount_list_controls_inclusion_and_archive_number_is_not_fixed(tmp_path):
    from cdmw.core.papgt_format import parse_papgt, serialize_papgt
    service, _clean, first, _mounted, root = mounted_game(tmp_path)
    shutil.copytree(root / "0036", root / "0045")
    mount = root / "meta/0.papgt"
    mount.write_bytes(serialize_papgt(tuple(replace(row, name="0045") if row.name == "0036" else row
                                          for row in parse_papgt(mount.read_bytes()))))
    entries = [entry for pamt in discover_pamt_files(root) for entry in parse_archive_pamt(pamt)]
    mounted = service.build_snapshot(entries, read_entry=_read)
    plan = plan_task(spec("Second"), mounted, service=service, include_mounted_items=True)(lambda _: None, None)
    assert plan.manifest["mounted_base"]["archives"] == ["0045"]
    assert (root / "0036").is_dir(), "The unmounted original is intentionally still on disk"
    for path in first.new_paths:
        assert plan.loose_files[path] == first.loose_files[path]


def test_cancellation_keeps_the_source_and_workspace_snapshot(tmp_path):
    service, _clean, _first, mounted, root = mounted_game(tmp_path)
    before = fingerprints(root)
    stop = threading.Event()
    def cancel(message):
        if message.startswith("Collecting mounted file"):
            stop.set()
    from cdmw.domain.cancellation import RunCancelled
    with pytest.raises(RunCancelled):
        plan_task(spec("Second"), mounted, service=service, include_mounted_items=True)(cancel, stop)
    assert not mounted.base_payloads
    assert fingerprints(root) == before


def test_hidden_item_from_another_mounted_table_is_reported(tmp_path):
    service, clean, _first, _mounted, root = mounted_game(tmp_path)
    clean = service.build_snapshot(parse_archive_pamt(root / "0009/0.pamt"), read_entry=_read)
    other = service.plan(replace(spec("Other_Sword"), item_key=1990050), clean)
    mounted = mount_export(service, other, root, tmp_path / "other", "0037")
    with pytest.raises(ValueError, match="already conflict: Existing_Sword.*0036"):
        prepare_mounted_item_base(service, mounted, read_entry=_read)


def test_modified_shipped_archives_are_not_mistaken_for_a_complete_mod(tmp_path):
    service, _clean, first, _mounted, _root = mounted_game(tmp_path)
    files = {entry.path: _read(entry) for entry in _clean.entries.values()}
    files.update(first.loose_files)
    contaminated_pamt = build_package(tmp_path / "modified-game", files)
    # No separate overlay exists, even though the ItemInfo table carries an added item.
    contaminated = service.build_snapshot(parse_archive_pamt(contaminated_pamt), read_entry=_read)
    with pytest.raises(ValueError, match="No separate mounted overlay archives"):
        prepare_mounted_item_base(service, contaminated, read_entry=_read)


def test_output_cannot_overwrite_the_game_or_an_existing_package(tmp_path):
    service, _clean, _first, mounted, root = mounted_game(tmp_path)
    plan = plan_task(spec("Second"), mounted, service=service, include_mounted_items=True)(lambda _: None, None)
    with pytest.raises(ValueError, match="outside the game"):
        service.export_loose(plan, root / "combined", replace_existing=False)
    with pytest.raises(ValueError, match="new folder"):
        service.export_loose(plan, tmp_path / "original")


def test_recovered_package_can_be_extended_and_merged_with_another_mod(tmp_path):
    from cdmw.services.mod_merge_service import prepare_mod_merge, export_merged_mod
    from cdmw.services.new_item_mod_base import build_mod_base_snapshot
    from cdmw.services.new_item_mounted_base import _item_rows

    service, _clean, first, mounted, _root = mounted_game(tmp_path / "installed")
    combined = plan_task(spec("Second"), mounted, service=service, include_mounted_items=True)(lambda _: None, None)
    folder = tmp_path / "combined"
    service.export_loose(combined, folder, manager="DMM", replace_existing=False)
    # An independent clean install proves the new package does not require the
    # mounted original to supply its baseline or dependencies.
    _other_service, clean, entries = setup_game(tmp_path / "clean")
    clean_root = tmp_path / "clean/game"
    (clean_root / "meta/0.pathc").write_bytes(encode_pathc(PathcTable(0, 148, (), (), (), b"")))
    clean = service.build_snapshot(entries, read_entry=_read)
    extended_base = build_mod_base_snapshot(service, clean, folder, read_entry=_read)
    extended = service.plan(spec("Third"), extended_base)
    assert {first.spec.item_key, combined.spec.item_key} <= extended_base.rows.keys()
    service.export_loose(extended, tmp_path / "extended", manager="JMM", replace_existing=False)

    separate = service.plan(replace(spec("Independent"), item_key=1990080, recipes=()), clean)
    other = tmp_path / "other"
    service.export_loose(separate, other, manager="DMM", replace_existing=False)
    merged = prepare_mod_merge((folder, other), clean_root, entries=entries, read_entry=_read)
    assert not merged.conflicts, merged.conflicts
    result = export_merged_mod(merged, tmp_path / "merged-again")
    payloads = mod_folder_payloads(result.package_root)
    table = combined.manifest["tables"]["iteminfo"]
    keys = _item_rows(payloads[table["payload_path"]].read_bytes(), payloads[table["header_path"]].read_bytes())
    assert {first.spec.item_key, combined.spec.item_key, separate.spec.item_key} <= keys.keys()
    for path in first.new_paths:
        assert payloads[path].read_bytes() == first.loose_files[path]


def test_missing_mounted_mesh_blocks_the_plan(tmp_path):
    service, _clean, first, _mounted, root = mounted_game(tmp_path)
    files = dict(first.loose_files)
    missing = next(path for path in first.new_paths if path.endswith(".pac"))
    del files[missing]
    rebuilt = build_package(tmp_path / "incomplete", files)
    for name in ("0.pamt", "0.paz", "1.paz"):
        shutil.copyfile(rebuilt.parent / name, root / "0036" / name)
    mount = root / "meta/0.papgt"
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), "0036", struct.unpack_from("<I", rebuilt.read_bytes())[0]))
    entries = [entry for pamt in discover_pamt_files(root) for entry in parse_archive_pamt(pamt)]
    mounted = service.build_snapshot(entries, read_entry=_read)
    with pytest.raises(ValueError, match="missing required assets"):
        plan_task(spec("Second"), mounted, service=service, include_mounted_items=True)(lambda _: None, None)


def test_material_with_missing_texture_reports_the_path(tmp_path):
    from cdmw.core.pac_xml_standard_material import PlainMaterial, plain_material_xml
    from cdmw.services.new_item_mounted_base import _check_material_textures
    service, _clean, _first, mounted, _root = mounted_game(tmp_path)
    missing = "character/texture/missing.dds"
    material = ('<SkinnedMeshMaterialWrapper _subMeshName="Blade">' + plain_material_xml(PlainMaterial(missing))
                + '</SkinnedMeshMaterialWrapper>').encode("utf-8")
    with pytest.raises(ValueError, match="missing.dds"):
        _check_material_textures(mounted, {"character/modelproperty/blade.pac_xml": material}, None)


from tests.test_new_item_rust_ui import studio, _send
from tests.test_new_item_export_feedback import _build_new


def test_output_option_reviews_and_exports_mounted_items(studio):
    fixture, tab, bridge = studio
    service = tab.controller.service
    first = service.plan(spec("Existing_Sword"), tab.controller.snapshot)
    root = Path(tab.controller.snapshot.iteminfo.payload_entry.pamt_path).parent.parent
    tab.controller.snapshot = mount_export(service, first, root, fixture.root / "original")
    panel = _build_new(studio)
    assert not panel.export_button.isEnabled()
    from PySide6.QtWidgets import QApplication
    tab.resize(1100, 650)
    QApplication.processEvents()
    assert not panel.include_mounted.visibleRegion().isEmpty()
    _send(bridge, panel.include_mounted, "toggle", True)
    assert not panel.add_to_mod.isChecked() and tab.controller.include_mounted_items
    assert not tab.controller.has_current_plan
    _send(bridge, panel.build_button, "activate")
    assert tab.controller.has_current_plan, panel.summary.toPlainText()
    assert panel.export_button.isEnabled()
    review = bridge.document.widget(panel.mounted_review, force=True)["props"]
    assert "Existing_Sword" in review["text"] and "0036" in review["text"]
    assert "in place of" in review["text"] and review["wrap"]
    assert not panel.mounted_review.visibleRegion().isEmpty()
    with patch("cdmw.ui.new_item.panels_output.QMessageBox.information") as message:
        _send(bridge, panel.export_button, "activate")
    assert "disable the included originals" in message.call_args.args[2]
    assert (panel._package_root() / "README.txt").is_file()
    _send(bridge, panel.add_to_mod, "toggle", True)
    assert not panel.include_mounted.isChecked() and not tab.controller.include_mounted_items
    assert not tab.controller.has_current_plan
