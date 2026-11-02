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
    assert not (root / "cdmw-compatibility.json").exists() and not (root / "cdmw-baseline.zip").exists()
    return evidence


def test_history_survives_folder_rename_and_copy_but_never_payload_edits(tmp_path):
    package = tmp_path / "mod"
    evidence = _package(package)
    before = {name: mod_metadata_path(package, name).read_bytes() for name in HISTORY_FILES}
    removed = retain_dmm_history(package)
    assert set(removed) == {"new-item.json", "meta/0.papgt"}
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


@pytest.mark.parametrize("existing_group", ("0036", "0042"))
def test_dmm_extension_recovers_owned_item_history(tmp_path, monkeypatch, existing_group):
    from cdmw.domain.archives.mutation import ArchiveAddRequest
    from cdmw.services.new_item_mod_base import mod_folder_payloads

    service, snapshot, _entries = setup_game(tmp_path)
    first = service.plan(replace(spec("First"), recipes=()), snapshot)
    prior_asset = ArchiveAddRequest(_entries[0].pamt_path, "character/model/first-only.pac", b"first asset")
    first = replace(first, additions=(*first.additions, prior_asset))
    folder = tmp_path / "mod"
    service.export_loose(first, folder, manager="DMM")
    if existing_group != "0036":
        # Recreate an older CDMW export, including history bound to those bytes.
        for name in HISTORY_FILES:
            shutil.copyfile(mod_metadata_path(folder, name), folder / name)
        (folder / "0036").rename(folder / existing_group)
        manifest = json.loads((folder / "manifest.json").read_bytes())
        manifest["archive_group"] = existing_group
        (folder / "manifest.json").write_text(json.dumps(manifest))
        retain_dmm_history(folder)
    base = build_mod_base_snapshot(service, snapshot, folder, read_entry=snapshot.provenance.reader)
    assert base.base_manifest["item_key"] == first.spec.item_key
    second = service.plan(replace(spec("Second"), recipes=()), base)
    if existing_group != "0036":
        before = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()}

        def fail_history(*_args, **_kwargs):
            raise OSError("History storage unavailable")

        with monkeypatch.context() as patch:
            patch.setattr("cdmw.core.mod_export_history.retain_dmm_history", fail_history)
            with pytest.raises(OSError, match="History storage unavailable"):
                service.export_loose(second, folder, manager="DMM")
        assert {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before
    service.export_loose(second, folder, manager="DMM")
    assert {p.parent.name for p in folder.glob("*/0.pamt")} == {"0036"}
    assert {p.parent.name for p in folder.glob("*/0.paz")} == {"0036"}
    assert json.loads((folder / "manifest.json").read_bytes())["archive_group"] == "0036"
    assert mod_folder_payloads(folder)[prior_asset.path].read_bytes() == prior_asset.payload_data
    record = json.loads(mod_metadata_path(folder, "new-item.json").read_bytes())
    assert first.spec.item_key in {item["item_key"] for item in record["previous_items"]}
    assert record["item_key"] == second.spec.item_key
    assert not any((folder / name).exists() for name in HISTORY_FILES)
    # The record must be filed for the published bytes, not for staging that still held
    # the copied legacy group.
    evidence = read_compatibility(folder)
    assert evidence is not None and evidence.files


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


def test_no_export_route_ships_authoring_records(tmp_path):
    """DMM reads every file a mod ships; CDMW's records must never be among them."""
    from cdmw.core.archive_loose_export import export_archive_payloads_to_mod_ready_loose
    from cdmw.domain.archives.mutation import ArchivePatchRequest
    from cdmw.models import ArchiveEntry, ModPackageInfo
    from cdmw.services.archive_overlay_package_service import export_archive_overlay_package

    group = tmp_path / "game" / "0008"
    group.mkdir(parents=True)
    paz = group / "0.paz"
    paz.write_bytes(b"original chart")
    entry = ArchiveEntry("actionchart/bin__/upperaction/test.paac", group / "0.pamt", paz, 0, 14, 14, 0, 0)
    request = ArchivePatchRequest(entry, b"edited chart bytes")
    loose = export_archive_payloads_to_mod_ready_loose(
        [request], parent_root=tmp_path / "loose", package_info=ModPackageInfo(title="Loose"))
    overlay = tmp_path / "overlay"
    export_archive_overlay_package([request], package_root=overlay, group="0040")
    for root in (loose.package_root, overlay):
        shipped = {path.name for path in root.rglob("*") if path.is_file()}
        assert not shipped & {*HISTORY_FILES, "mesh-editor-session.json"}, shipped
        evidence = read_compatibility(root)
        assert evidence is not None and evidence.originals == {"actionchart/bin__/upperaction/test.paac": b"original chart"}


def test_an_added_file_keeps_history_but_a_changed_payload_never_does(tmp_path):
    package = tmp_path / "mod"
    evidence = _package(package)
    (package / "character/model").mkdir(parents=True)
    (package / "character/model/owned.pac").write_bytes(b"asset the user added")
    assert read_compatibility(package).originals == evidence.originals
    assert mod_metadata_path(package, "cdmw-compatibility.json").is_file()
    (package / "0045/0.paz").write_bytes(b"edited payload")
    assert read_compatibility(package) is None, "an edited payload must not reuse the old baseline"


def test_extending_a_new_item_mod_without_its_record_is_refused(tmp_path):
    from cdmw.core import mod_export_history as history

    service, snapshot, _entries = setup_game(tmp_path)
    first = service.plan(replace(spec("First"), recipes=()), snapshot)
    folder = tmp_path / "mod"
    service.export_loose(first, folder, manager="DMM")
    (folder / "character/model").mkdir(parents=True)
    (folder / "character/model/owned.pac").write_bytes(b"asset the user added")
    base = build_mod_base_snapshot(service, snapshot, folder, read_entry=snapshot.provenance.reader)
    assert base.base_manifest["item_key"] == first.spec.item_key, "an added file must not hide the earlier items"
    shutil.rmtree(history._history_root())
    with pytest.raises(ValueError, match="cannot find its record of the items"):
        build_mod_base_snapshot(service, snapshot, folder, read_entry=snapshot.provenance.reader)


def test_records_never_land_in_a_loose_mod_and_survive_descriptor_rewrites_and_zips(tmp_path):
    import zipfile

    from cdmw.core.archive_loose_export import export_archive_payloads_to_mod_ready_loose
    from cdmw.models import ArchiveEntry, ModPackageInfo
    from cdmw.services.archive_mutation_service import ArchivePatchRequest

    game = tmp_path / "game"
    (game / "0004").mkdir(parents=True)
    (game / "0004" / "0.pamt").write_bytes(b"index")
    entry = ArchiveEntry("sound/windows/1.bnk", game / "0004" / "0.pamt", game / "0004" / "0.paz", 0, 3, 3, 0, 0)
    result = export_archive_payloads_to_mod_ready_loose(
        [ArchivePatchRequest(entry=entry, payload_data=b"new bank")],
        parent_root=tmp_path / "out",
        package_info=ModPackageInfo(title="Audio"),
    )
    root = result.package_root
    names = {path.name for path in root.rglob("*") if path.is_file()}
    assert not names & {"cdmw-compatibility.json", "cdmw-baseline.zip"}
    assert read_compatibility(root) is not None

    # Descriptors are rewritten after the record is saved; the record must still be found.
    (root / "manifest.json").write_text('{"rewritten": true}')
    (root / "README.txt").write_text("changed")
    assert read_compatibility(root) is not None

    zipped = tmp_path / "Audio.zip"
    with zipfile.ZipFile(zipped, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, f"Audio/{path.relative_to(root).as_posix()}")
    assert read_compatibility(zipped) is not None

    (root / "sound/windows/1.bnk").write_bytes(b"edited bank")
    assert read_compatibility(root) is None


def test_moving_new_item_records_keeps_the_compatibility_already_in_history(tmp_path):
    package = tmp_path / "mod"
    evidence = _package(package)
    retain_dmm_history(package)
    assert read_compatibility(package).originals == evidence.originals
    assert mod_metadata_path(package, "new-item.json").read_text() == '{"item_key": 1990001}'


def test_histories_bound_with_the_old_descriptor_rules_are_still_found(tmp_path):
    import hashlib

    from cdmw.core import mod_export_history as history
    from cdmw.core.mod_compatibility import hash_file

    package = tmp_path / "mod"
    (package / "0045").mkdir(parents=True)
    (package / "0045/0.paz").write_bytes(b"payload")
    (package / "manifest.json").write_text("{}")
    # An earlier CDMW bound history to every file except authoring records, README and the mount list.
    records = sorted((path.relative_to(package).as_posix().casefold(), hash_file(path))
                     for path in package.rglob("*") if path.is_file())
    legacy = history._history_root() / hashlib.sha256(json.dumps(records, separators=(",", ":")).encode("utf-8")).hexdigest()
    legacy.mkdir(parents=True)
    (legacy / "new-item.json").write_text('{"item_key": 7}')
    assert mod_metadata_path(package, "new-item.json") == legacy / "new-item.json"
