"""Actual compiler/archive preparation on owned game fixtures, without native admission."""
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import struct
import threading
from uuid import uuid4
import zipfile

import pytest

from cdmw.core.archive_format import calculate_pa_checksum, parse_archive_pamt_bytes
from cdmw.core.papgt_format import parse_papgt
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.spec import ModelSource
from cdmw.services import independent_item_native_resources as owner
from cdmw.services.independent_item_install import (
    export_profile, load_registry, prepare_install, prepare_profile_import, prepare_remove, resolve_items,
)
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.new_item_planning import ModelFiles
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_reference_assessment import TEXTURE
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import imported_game
from tests.test_new_item_service import PAC_XML, imported_pac


def authored_resource(path, *, identity=None, variant=0, name="SameDonorResource"):
    service, snapshot = imported_game(path)
    side_files = {PAC_XML: snapshot.payload(PAC_XML)}
    if variant:
        texture = snapshot.payload(TEXTURE)
        texture = texture[:-1] + bytes([texture[-1] ^ variant])
        side_files[TEXTURE] = texture
    plan = service.plan(replace(shop_spec(name), model_source=ModelSource.IMPORTED), snapshot,
                        model=ModelFiles(imported_pac(100), side_files),
                        capture_independent=True)
    return from_plan(plan, identity or uuid4().hex)


def prepared_pair(tmp_path):
    packages = [authored_resource(tmp_path / "author-a"), authored_resource(tmp_path / "author-b", variant=1)]
    imported_game(tmp_path / "recipient")
    root = tmp_path / "recipient/game"
    return root, packages, [package_bytes(package) for package in packages]


def images_by_id(sources, root):
    return {image.identity: image for image in owner.prepare_native_resource_images(sources, root, target="archive")}


def assert_exact_compiler_bytes(image, changes):
    expected = {path: row["after"] for path, row in changes.items() if row["before"] is None and row["after"] is not None}
    entries = parse_archive_pamt_bytes(image.index_bytes, Path("0000/0.pamt"))
    assert {entry.path for entry in entries} == set(expected)
    for entry in entries:
        assert entry.flags == 0 and entry.paz_index == 0
        assert entry.comp_size == entry.orig_size == len(expected[entry.path])
        assert image.archive_bytes[entry.offset:entry.offset + entry.comp_size] == expected[entry.path]
    checksum, count, _constant, ordinal, archive_checksum, archive_size = struct.unpack_from("<6I", image.index_bytes)
    assert count == 1 and ordinal == 0
    assert checksum == calculate_pa_checksum(image.index_bytes[12:])
    assert archive_checksum == calculate_pa_checksum(image.archive_bytes)
    assert archive_size == len(image.archive_bytes)
    directory, = parse_papgt(image.mount_bytes)
    assert directory.name == "0000" and directory.pamt_checksum == checksum


@pytest.mark.parametrize("target", ["archive", "virtual"])
def test_actual_two_package_images_contain_only_their_compiler_resources(tmp_path, target):
    root, packages, sources = prepared_pair(tmp_path)
    before = files_in(root)
    resolved = resolve_items(sources, root, target=target, rebuild=True, capture_isolation=True)
    options = {"target": "archive"} if target == "archive" else {}
    images = {image.identity: image for image in owner.prepare_native_resource_images(sources, root, **options)}
    members = []
    for package, changes in resolved.contributions:
        image = images[package.identity]
        assert_exact_compiler_bytes(image, changes)
        report = image.report()
        assert report["content_sha256"] == package.digest
        assert report["artifact_sha256"] == package.artifact_digest
        assert report["binding_sha256"] == resolved.registry["items"][package.identity]["binding_hash"]
        assert report["binding_status"]["projection"] == "proposed"
        assert all(row["status"] == "proposed" for row in report["binding_status"]["symbols"])
        assert report["excluded_shared_outputs"] and report["shared_integrations"]
        assert report["borrowed_contribution_paths"] and report["resource_graph"]["unresolved"]
        assert not report["published"] and not report["native_admission"]
        assert not report["native_engine_calls_executed"] and not report["native_resource_use_verified"]
        assert not report["reference_closure_claimed"]
        assert report["storage"]["image_bytes"] == sum(len(data) for _path, data in image.files)
        assert report["storage"]["archive_bytes"] >= report["storage"]["payload_bytes"]
        paths = {row["path"] for row in report["members"]}
        assert paths.isdisjoint(row["path"] for row in report["excluded_shared_outputs"])
        assert all(row["in_image"] for row in report["binding_status"]["paths"])
        members.append(paths)
        report["members"].clear()
        assert image.report()["members"]  # Consumers cannot mutate the captured report.
    assert members[0] and members[0].isdisjoint(members[1])
    assert files_in(root) == before
    print("native_resource_image_metrics=" + json.dumps({"target": target,
        "packages": [image.report()["storage"] for image in images.values()],
        "image_checksum_helper_threshold_exceeded": any(len(image.archive_bytes) > 65536 for image in images.values())}, sort_keys=True))


def test_retained_order_update_removal_and_reinstall_preserve_the_other_image(tmp_path):
    root, packages, sources = prepared_pair(tmp_path)
    backups = Backups(tmp_path)
    backups.apply(prepare_install(sources, root).preparation)
    original_bindings = deepcopy(load_registry(root)["items"])
    images = images_by_id(sources, root)
    reversed_images = images_by_id(sources[::-1], root)
    for package in packages:
        assert images[package.identity].files == reversed_images[package.identity].files
        assert images[package.identity].report()["binding_status"]["projection"] == "retained"
    renamed = authored_resource(tmp_path / "author-rename", identity=packages[0].identity, name="RenamedResource")
    name_only = images_by_id([package_bytes(renamed), sources[1]], root)[renamed.identity]
    assert name_only.report()["content_sha256"] != packages[0].digest
    assert name_only.files == images[renamed.identity].files
    updated = authored_resource(tmp_path / "author-update", identity=packages[0].identity, variant=2)
    changed_sources = [package_bytes(updated), sources[1]]
    before = files_in(root)
    changed = images_by_id(changed_sources, root)
    assert changed[packages[0].identity].archive_bytes != images[packages[0].identity].archive_bytes
    assert changed[packages[1].identity].files == images[packages[1].identity].files
    assert changed[packages[0].identity].report()["content_sha256"] != packages[0].digest
    assert changed[packages[0].identity].report()["bindings"] == original_bindings[packages[0].identity]["values"]
    previous_paths = {row["path"] for row in images[packages[0].identity].report()["members"]}
    next_paths = {row["path"] for row in changed[packages[0].identity].report()["members"]}
    retired, proposed = previous_paths - next_paths, next_paths - previous_paths
    assert retired and proposed
    statuses = {row["path"]: row for row in changed[packages[0].identity].report()["binding_status"]["paths"]}
    assert all(statuses[path]["status"] == "retained" and not statuses[path]["in_image"] for path in retired)
    assert all(statuses[path]["status"] == "proposed" and statuses[path]["in_image"] for path in proposed)
    assert all(row["status"] == "retained" for row in changed[packages[0].identity].report()["binding_status"]["symbols"])
    assert files_in(root) == before
    backups.apply(prepare_install([changed_sources[0]], root).preparation)
    backups.apply(prepare_remove(packages[0].identity, root))
    remaining = images_by_id([sources[1]], root)
    assert remaining[packages[1].identity].files == images[packages[1].identity].files
    backups.apply(prepare_install([changed_sources[0]], root).preparation)
    reinstalled = images_by_id(changed_sources, root)
    assert reinstalled[packages[0].identity].files == changed[packages[0].identity].files
    assert load_registry(root)["items"][packages[0].identity]["values"] == original_bindings[packages[0].identity]["values"]
    profile = export_profile(root, tmp_path / "save.cdprofile")
    imported_game(tmp_path / "transfer")
    transfer = tmp_path / "transfer/game"
    backups.apply(prepare_profile_import(profile, transfer))
    before_transfer = files_in(transfer)
    transferred = images_by_id(changed_sources[::-1], transfer)
    for package in packages:
        assert transferred[package.identity].files == reinstalled[package.identity].files
        assert transferred[package.identity].report()["binding_status"]["projection"] == "retained"
    assert files_in(transfer) == before_transfer


def test_repacked_zip_and_duplicate_sources_keep_content_and_image_identity(tmp_path):
    root, packages, sources = prepared_pair(tmp_path)
    original = sources[0]
    repacked = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(repacked, "w", compression=zipfile.ZIP_STORED) as target:
        for name in reversed(source.namelist()):
            target.writestr(name, source.read(name))
    different = repacked.getvalue()
    assert different != original
    first, = owner.prepare_native_resource_images([original], root, target="archive")
    second, = owner.prepare_native_resource_images([original, different], root, target="archive")
    assert first.files == second.files
    assert first.report()["content_sha256"] == second.report()["content_sha256"] == packages[0].digest
    assert first.report()["artifact_sha256"] != second.report()["artifact_sha256"]
    assert first.report()["resource_image_sha256"] == second.report()["resource_image_sha256"]


@pytest.fixture
def resolved_input(tmp_path, monkeypatch):
    package = authored_resource(tmp_path / "author")
    imported_game(tmp_path / "recipient")
    root = tmp_path / "recipient/game"
    sources = [package_bytes(package)]
    resolved = resolve_items(sources, root, target="archive", rebuild=True, capture_isolation=True)
    monkeypatch.setattr(owner, "resolve_items", lambda *args, **kwargs: resolved)
    return root, sources, resolved


@pytest.mark.parametrize("fault", ["assessment", "reservation", "payload", "graph", "shared-carrier", "missing", "duplicate"])
def test_incomplete_or_mismatched_compiler_joins_refuse(resolved_input, fault):
    root, sources, resolved = resolved_input
    package, changes = resolved.contributions[0]
    assessment = resolved.isolation_assessments[0]
    path = next(path for path, change in changes.items() if change["before"] is None)
    if fault == "assessment":
        assessment["content_sha256"] = "0" * 64
    elif fault == "reservation":
        resolved.registry["items"][package.identity]["paths"].remove(path)
    elif fault == "payload":
        changes[path]["after"] += b"changed"
    elif fault == "graph":
        next(row for row in assessment["resource_graph"]["resources"] if row["path"] == path)["ownership"] = "borrowed"
    elif fault == "shared-carrier":
        changes[path]["meta"] = True
    elif fault == "missing":
        resolved.isolation_assessments = ()
    else:
        resolved.isolation_assessments += (assessment,)
    before = files_in(root)
    with pytest.raises(IndependentItemError):
        owner.prepare_native_resource_images(sources, root, target="archive")
    assert files_in(root) == before


@pytest.mark.parametrize("fault", ["index-checksum", "paz-checksum", "paz-size", "trailing-index", "range", "payload"])
def test_archive_corruption_is_detected_after_serialization(resolved_input, monkeypatch, fault):
    root, sources, _resolved = resolved_input
    build = owner.build_overlay_archive
    def corrupt(*args, **kwargs):
        archive = build(*args, **kwargs)
        index, paz = bytearray(archive.pamt_bytes), bytearray(archive.paz_bytes)
        if fault == "index-checksum":
            index[0] ^= 1
        elif fault == "paz-checksum":
            index[16] ^= 1
            struct.pack_into("<I", index, 0, calculate_pa_checksum(index[12:]))
        elif fault == "paz-size":
            struct.pack_into("<I", index, 20, len(paz) + 16)
            struct.pack_into("<I", index, 0, calculate_pa_checksum(index[12:]))
        elif fault == "trailing-index":
            index.extend(b"extra")
            struct.pack_into("<I", index, 0, calculate_pa_checksum(index[12:]))
        elif fault == "range":
            offset = 24
            for width in (1, 1, 16):
                offset += 4 + struct.unpack_from("<I", index, offset)[0] * width
            struct.pack_into("<I", index, offset + 8, len(paz) + 16)
            struct.pack_into("<I", index, 0, calculate_pa_checksum(index[12:]))
        else:
            paz[0] ^= 1
            struct.pack_into("<I", index, 16, calculate_pa_checksum(paz))
            struct.pack_into("<I", index, 0, calculate_pa_checksum(index[12:]))
        return replace(archive, pamt_bytes=bytes(index), paz_bytes=bytes(paz), pamt_checksum=struct.unpack_from("<I", index)[0])
    monkeypatch.setattr(owner, "build_overlay_archive", corrupt)
    with pytest.raises(IndependentItemError):
        owner.prepare_native_resource_images(sources, root, target="archive")


def test_profile_drift_after_archive_work_refuses(resolved_input, monkeypatch):
    root, sources, _resolved = resolved_input
    build = owner.build_overlay_archive
    profile = root / ".cdmw/independent-items.json"
    assert not profile.exists()
    def drift(*args, **kwargs):
        result = build(*args, **kwargs)
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_bytes(b"changed")
        return result
    monkeypatch.setattr(owner, "build_overlay_archive", drift)
    with pytest.raises(IndependentItemError, match="changed during private resource preparation"):
        owner.prepare_native_resource_images(sources, root, target="archive")
    assert profile.read_bytes() == b"changed"  # Preparation must not overwrite foreign changes.


@pytest.mark.parametrize("limit", ["MAX_BLOB", "MAX_FILES", "MAX_TOTAL"])
def test_resource_budgets_refuse_before_archive_build(resolved_input, monkeypatch, limit):
    root, sources, _resolved = resolved_input
    monkeypatch.setattr(owner, limit, 0)
    def unexpected(*args, **kwargs):
        raise AssertionError("A refused resource budget reached archive construction.")
    monkeypatch.setattr(owner, "build_overlay_archive", unexpected)
    with pytest.raises(IndependentItemError):
        owner.prepare_native_resource_images(sources, root, target="archive")


def test_cancellation_and_empty_inputs_do_not_start_resolution(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Invalid or cancelled inputs reached resolution.")
    monkeypatch.setattr(owner, "resolve_items", unexpected)
    with pytest.raises(IndependentItemError):
        owner.prepare_native_resource_images([], Path("unused"))
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        owner.prepare_native_resource_images([b"unused"], Path("unused"), stop_event=stop)


def test_stock_only_contribution_refuses(resolved_input):
    root, sources, resolved = resolved_input
    resolved.isolation_assessments[0]["contribution_class"] = "stock-edits"
    with pytest.raises(IndependentItemError, match="new-item contributions"):
        owner.prepare_native_resource_images(sources, root, target="archive")


def test_real_cli_reports_without_publishing_game_or_profile_files(tmp_path, capsys):
    from scripts.inspect_cditem_native_resources import main

    root, packages, sources = prepared_pair(tmp_path)
    selected = tmp_path / "selected.cditem"
    selected.write_bytes(sources[0])
    before = files_in(root)
    assert main(["--game-root", str(root), str(selected)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["published"] and not result["native_admission"]
    assert result["packages"][0]["identity"] == packages[0].identity
    assert result["packages"][0]["members"]
    assert files_in(root) == before
