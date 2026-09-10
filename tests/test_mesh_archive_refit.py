from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_archive_refit import (
    archive_refit_snapshots, load_archive_refit_context, save_archive_refit_context,
)
from cdmw.services.mesh_service import MeshService
from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
from tests.test_mesh_rust_authoring_exact_output import (
    _candidate_reference, _open_exact_session, _request, _rig_command,
)


def _entry(root, name, source):
    group = root / "game/character"
    group.mkdir(parents=True, exist_ok=True)
    pamt, paz = group / "0.pamt", group / "0.paz"
    pamt.write_bytes(b"owned archive index")
    paz.write_bytes(source)
    return ArchiveEntry(name, pamt, paz, 0, len(source), len(source), 0, 0)


def _load_pair(tmp_path, *, assign_body=True, texture_paths=None,
               primary_appearance=None, incoming_appearance=None, role="armor", distinct_material=False):
    source, authority, session = _open_exact_session(
        tmp_path / "session", base_texture_path=texture_paths[0] if texture_paths else None,
        neutral_appearance=primary_appearance,
    )
    primary = _entry(tmp_path, "owned-rust-exact.pac", source)
    armor = _entry(tmp_path, "armor.pac", source)
    other = MeshService()
    mesh = other.load_mesh_bytes(source, armor.path, run_roundtrip=True)
    if distinct_material:
        mesh.submeshes[0].name = "Armor"
        mesh.submeshes[0].material = "Armor material"
    other_id = other.open_edit_session(mesh, mode="edit").session_id
    try:
        incoming = other.capture_export_snapshot(other_id)
        if texture_paths:
            incoming.mesh.submeshes[0].preview_texture_dds_path = str(texture_paths[1])
    finally:
        other.close_edit_session(other_id, force_without_saving=True)
    if assign_body:
        result = _rig_command(session, 1, "refit_use_loaded_body", {})
        assert result["state"]["morph_refit"]["driver_submesh_indices"]
    loaded = _rig_command(session, 2, "refit_choose_archive", {
        "role": role, "_primary_entry": primary, "_archive_entry": armor,
        "_archive_snapshot": incoming, "_archive_neutral_appearance": incoming_appearance,
    })
    return source, authority, session, primary, armor, loaded


def _edit_both(session):
    request = _request(session, "transaction_request", 20)
    reference = _candidate_reference(session, request_id=20, first_x=0.4)
    path = session.root / reference["path"]
    candidate = json.loads(path.read_text())
    candidate["submeshes"][-1]["positions"][0][0] = 0.7
    encoded = json.dumps(candidate).encode()
    path.write_bytes(encoded)
    reference.update(byte_length=len(encoded), sha256=hashlib.sha256(encoded).hexdigest().upper())
    request["candidate"] = reference
    session.apply_candidate(request)


def test_archive_refit_finish_and_build_mod_preserve_both_original_files(tmp_path):
    source, authority, session, primary, armor, loaded = _load_pair(tmp_path)
    try:
        assert loaded["state"]["output_policy"] == "exact_game_asset"
        assert len(loaded["state"]["archive_refit_assets"]) == 2
        _rig_command(session, 3, "refit_bind", {"submesh_indices": loaded["result"]["loaded_parts"]})
        _edit_both(session)
        finished = session.finish(_request(session, "finish_request", 21))
        assert len(finished["exact_output_validation"]["assets"]) == 2
        snapshot = authority.capture_export_snapshot("authoritative-rust-exact")
        assert len(archive_refit_snapshots(snapshot)) == 2
        assert authority.validate_export_snapshot(snapshot).ok
        errors, completed = [], []
        worker = MeshDirectOutputWorker(
            1, authority, "authoritative-rust-exact", primary, kind="loose_mod",
            output_path=tmp_path / "mod", manager_profile="dmm",
        )
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors
        assert completed
        body_bytes = (tmp_path / "mod" / primary.path).read_bytes()
        armor_bytes = (tmp_path / "mod" / armor.path).read_bytes()
        assert parse_pac(body_bytes, primary.path).submeshes[0].vertices[0][0] == pytest.approx(0.4, abs=2e-5)
        assert parse_pac(armor_bytes, armor.path).submeshes[-1].vertices[0][0] == pytest.approx(0.7, abs=2e-5)
        assert primary.paz_file.read_bytes() == source
        assert primary.pamt_path.read_bytes() == b"owned archive index"
        metadata = json.loads((tmp_path / "mod/mesh-editor-session.json").read_text())
        assert {asset["path"] for asset in metadata["assets"]} == {primary.path, armor.path}
        assert authority.undo("authoritative-rust-exact").ok
        assert authority._session("authoritative-rust-exact").archive_refit_context is None
        assert authority.redo("authoritative-rust-exact").ok
        assert len(archive_refit_snapshots(authority.capture_export_snapshot("authoritative-rust-exact"))) == 2
    finally:
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def test_archive_refit_load_undo_and_hidden_layers_retain_asset_identity(tmp_path):
    _source, authority, session, _primary, _armor, _loaded = _load_pair(tmp_path, assign_body=False)
    try:
        shadow, sid = session.shadow_service, session.shadow_session_id
        assert shadow.cached_morph_state(sid).driver_submesh_indices == (0,)
        assert shadow.cached_morph_state(sid).profile_id
        context = shadow._session(sid).archive_refit_context
        assert shadow.undo(sid).ok
        assert shadow._session(sid).archive_refit_context is None
        assert shadow.redo(sid).ok
        assert shadow._session(sid).archive_refit_context is context
        layers = shadow._session(sid).geometry_layers
        shadow._session(sid).geometry_layers = tuple(replace(layer, visible=False) for layer in layers)
        assert len(archive_refit_snapshots(shadow.capture_export_snapshot(sid))) == 2
    finally:
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def test_archive_refit_draft_roundtrip_keeps_sources_and_rejects_tampering(tmp_path):
    _source, authority, session, _primary, _armor, _loaded = _load_pair(tmp_path, assign_body=False)
    try:
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        root = tmp_path / "draft"
        payload = save_archive_refit_context(snapshot.archive_refit_context, root, threading.Event())
        restored = load_archive_refit_context(payload, root)
        components = archive_refit_snapshots(replace(snapshot, archive_refit_context=restored))
        assert len(components) == 2
        assert all(session.shadow_service.validate_export_snapshot(item).ok for _entry, item in components)
        legacy = {**payload, "format": "cdmw_archive_refit_v1"}
        legacy.pop("coordinates")
        assert not load_archive_refit_context(legacy, root).neutral_coordinates
        (root / payload["assets"][0]["source"]).write_bytes(b"damaged")
        with pytest.raises(ValueError, match="source"):
            load_archive_refit_context(payload, root)
    finally:
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def test_archive_refit_second_writer_failure_publishes_no_mod(tmp_path):
    _source, authority, session, primary, _armor, _loaded = _load_pair(tmp_path, assign_body=False)
    try:
        session.finish(_request(session, "finish_request", 4))
        service_writer = authority.rebuild_result_from_snapshot
        count = 0

        def fail_second(snapshot):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("armor writer rejected")
            return service_writer(snapshot)

        errors = []
        worker = MeshDirectOutputWorker(1, authority, "authoritative-rust-exact", primary,
                                       kind="loose_mod", output_path=tmp_path / "mod")
        worker.error.connect(lambda _id, message: errors.append(message))
        with patch.object(authority, "rebuild_result_from_snapshot", side_effect=fail_second):
            worker.run()
        assert errors and "armor writer rejected" in errors[0]
        assert not (tmp_path / "mod").exists()
    finally:
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def test_archive_refit_body_slider_moves_bound_armor_and_bakes_both(tmp_path):
    _source, authority, session, _primary, _armor, loaded = _load_pair(tmp_path)
    try:
        _rig_command(session, 3, "select", {"selection": {"source_indices": [0]}})
        _rig_command(session, 4, "morph_create", {"definition": {
            "profile_id": "fit", "profile_name": "Fit", "definition_id": "height", "label": "Height",
            "rule": "move", "axis": "z", "amount": 0.1, "feather": 0,
        }})
        assert session.shadow_service.cached_morph_state(session.shadow_session_id).driver_submesh_indices == (0,)
        _rig_command(session, 6, "refit_bind", {"submesh_indices": loaded["result"]["loaded_parts"]})
        shadow, sid = session.shadow_service, session.shadow_session_id
        before = shadow.working_mesh(sid, clone=True)
        _rig_command(session, 7, "morph_set_value", {"definition_id": "height", "value": 50, "phase": "end"})
        after = shadow.working_mesh(sid, clone=True)
        for old, new in zip(before.submeshes, after.submeshes, strict=True):
            assert new.vertices[0][2] == pytest.approx(old.vertices[0][2] + 0.05)
        _rig_command(session, 8, "morph_bake", {})
        result = session.finish(_request(session, "finish_request", 9))
        assert len(result["exact_output_validation"]["assets"]) == 2
    finally:
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def test_archive_armor_load_assigns_body_when_existing_profile_has_no_driver(tmp_path):
    _source, authority, session, primary, armor, _loaded = _load_pair(tmp_path, assign_body=False)
    try:
        shadow, sid = session.shadow_service, session.shadow_session_id
        incoming = shadow._session(sid).archive_refit_context.assets[-1].source
        _rig_command(session, 3, "undo", {})
        _rig_command(session, 4, "select", {"selection": {"source_indices": [0]}})
        created = _rig_command(session, 5, "morph_create", {"definition": {
            "profile_id": "existing", "profile_name": "Existing", "definition_id": "height",
            "label": "Height", "rule": "move", "axis": "z", "amount": .1, "feather": 0,
        }})
        assert created["state"]["morph_refit"]["profile_id"] == "existing"
        assert created["state"]["morph_refit"]["driver_submesh_indices"] == []
        loaded = _rig_command(session, 6, "refit_choose_archive", {
            "role": "armor", "_primary_entry": primary, "_archive_entry": armor,
            "_archive_snapshot": incoming,
        })
        assert loaded["state"]["morph_refit"]["driver_submesh_indices"] == [0]
        bound = _rig_command(session, 7, "refit_bind", {"submesh_indices": [1]})
        assert bound["state"]["morph_refit"]["refit"]["garment_submesh_indices"] == [1]
    finally:
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


@pytest.mark.parametrize("primary_name", ["body.dds", "a-body.dds"])
@pytest.mark.parametrize("distinct_material", [False, True])
def test_archive_refit_publishes_owned_texture_updates_for_load_undo_and_redo(tmp_path, primary_name, distinct_material):
    from PIL import Image

    body_texture, armor_texture = tmp_path / primary_name, tmp_path / "armor.dds"
    Image.new("RGBA", (4, 4), (200, 50, 40, 255)).save(body_texture)
    Image.new("RGBA", (4, 4), (40, 50, 200, 255)).save(armor_texture)
    _source, authority, session, _primary, _armor, loaded = _load_pair(
        tmp_path, assign_body=False, texture_paths=(body_texture, armor_texture), distinct_material=distinct_material,
    )
    try:
        def materials(state):
            update = state["archive_refit_materials"]
            reference = update["file"]
            data = (session.root / reference["path"]).read_bytes()
            assert hashlib.sha256(data).hexdigest().upper() == reference["sha256"]
            payload = json.loads(data)
            assert payload["key"] == update["key"]
            slots = [(row["material_index"], row["material_slot_index"])
                     for row in payload["material_presentations"]]
            expected = [(0, 0), (1, 1 if distinct_material else 0)]
            assert slots == expected[:len(slots)]
            return payload["textures"]

        textures = materials(loaded["state"])
        assert len(textures) == 2
        assert textures[:1] == session.archive_refit_material_cache["base"]["textures"]
        assert len(tuple(session.root.glob("texture-*.dds"))) == 2
        assert {tuple(texture["material_indices_by_lod"][0]) for texture in textures} == {(0,), (1,)}
        assert {(session.root / texture["file"]["path"]).read_bytes() for texture in textures} == {
            body_texture.read_bytes(), armor_texture.read_bytes(),
        }
        assert len(materials(_rig_command(session, 3, "undo", {})["state"])) == 1
        assert len(materials(_rig_command(session, 4, "redo", {})["state"])) == 2
    finally:
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def test_archive_refit_saved_layer_generation_reopens_with_two_exportable_assets(tmp_path):
    source, authority, session, _primary, _armor, _loaded = _load_pair(tmp_path, assign_body=False)
    reopened = MeshService()
    reopened_id = ""
    try:
        _edit_both(session)
        session.finish(_request(session, "finish_request", 21))
        project_path = tmp_path / "draft/mesh_layer_project.json"
        authority._session("authoritative-rust-exact").mesh_layer_project_path = project_path
        authority.retry_mesh_layer_autosave("authoritative-rust-exact")
        mesh = reopened.load_mesh_bytes(source, "owned-rust-exact.pac", run_roundtrip=True)
        setattr(mesh, "_cdmw_mesh_layer_project_path", str(project_path))
        reopened_id = reopened.open_edit_session(mesh, mode="edit").session_id
        snapshot = reopened.capture_export_snapshot(reopened_id)
        assets = archive_refit_snapshots(snapshot)
        assert len(assets) == 2
        for (_entry, component), expected in zip(assets, (0.4, 0.7), strict=True):
            result, report = reopened.rebuild_result_from_snapshot(component)
            assert report.validation_status == "passed"
            assert parse_pac(result.data, "reopened.pac").submeshes[0].vertices[0][0] == pytest.approx(expected, abs=2e-5)
    finally:
        if reopened_id:
            reopened.close_edit_session(reopened_id, force_without_saving=True)
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)
