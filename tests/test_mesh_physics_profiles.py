from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.core.common import RunCancelled
from cdmw.models import ArchiveEntry
from cdmw.services import mesh_physics_profiles as profiles
from cdmw.services import mesh_rust_authoring as authoring
from tests.test_mesh_rust_archive_texture_launch import _entry
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadWorker


def _prepared(tmp_path, path, data, *, package="0010", ordinal=0):
    prepared = tmp_path / f"{package}-{ordinal}-{Path(path).name}"
    prepared.write_bytes(data)
    return ArchiveEntry(
        path, tmp_path / package / "0.pamt", tmp_path / package / "0.paz",
        ordinal, 700, 900, 0, 0, prepared_path=prepared,
        prepared_size=len(data), prepared_sha256=hashlib.sha256(data).hexdigest(),
    )


@pytest.fixture
def physics_inputs(tmp_path):
    source = _prepared(tmp_path, _entry(tmp_path).path, _pac_fixture(skinned=False))
    sidecar = _prepared(tmp_path, source.path.replace("/model/", "/modelproperty/") + "_xml", (
        '<Common/><ModelPropertyList><ModelProperty Index="0">'
        '<SkinnedMeshProperty _pbdSimulationMaterialName="Lower_Leather">'
        '<SkinnedMeshMaterialWrapper _subMeshName="skirt"><Material _materialName="cloth"/>'
        '</SkinnedMeshMaterialWrapper><SkinnedMeshMaterialWrapper _subMeshName="belt"/>'
        '</SkinnedMeshProperty></ModelProperty><ModelProperty Index="1">'
        '<SkinnedMeshMaterialWrapper _subMeshName="skirt" _pbdSimulationMaterialName=""/>'
        '</ModelProperty></ModelPropertyList>'
    ).encode("utf-16"))
    catalogue = _prepared(tmp_path, "character/descriptors/pbd/pbdconfig.xml", (
        '<Config><!-- <Material Name="Lower_Leather" Filename="wrong.xml"/> -->'
        '<Material Name="Lower_Leather" Filename="Material/Armor/Lower_Leather.xml"/>'
        '</Config>'
    ).encode())
    profile = _prepared(tmp_path, "character/descriptors/pbd/material/armor/lower_leather.xml", (
        '<?xml version="1.0"?><Profile><!-- keep me -->\r\n'
        '<Damping>8.125</Damping><UnknownFlag magic="3"/>'
        '<AttachedCloth><Damping>0.4</Damping></AttachedCloth></Profile>'
    ).encode())
    index = {}
    for entry in (sidecar, catalogue, profile):
        index.setdefault(Path(entry.path).name.casefold(), []).append(entry)
    return source, index, sidecar, catalogue, profile


def test_exact_profile_sources_preserve_bytes_variants_and_empty_bindings(physics_inputs):
    source, index, sidecar, catalogue, profile = physics_inputs
    before = {entry.prepared_path: entry.prepared_path.read_bytes() for entry in (sidecar, catalogue, profile)}
    context = profiles.resolve_mesh_physics_profiles(source, index)
    assert not context.problem
    assert context.source_identity == source.identity
    assert context.sidecar.data == before[sidecar.prepared_path]
    assert context.catalogue.data == before[catalogue.prepared_path]
    assert len(context.profiles) == 1  # Two parts share one immutable document.
    document = context.profiles[0]
    assert document.data == before[profile.prepared_path]
    assert document.sha256 == profile.prepared_sha256
    assert document.identity == profile.identity
    assert b"8.125" in document.data  # Authored values are never clamped to preview limits.
    assert [(row.submesh_name, row.variant_index, row.profile_name, row.profile_path) for row in context.bindings] == [
        ("skirt", "0", "Lower_Leather", profile.path),
        ("belt", "0", "Lower_Leather", profile.path),
        ("skirt", "1", "", ""),
    ]
    assert not any(row.problem for row in context.bindings)
    with pytest.raises(FrozenInstanceError):
        document.data = b"changed"
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("inherited", [False, True])
def test_explicit_empty_bindings_are_retained_without_loading_a_catalogue(physics_inputs, inherited):
    source, index, sidecar, *_ = physics_inputs
    data = (b'<Root _pbdSimulationMaterialName=""><Part _subMeshName="skirt"/></Root>' if inherited else
            b'<Root _pbdSimulationMaterialName="Lower_Leather"><Part _subMeshName="skirt" _pbdSimulationMaterialName=""/></Root>')
    sidecar.prepared_path.write_bytes(data)
    sidecar.prepared_size = len(data)
    sidecar.prepared_sha256 = hashlib.sha256(data).hexdigest()
    context = profiles.resolve_mesh_physics_profiles(source, index)
    assert not context.problem and context.catalogue is None and not context.profiles
    assert [(row.submesh_name, row.profile_name, row.variant_index) for row in context.bindings] == [("skirt", "", "")]


def test_character_profile_lookup_uses_modelproperty_not_a_same_name_decoy(physics_inputs, tmp_path):
    source, index, sidecar, *_ = physics_inputs
    adjacent = _prepared(tmp_path, source.path + "_xml", b'<Root/>', ordinal=9)
    index[adjacent.basename.casefold()].append(adjacent)
    context = profiles.resolve_mesh_physics_profiles(source, index)
    assert context.sidecar.identity == sidecar.identity and context.profiles
    index[adjacent.basename.casefold()] = [adjacent]
    context = profiles.resolve_mesh_physics_profiles(source, index)
    assert context.problem and context.sidecar is None


@pytest.mark.parametrize("failure", ["decoy", "duplicate", "checksum", "malformed", "declaration", "oversized"])
def test_unverified_profile_stays_unresolved_without_losing_bindings(physics_inputs, tmp_path, failure):
    source, index, _, _, profile = physics_inputs
    key = Path(profile.path).name.casefold()
    if failure == "decoy":
        index[key] = [replace(profile, path="character/descriptors/pbd/unrelated/lower_leather.xml")]
    elif failure == "duplicate":
        index[key].append(replace(profile, pamt_path=tmp_path / "other/0.pamt"))
    else:
        data = {"checksum": b"<Changed/>", "malformed": b"<Profile>",
                "declaration": b'<!DOCTYPE Profile [<!ENTITY e "1">]><Profile>&e;</Profile>',
                "oversized": b" " * (profiles._MAX_DOCUMENT_BYTES + 1)}[failure]
        profile.prepared_path.write_bytes(data)
        profile.prepared_size = len(data)
        if failure != "checksum":
            profile.prepared_sha256 = hashlib.sha256(data).hexdigest()
    context = profiles.resolve_mesh_physics_profiles(source, index)
    assert not context.problem
    assert context.profiles == ()
    assert len(context.bindings) == 3
    assert all(binding.problem and not binding.profile_path for binding in context.bindings[:2])
    assert context.bindings[2].profile_name == "" and not context.bindings[2].problem


def test_catalogue_name_collisions_are_not_silently_overwritten(physics_inputs):
    source, index, _, catalogue, _ = physics_inputs
    data = (b'<Config><Material Name="Lower_Leather" Filename="one.xml"/>'
            b'<Material Name="lower_leather" Filename="two.xml"/></Config>')
    catalogue.prepared_path.write_bytes(data)
    catalogue.prepared_size = len(data)
    catalogue.prepared_sha256 = hashlib.sha256(data).hexdigest()
    context = profiles.resolve_mesh_physics_profiles(source, index)
    assert context.profiles == ()
    assert "ambiguous" in context.bindings[0].problem


def test_capture_is_detached_and_rejects_a_different_pac(physics_inputs):
    source, index, *_ = physics_inputs
    context = profiles.resolve_mesh_physics_profiles(source, index)
    preview = SimpleNamespace(path=source.path, submeshes=())
    controller = SimpleNamespace()
    authoring.prime_rust_mesh_preview_context(controller, preview, target_entry=source, physics_profile_context=context)
    captured = getattr(controller, authoring._RUST_PREVIEW_MATERIAL_CONTEXT_ATTR)
    preview.path = "changed after capture"
    assert captured.physics_profile_context is context
    assert captured.preview_model.path == source.path
    with pytest.raises(authoring.RustMeshAuthoringError, match="different archive entry"):
        authoring.prime_rust_mesh_preview_context(
            controller, preview, target_entry=replace(source, offset=source.offset + 1),
            physics_profile_context=context,
        )
    assert getattr(controller, authoring._RUST_PREVIEW_MATERIAL_CONTEXT_ATTR) is captured


def test_isolated_editing_session_retains_owned_profile_bytes(physics_inputs, tmp_path):
    from tests.test_mesh_rust_authoring import RustMeshAuthoringTests

    source, index, _, _, profile = physics_inputs
    context = profiles.resolve_mesh_physics_profiles(source, index)
    original = profile.prepared_path.read_bytes()
    preview = SimpleNamespace(path=source.path, submeshes=())
    service, host = RustMeshAuthoringTests()._create(
        tmp_path / "session", preview_material_model=preview, target_entry=source,
        physics_profile_context=context,
    )
    try:
        profile.prepared_path.write_bytes(b"cache replaced after capture")
        assert host.physics_profile_context is context
        assert host.physics_profile_context.profiles[0].data == original
        assert host.physics_profile_context.profiles[0].sha256 == hashlib.sha256(original).hexdigest()
    finally:
        host.cancel()
        service.close_edit_session("authoritative-rust-test", force_without_saving=True)


@pytest.mark.parametrize("cancel", [False, True])
def test_archive_loader_publishes_profiles_or_closes_cancelled_session(physics_inputs, cancel):
    source, index, *_ = physics_inputs
    worker = MeshArchiveSessionLoadWorker(7, source, archive_entries_by_basename=index)
    loaded, errors = [], []
    worker.loaded.connect(lambda _request, result: loaded.append(result))
    worker.error.connect(lambda _request, message: errors.append(message))
    from cdmw.services.mesh_service import MeshService
    service = MeshService()
    resolve = profiles.resolve_mesh_physics_profiles

    def capture(*args, **kwargs):
        result = resolve(*args, **kwargs)
        if cancel:
            worker.stop()
            raise RunCancelled("cancelled after physics reads")
        return result

    with patch("cdmw.workers.mesh_editor_aux_workers.MeshService", return_value=service), patch(
        "cdmw.workers.mesh_editor_aux_workers.resolve_mesh_physics_profiles", side_effect=capture,
    ):
        worker.run()
    assert not errors
    if cancel:
        assert not loaded and not service._sessions
    else:
        assert len(loaded) == 1
        result = loaded[0]
        try:
            assert result.physics_profile_context.profiles
            assert result.physics_profile_context.source_identity == source.identity
        finally:
            service.close_edit_session(result.view.session_id, force_without_saving=True)


def test_cancelled_profile_capture_does_not_start_reads(physics_inputs):
    source, index, *_ = physics_inputs
    stop = threading.Event()
    stop.set()
    with patch.object(profiles, "read_archive_entry_data", side_effect=AssertionError("late read")):
        with pytest.raises(RunCancelled):
            profiles.resolve_mesh_physics_profiles(source, index, stop_event=stop)


@pytest.mark.parametrize("stale", [False, True])
def test_editor_retains_loader_profiles_with_cached_materials_and_clears_on_close(physics_inputs, tmp_path, stale):
    from tests.test_mesh_rust_editor_selection import _tab, _dispose
    from cdmw.services.mesh_service import MeshService
    from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadResult

    source, index, *_ = physics_inputs
    context = profiles.resolve_mesh_physics_profiles(source, index)
    service = MeshService()
    mesh = service.load_mesh_bytes(source.prepared_path.read_bytes(), source.path)
    view = service.open_edit_session(mesh, mode="edit")
    result = MeshArchiveSessionLoadResult(service, view, mesh, source.prepared_sha256, physics_profile_context=context)
    tab = _tab(tmp_path)
    tab.archive_session_load_request_id = 8 if stale else 7
    tab.archive_session_load_entry = source
    tab.archive_session_load_material_model = SimpleNamespace(path=source.path, meshes=[SimpleNamespace(
        source_submesh_index=0, preview_texture_dds_path=str(tmp_path / "cached.dds"),
    )])
    tab.archive_material_context_verified_for_rust = True
    try:
        with patch.object(tab, "_start_archive_material_context_resolution", side_effect=AssertionError("cached materials must not be reloaded")):
            tab._handle_archive_session_loaded(7, result)
        if stale:
            assert tab.archive_physics_profile_context is None and not service._sessions
        else:
            assert tab.archive_physics_profile_context is context
            assert not tab._defer_rust_editor_for_material_context(tab.standalone_controller)
            tab._prime_rust_preview_material_context(tab.standalone_controller)
            captured = getattr(tab.standalone_controller, authoring._RUST_PREVIEW_MATERIAL_CONTEXT_ATTR)
            assert captured.physics_profile_context is context
            tab.close_standalone_session()
            assert tab.archive_physics_profile_context is None
    finally:
        service.close_edit_session(view.session_id, force_without_saving=True)
        _dispose(tab)
