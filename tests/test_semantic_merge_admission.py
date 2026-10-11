"""Actual semantic export/Merge admission and atomic publication on owned fixtures."""
import os
import threading

import pytest

from cdmw.core.mod_compatibility import SEMANTIC_EXPORT_FILE, read_semantic_export
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.domain.archives.iteminfo_composition import rows_of
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.iteminfo_operations import ItemFieldConflict
from cdmw.services.independent_item_compatibility import prepare_independent_mod_merge
from cdmw.services.independent_item_install import load_registry, prepare_install
from cdmw.services.independent_item_package import package_bytes, read_package
from cdmw.services.mod_merge_service import export_merged_mod, prepare_mod_merge
from cdmw.services.new_item_mod_base import build_mod_base_snapshot, mod_folder_payloads
from tests.test_archive_overlay_manager import Backups, snapshot_of
from tests.test_independent_item_fields import field_package
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game
from tests.test_iteminfo_row import DDD


def exported_fields(base, *, value=7, stat=False):
    service, snapshot, entries = setup_game(base)
    package = field_package(snapshot, value=value, stat=stat)
    root = base / "game"
    Backups(base).apply(prepare_install([package_bytes(package)], root).preparation)
    plan = prepare_independent_mod_merge(root)
    result = export_merged_mod(plan, base / "exported")
    assert result.manager == "CDMW"
    assert {path.name for path in result.package_root.iterdir()} == {SEMANTIC_EXPORT_FILE}
    readback = read_semantic_export(result.package_root)
    assert readback is not None
    assert {read_package(raw).identity for raw in readback.packages} == {package.identity}
    return result.package_root, package, (service, snapshot, entries)


def merged_plan(tmp_path, *, other_stat=False, other_value=7):
    first, first_package, _ = exported_fields(tmp_path / "first")
    second, second_package, _ = exported_fields(tmp_path / "second", stat=other_stat, value=other_value)
    _, snapshot, entries = setup_game(tmp_path / "recipient")
    root = tmp_path / "recipient/game"
    plan = prepare_mod_merge((first, second), root, entries=entries)
    return plan, root, snapshot, (first_package, second_package)


def test_semantic_export_cannot_be_used_as_an_unannotated_mod_or_new_item_base(tmp_path):
    folder, _, (service, snapshot, _) = exported_fields(tmp_path)
    snapshot = snapshot_of(tmp_path / "game")
    before = files_in(folder)
    for consumer in (lambda: mod_folder_payloads(folder),
                     lambda: build_mod_base_snapshot(service, snapshot, folder, read_entry=snapshot.provenance.reader)):
        with pytest.raises(ValueError, match="semantic export.*required package intent"):
            consumer()
    assert files_in(folder) == before


@pytest.mark.parametrize("reverse", [False, True])
def test_generic_merge_retains_source_equal_requirement_after_actual_roundtrip(tmp_path, reverse):
    first, first_package, _ = exported_fields(tmp_path / "first", value=1)
    second, second_package, _ = exported_fields(tmp_path / "second", value=9)
    _, _, entries = setup_game(tmp_path / "recipient")
    root = tmp_path / "recipient/game"
    before = {path: files_in(path) for path in (first, second, root)}
    folders = (second, first) if reverse else (first, second)
    with pytest.raises(ItemFieldConflict) as caught:
        prepare_mod_merge(folders, root, entries=entries)
    assert first_package.identity in str(caught.value)
    assert second_package.identity in str(caught.value)
    assert all(files_in(path) == content for path, content in before.items())


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("disjoint", [False, True])
def test_generic_merge_roundtrip_retains_both_equal_or_disjoint_owners(tmp_path, reverse, disjoint):
    first, first_package, _ = exported_fields(tmp_path / "first", value=7)
    second, second_package, _ = exported_fields(tmp_path / "second", stat=disjoint, value=13000 if disjoint else 7)
    _, snapshot, entries = setup_game(tmp_path / "recipient")
    root = tmp_path / "recipient/game"
    before = {path: files_in(path) for path in (first, second, root)}
    folders = (second, first) if reverse else (first, second)
    plan = prepare_mod_merge(folders, root, entries=entries)
    assert not plan.conflicts
    merged = export_merged_mod(plan, tmp_path / "combined")
    readback = read_semantic_export(merged.package_root)
    owners = {first_package.identity, second_package.identity}
    assert {read_package(raw).identity for raw in readback.packages} == owners
    data = {path: value for path, value, _flags in readback.files}
    row = parse_iteminfo_row(rows_of(data[snapshot.iteminfo.payload_entry.path],
                                    data[snapshot.iteminfo.header_entry.path])[1001295])
    assert row.max_stack_count == 7
    if disjoint:
        assert row.stat(0, DDD).value == 13000
    assert all(files_in(path) == content for path, content in before.items())
    Backups(tmp_path / "recipient").apply(prepare_install([merged.package_root / SEMANTIC_EXPORT_FILE], root).preparation)
    assert set(load_registry(root)["items"]) == owners
    assert snapshot_of(root).rows[1001295].max_stack_count == 7


def test_semantic_export_cancelled_after_staging_keeps_output_absent(tmp_path, monkeypatch):
    from cdmw.core import mod_compatibility

    plan, root, _, _ = merged_plan(tmp_path)
    before = files_in(root)
    stop = threading.Event()
    writer = mod_compatibility.write_semantic_export

    def cancel_after(*args, **kwargs):
        written = writer(*args, **kwargs)
        stop.set()
        return written

    monkeypatch.setattr(mod_compatibility, "write_semantic_export", cancel_after)
    destination = tmp_path / "cancelled"
    with pytest.raises(RunCancelled):
        export_merged_mod(plan, destination, stop_event=stop)
    assert not destination.exists()
    assert not list(tmp_path.glob(".cancelled.cdmw-stage-*"))
    assert files_in(root) == before


def test_semantic_export_rechecks_exact_wrapper_digest_before_publication(tmp_path, monkeypatch):
    from cdmw.core import mod_compatibility

    plan, root, _, _ = merged_plan(tmp_path)
    writer = mod_compatibility.write_semantic_export
    source = plan.folders[0] / SEMANTIC_EXPORT_FILE
    destination = tmp_path / "changed"
    destination.mkdir()
    before = files_in(root)

    def change_after(*args, **kwargs):
        written = writer(*args, **kwargs)
        stat, data = source.stat(), bytearray(source.read_bytes())
        data[-1] ^= 1
        source.write_bytes(data)
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return written

    monkeypatch.setattr(mod_compatibility, "write_semantic_export", change_after)
    with pytest.raises((ValueError, RuntimeError), match="[Cc]hanged|[Mm]ismatch"):
        export_merged_mod(plan, destination)
    assert not list(destination.iterdir())
    assert not list(tmp_path.glob(".changed.cdmw-stage-*"))
    assert files_in(root) == before


def test_semantic_publication_failure_keeps_previous_usable_artifact(tmp_path, monkeypatch):
    from cdmw.core import atomic_file

    plan, root, _, _ = merged_plan(tmp_path)
    previous = export_merged_mod(plan, tmp_path / "previous").package_root
    before = files_in(previous), files_in(root)
    destination = tmp_path / "failed"
    destination.mkdir()

    def fail(*args, **kwargs):
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(atomic_file, "atomic_publish_directory", fail)
    with pytest.raises(OSError, match="synthetic publication failure"):
        export_merged_mod(plan, destination)
    assert not list(destination.iterdir())
    assert not list(tmp_path.glob(".failed.cdmw-stage-*"))
    assert (files_in(previous), files_in(root)) == before
    assert read_semantic_export(previous) is not None


def test_late_cancellation_does_not_hide_committed_semantic_export(tmp_path, monkeypatch):
    from cdmw.core import atomic_file

    plan, root, _, _ = merged_plan(tmp_path)
    stop = threading.Event()
    publish = atomic_file.atomic_publish_directory

    def publish_then_cancel(*args, **kwargs):
        result = publish(*args, **kwargs)
        stop.set()
        return result

    monkeypatch.setattr(atomic_file, "atomic_publish_directory", publish_then_cancel)
    destination = tmp_path / "committed"
    result = export_merged_mod(plan, destination, stop_event=stop)
    assert stop.is_set()
    assert result.package_root == destination
    assert read_semantic_export(destination) is not None
