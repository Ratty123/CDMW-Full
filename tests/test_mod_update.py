"""Game updates preserve new game rows, original packages, and unknown history."""
from dataclasses import replace
import json
import threading

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.mod_compatibility import (BASELINE_FILE, COMPATIBILITY_FILE, build_status,
    compatibility_from_payloads, read_compatibility, write_compatibility)
from cdmw.core.structured_binary_editor import parse_pabgh_table, replace_table_row
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.mod_update_service import export_updated_mod, prepare_mod_update
from tests.test_mod_merge import fingerprint, payloads
from tests.test_new_item_provenance import current_files, setup_game, spec
from tests.test_new_item_service import build_package, TEMPLATE


def exported(tmp_path, manager="DMM"):
    service, snapshot, entries = setup_game(tmp_path)
    (tmp_path / "game/meta/0.paver").write_text("2.00.00")
    snapshot = service.build_snapshot(entries, read_entry=snapshot.provenance.reader)
    plan = service.plan(replace(spec("UpdateTest"), recipes=()), snapshot)
    folder = tmp_path / "mod"
    service.export_loose(plan, folder, manager=manager)
    return plan, snapshot, entries, folder


@pytest.mark.parametrize("manager", ("DMM", "JMM", "CDUMM"))
def test_exports_record_originals_and_compare_unchanged(tmp_path, manager):
    original, _snapshot, entries, folder = exported(tmp_path, manager)
    evidence = read_compatibility(folder)
    assert evidence.target_game["build"] == "2.00.00"
    assert evidence.originals and all(row["baseline_known"] for row in evidence.files)
    assert evidence.dependencies
    checked = prepare_mod_update(folder, tmp_path / "game", entries=entries)
    assert checked.status == "unchanged", checked.conflicts
    assert checked.can_update
    assert original.spec.item_key == checked.new_item["item_key"]


def test_update_preserves_game_patch_and_authored_item(tmp_path):
    original, snapshot, _entries, folder = exported(tmp_path)
    before_mod = fingerprint(folder)
    files = current_files()
    body_path, head_path = snapshot.iteminfo.payload_entry.path, snapshot.iteminfo.header_entry.path
    body, head = files[body_path], files[head_path]
    table = parse_pabgh_table(head, payload=body)
    row = next(body[start:end] for item, start, end in table.row_spans(len(body)) if item.row_id == TEMPLATE)
    # The patch modifies the shipped template; the mod adds a different row.
    from cdmw.core.iteminfo_row import parse_iteminfo_row, price_list_with, rebuild_stat_block
    parsed = parse_iteminfo_row(row)
    replacement = rebuild_stat_block(parsed, price_list=price_list_with(parsed.price_list, 1, 9876))
    files[body_path], files[head_path] = replace_table_row(body, head, TEMPLATE, replacement)
    pamt = build_package(tmp_path / "game", files)
    (tmp_path / "game/meta/0.paver").write_text("2.00.01")
    before_game = fingerprint(tmp_path / "game")
    plan = prepare_mod_update(folder, tmp_path / "game", entries=parse_archive_pamt(pamt))
    assert plan.status == "changed", plan.conflicts
    assert plan.can_update, plan.conflicts
    result = export_updated_mod(plan, tmp_path / "updated")
    output = payloads(result.package_root)
    rows = {item.row_id: output[body_path][start:end] for item, start, end in
            parse_pabgh_table(output[head_path], payload=output[body_path]).row_spans(len(output[body_path]))}
    assert rows[TEMPLATE] == replacement
    assert original.spec.item_key in rows
    assert fingerprint(folder) == before_mod
    assert fingerprint(tmp_path / "game") == before_game
    assert read_compatibility(result.package_root).target_game["build"] == "2.00.01"


def test_opaque_overlapping_change_blocks_output(tmp_path):
    _service, _snapshot, entries = setup_game(tmp_path)
    folder = tmp_path / "mod"
    (folder / "character").mkdir(parents=True)
    (folder / "character/model.pac").write_bytes(b"mod")
    write_compatibility(folder, compatibility_from_payloads({"character/model.pac": b"mod"},
                                                           {"character/model.pac": b"old"}))
    files = current_files()
    files["character/model.pac"] = b"new game"
    pamt = build_package(tmp_path / "game", files)
    plan = prepare_mod_update(folder, tmp_path / "game", entries=parse_archive_pamt(pamt))
    assert plan.status == "conflict" and not plan.can_update
    with pytest.raises(ValueError, match="conflicts"):
        export_updated_mod(plan, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()


def test_unknown_old_mod_and_modified_export_are_not_certified(tmp_path):
    _original, _snapshot, entries, folder = exported(tmp_path)
    (folder / COMPATIBILITY_FILE).unlink()
    (folder / BASELINE_FILE).unlink()
    (folder / "new-item.json").unlink()
    plan = prepare_mod_update(folder, tmp_path / "game", entries=entries)
    assert plan.status == "unknown" and not plan.can_update


def test_input_changes_cancellation_and_destination_safety(tmp_path):
    _original, _snapshot, entries, folder = exported(tmp_path)
    plan = prepare_mod_update(folder, tmp_path / "game", entries=entries)
    for output in (folder, tmp_path / "game", folder / "updated"):
        with pytest.raises(ValueError, match="separate"):
            export_updated_mod(plan, output)
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        export_updated_mod(plan, tmp_path / "cancelled", stop_event=stop)
    (tmp_path / "game/meta/0.paver").write_text("2.00.02")
    with pytest.raises(ValueError, match="changed"):
        export_updated_mod(plan, tmp_path / "stale")
    assert not (tmp_path / "cancelled").exists() and not (tmp_path / "stale").exists()


def test_build_signatures_do_not_discard_patch_components():
    assert build_status({"build": "2.00.00"}, {"build": "2.00.01"}) == "changed"
    assert build_status({}, {"build": "2.00.01"}) == "unknown"
    assert build_status({"executable_sha256": "a"}, {"executable_sha256": "b"}) == "changed"


def test_tampered_baseline_is_rejected(tmp_path):
    evidence = compatibility_from_payloads({"a/b.pac": b"new"}, {"a/b.pac": b"old"})
    write_compatibility(tmp_path, evidence)
    assert read_compatibility(tmp_path).originals == evidence.originals
    (tmp_path / BASELINE_FILE).write_bytes(b"replaced")
    with pytest.raises(ValueError, match="changed"):
        read_compatibility(tmp_path)


def test_installed_overlays_record_build_and_export_comparison_without_mutation(tmp_path):
    from cdmw.services.archive_overlay_manager import list_installed_overlays
    from cdmw.services.mod_update_service import prepare_installed_overlay_update
    from tests.test_archive_overlay_manager import Backups, snapshot_of
    from cdmw.core.archive_format import discover_pamt_files

    service, snapshot, entries = setup_game(tmp_path)
    root = tmp_path / "game"
    (root / "meta/0.paver").write_text("2.00.00")
    snapshot = snapshot_of(root)
    plan = service.plan(replace(spec("Installed"), recipes=()), snapshot)
    service.install_overlay(plan, mutation_service=Backups(tmp_path), confirmed=True, game_running=lambda: False)
    installed = list_installed_overlays(root)
    assert installed[0].game_build == "2.00.00"
    assert installed[0].compatibility_status == "same"
    (root / "meta/0.paver").write_text("2.00.01")
    assert list_installed_overlays(root)[0].compatibility_status == "changed"
    entries = tuple(entry for pamt in discover_pamt_files(root) for entry in parse_archive_pamt(pamt))
    before = fingerprint(root)
    checked = prepare_installed_overlay_update(root, entries=entries)
    assert checked.can_update, checked.conflicts
    result = export_updated_mod(checked, tmp_path / "updated-overlays")
    assert payloads(result.package_root)
    assert fingerprint(root) == before


def test_compatibility_survives_zip_and_retrofit(tmp_path):
    import zipfile
    from cdmw.core.mod_package_retrofit import analyze_retrofittable_mod_package, retrofit_mod_package
    _original, _snapshot, _entries, folder = exported(tmp_path, "JMM")
    zipped = tmp_path / "mod.zip"
    with zipfile.ZipFile(zipped, "w") as archive:
        for path in folder.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(folder).as_posix())
    assert read_compatibility(zipped).target_game["build"] == "2.00.00"
    package = analyze_retrofittable_mod_package(folder)
    result = retrofit_mod_package(package, output_parent=tmp_path / "converted", manager_profile="cdumm")
    assert read_compatibility(result.package_root).target_game["build"] == "2.00.00"


def test_game_patch_reusing_authored_item_id_blocks_update(tmp_path):
    from cdmw.services.new_item_service import NewItemService
    original, snapshot, _entries, folder = exported(tmp_path)
    incoming = NewItemService().plan(replace(spec("GameAdded"), item_key=original.spec.item_key, recipes=()), snapshot)
    files = current_files()
    files.update(incoming.loose_files)
    pamt = build_package(tmp_path / "game", files)
    checked = prepare_mod_update(folder, tmp_path / "game", entries=parse_archive_pamt(pamt))
    assert not checked.can_update and checked.status == "conflict"
    assert any(str(original.spec.item_key) in message for message in checked.conflicts)


def test_changed_reference_and_modified_mod_payload_are_blocked(tmp_path):
    from cdmw.core.mod_compatibility import digest
    files = current_files()
    reference = "character/reference.pac"
    files[reference] = b"original reference"
    folder = tmp_path / "mod"
    (folder / "character").mkdir(parents=True)
    payload = folder / "character/new.pac"
    payload.write_bytes(b"authored mesh")
    evidence = compatibility_from_payloads({"character/new.pac": payload.read_bytes()}, {"character/new.pac": None},
        dependencies=({"path": reference, "sha256": digest(files[reference])},))
    write_compatibility(folder, evidence)
    pamt = build_package(tmp_path / "game", files)
    assert prepare_mod_update(folder, tmp_path / "game", entries=parse_archive_pamt(pamt)).can_update
    files[reference] = b"game update reference"
    pamt = build_package(tmp_path / "game", files)
    checked = prepare_mod_update(folder, tmp_path / "game", entries=parse_archive_pamt(pamt))
    assert not checked.can_update and (reference, "dependency_changed") in checked.comparisons
    payload.write_bytes(b"manually changed mesh")
    checked = prepare_mod_update(folder, tmp_path / "game", entries=parse_archive_pamt(pamt))
    assert any("mod payload changed" in message for message in checked.conflicts)


def test_input_change_during_export_prevents_publication(tmp_path, monkeypatch):
    from cdmw.services import archive_overlay_package_service
    _original, _snapshot, entries, folder = exported(tmp_path)
    checked = prepare_mod_update(folder, tmp_path / "game", entries=entries)
    before_game = fingerprint(tmp_path / "game")
    write = archive_overlay_package_service.export_archive_overlay_package
    def change_source_after_staging(*args, **kwargs):
        result = write(*args, **kwargs)
        with (folder / "manifest.json").open("a", encoding="utf-8") as stream:
            stream.write("\n")
        return result
    monkeypatch.setattr(archive_overlay_package_service, "export_archive_overlay_package", change_source_after_staging)
    with pytest.raises((ValueError, RuntimeError), match="[Ss]ource.*changed|[Ss]ource.*stale"):
        export_updated_mod(checked, tmp_path / "updated")
    assert not (tmp_path / "updated").exists()
    assert fingerprint(tmp_path / "game") == before_game


def test_oversized_originals_remain_unknown(tmp_path, monkeypatch):
    from cdmw.core import mod_compatibility
    monkeypatch.setattr(mod_compatibility, "MAX_FILE_BYTES", 3)
    monkeypatch.setattr(mod_compatibility, "MAX_BASELINE_BYTES", 4)
    evidence = compatibility_from_payloads({"a.pac": b"mod", "b.pac": b"mod", "c.pac": b"mod"},
        {"a.pac": b"1234", "b.pac": b"123", "c.pac": b"12"})
    assert evidence.originals == {"b.pac": b"123"}
    assert [row["baseline_known"] for row in evidence.files] == [False, True, False]


@pytest.mark.parametrize("manager", ("DMM", "JMM", "CDUMM"))
def test_adding_to_existing_mod_keeps_original_game_baseline(tmp_path, manager):
    from cdmw.services.new_item_mod_base import build_mod_base_snapshot
    from cdmw.services.new_item_service import NewItemService
    original, snapshot, entries, folder = exported(tmp_path, manager)
    service = NewItemService()
    base = build_mod_base_snapshot(service, snapshot, folder, read_entry=snapshot.provenance.reader)
    second = service.plan(replace(spec("SecondItem"), item_key=original.spec.item_key + 100, recipes=()), base)
    service.export_loose(second, folder, manager=manager)
    checked = prepare_mod_update(folder, tmp_path / "game", entries=entries)
    assert checked.status == "unchanged" and checked.can_update, checked.conflicts
    files = payloads(folder)
    body, head = snapshot.iteminfo.payload_entry.path, snapshot.iteminfo.header_entry.path
    ids = {row.row_id for row in parse_pabgh_table(files[head], payload=files[body]).rows}
    assert {original.spec.item_key, second.spec.item_key} <= ids


def test_overlay_history_change_during_load_is_rejected(tmp_path, monkeypatch):
    from cdmw.services import archive_overlay_manager
    from cdmw.services.mod_update_service import prepare_installed_overlay_update
    from tests.test_archive_overlay_manager import Backups
    service, snapshot, entries = setup_game(tmp_path)
    root = tmp_path / "game"
    plan = service.plan(replace(spec("Installed"), recipes=()), snapshot)
    service.install_overlay(plan, mutation_service=Backups(tmp_path), confirmed=True, game_running=lambda: False)
    load = archive_overlay_manager._load_index
    def change_after_read(game_root):
        state = load(game_root)
        with (game_root / ".cdmw/overlays.json").open("a", encoding="utf-8") as stream:
            stream.write("\n")
        return state
    monkeypatch.setattr(archive_overlay_manager, "_load_index", change_after_read)
    with pytest.raises(ValueError, match="Source changed while reading"):
        prepare_installed_overlay_update(root, entries=entries)
