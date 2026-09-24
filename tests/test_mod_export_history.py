"""Lean DMM packages keep local history without weakening publication checks."""
from dataclasses import replace
import json
import shutil
import threading

import pytest

from cdmw.core.mod_compatibility import compatibility_from_payloads, read_compatibility, write_compatibility
from cdmw.core.mod_export_history import HISTORY_FILES, mod_metadata_path, retain_dmm_history
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.new_item_mod_base import build_mod_base_snapshot
from cdmw.services.new_item_service import NewItemExportResult, _publish_package_atomically
from tests.test_new_item_provenance import setup_game, spec


def _package(root):
    (root / "0045").mkdir(parents=True)
    (root / "0045/0.pamt").write_bytes(b"index")
    (root / "0045/0.paz").write_bytes(b"payload")
    (root / "meta").mkdir()
    (root / "meta/0.pathc").write_bytes(b"texture registrations")
    (root / "meta/0.papgt").write_bytes(b"unused mount list")
    (root / "manifest.json").write_text('{"target_game": {"build": "2.03.02"}}')
    (root / "modinfo.json").write_text('{"name": "Example"}')
    (root / "README.txt").write_text("Enable this mod in DMM.")
    (root / "new-item.json").write_text('{"item_key": 1990001}')
    evidence = compatibility_from_payloads({"character/model.pac": b"new"}, {"character/model.pac": b"old"})
    write_compatibility(root, evidence)
    return evidence


def test_history_survives_folder_rename_and_copy_but_never_payload_edits(tmp_path):
    package = tmp_path / "mod"
    evidence = _package(package)
    before = {name: (package / name).read_bytes() for name in HISTORY_FILES}
    removed = retain_dmm_history(package)
    assert set(removed) == {*HISTORY_FILES, "meta/0.papgt"}
    assert {p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()} == {
        "0045/0.pamt", "0045/0.paz", "meta/0.pathc", "manifest.json", "modinfo.json", "README.txt"}
    assert (package / "meta/0.pathc").read_bytes() == b"texture registrations"
    renamed = package.rename(tmp_path / "renamed")
    copied = tmp_path / "copied"
    shutil.copytree(renamed, copied)
    for root in (renamed, copied):
        assert read_compatibility(root).originals == evidence.originals
        for name, data in before.items():
            history = mod_metadata_path(root, name)
            assert not history.is_relative_to(root)
            assert history.read_bytes() == data
    (copied / "0045/0.paz").write_bytes(b"changed")
    assert read_compatibility(copied) is None
    assert not mod_metadata_path(copied, "new-item.json").exists()
    assert read_compatibility(renamed).originals == evidence.originals


def test_legacy_inline_records_remain_authoritative(tmp_path):
    package = tmp_path / "mod"
    _package(package)
    retain_dmm_history(package)
    inline = package / "new-item.json"
    inline.write_text('{"item_key": 1990002}')
    assert mod_metadata_path(package, inline.name) == inline
    (package / "cdmw-compatibility.json").write_text("invalid")
    with pytest.raises(ValueError):
        read_compatibility(package)


@pytest.mark.parametrize("failure", ("write", "cancel"))
def test_history_failure_preserves_previous_export(tmp_path, monkeypatch, failure):
    import cdmw.core.mod_export_history as history

    package = tmp_path / "mod"
    _package(package)
    before = {p.relative_to(package): p.read_bytes() for p in package.rglob("*") if p.is_file()}
    stop = threading.Event()
    publish_history = history.atomic_publish_directory

    def fail(_staging, _target):
        if failure == "cancel":
            publish_history(_staging, _target)
            stop.set()
            return
        raise OSError("History storage unavailable")

    monkeypatch.setattr(history, "atomic_publish_directory", fail)

    def write(staging):
        (staging / "0045/0.paz").write_bytes(b"replacement")
        return NewItemExportResult(staging, "DMM", (), (), HISTORY_FILES)

    with pytest.raises(RunCancelled if failure == "cancel" else OSError):
        _publish_package_atomically(package, write, stop_event=stop)
    assert {p.relative_to(package): p.read_bytes() for p in package.rglob("*") if p.is_file()} == before
    assert not list(package.parent.glob(".mod.cdmw-stage-*"))
    assert not list(history._history_root().glob(".history-*"))


def test_dmm_extension_recovers_owned_item_history(tmp_path):
    service, snapshot, _entries = setup_game(tmp_path)
    first = service.plan(replace(spec("First"), recipes=()), snapshot)
    folder = tmp_path / "mod"
    service.export_loose(first, folder, manager="DMM")
    base = build_mod_base_snapshot(service, snapshot, folder, read_entry=snapshot.provenance.reader)
    assert base.base_manifest["item_key"] == first.spec.item_key
    second = service.plan(replace(spec("Second"), recipes=()), base)
    service.export_loose(second, folder, manager="DMM")
    record = json.loads(mod_metadata_path(folder, "new-item.json").read_bytes())
    assert first.spec.item_key in {item["item_key"] for item in record["previous_items"]}
    assert record["item_key"] == second.spec.item_key
    assert not any((folder / name).exists() for name in HISTORY_FILES)


@pytest.mark.parametrize("operation", ("extend", "merge", "update"))
def test_changed_local_history_invalidates_prepared_work(tmp_path, operation):
    from cdmw.services.mod_merge_service import prepare_mod_merge
    from cdmw.services.mod_update_service import prepare_mod_update
    from cdmw.services.new_item_provenance import StaleNewItemSource
    from tests.test_mod_merge import make_mods

    service, snapshot, entries, _plans, folders = make_mods(tmp_path)
    if operation == "extend":
        base = build_mod_base_snapshot(service, snapshot, folders[1], read_entry=snapshot.provenance.reader)
        pending = service.plan(replace(spec("Third"), recipes=()), base).source_revision
    elif operation == "merge":
        pending = prepare_mod_merge(folders, tmp_path / "game", entries=entries)
    else:
        pending = prepare_mod_update(folders[1], tmp_path / "game", entries=entries)
    metadata = mod_metadata_path(folders[1], "cdmw-baseline.zip")
    metadata.write_bytes(metadata.read_bytes() + b"changed history")
    with pytest.raises((ValueError, StaleNewItemSource), match="changed|changed history"):
        pending.validate()
