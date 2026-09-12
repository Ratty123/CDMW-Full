from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.services.mesh_archive_refit import (
    load_archive_refit_materials, save_archive_refit_materials,
)
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, _canonical_json_bytes
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_archive_refit import _edit_both, _entry, _load_pair
from tests.test_mesh_rust_authoring_exact_output import _request, _rig_command


def _image(path, color):
    Image.new("RGBA", (4, 4), (*color, 255)).save(path)
    return path


def _textures(editor, state=None):
    path = editor.root / state["archive_refit_materials"]["file"]["path"] if state else editor.manifest_path
    payload = json.loads(path.read_text())
    return {(tuple(row["material_indices_by_lod"][0]), row["role"]): row["file"]["sha256"]
            for row in payload["textures"]}


@pytest.mark.parametrize("legacy", [False, True])
def test_refit_draft_materials_survive_cache_loss_or_warn_for_legacy_drafts(tmp_path, legacy):
    body = _image(tmp_path / "body.dds", (180, 20, 30))
    armor = _image(tmp_path / "armor.dds", (30, 20, 180))
    source, authority, editor, primary, armor_entry, loaded = _load_pair(
        tmp_path, assign_body=False, texture_paths=(body, armor),
    )
    resumed = MeshService()
    resumed_id = ""
    reopened = None
    try:
        # The archive command carries direct roles and typed, nested layer inputs.
        incoming = copy.deepcopy(editor.shadow_service._session(editor.shadow_session_id).archive_refit_context.assets[-1].source)
        normal = _image(tmp_path / "armor_n.dds", (128, 128, 255))
        glow = _image(tmp_path / "armor_e.dds", (20, 200, 100))
        preview = _image(tmp_path / "armor_n.png", (128, 128, 255))
        mask = _image(tmp_path / "layer_mask.png", (100, 100, 100))
        part = incoming.mesh.submeshes[0]
        part.preview_normal_texture_dds_path = str(normal)
        part.preview_emissive_texture_dds_path = str(glow)
        part.preview_material_texture_inputs = (PreviewMaterialTextureInput(
            slot_kind="normal", confidence="gltf", source_dds_path=str(normal),
            preview_texture_path=str(preview), source_texture_path="character/texture/armor_n.dds",
            material_parameters=(PreviewMaterialParameterInput(
                parameter_name="layerMask", texture_path=str(mask), numeric_value=.25,
            ),),
        ),)
        _rig_command(editor, 3, "undo", {})
        loaded = _rig_command(editor, 4, "refit_choose_archive", {
            "role": "armor", "_primary_entry": primary, "_archive_entry": armor_entry,
            "_archive_snapshot": incoming,
        })
        expected = _textures(editor, loaded["state"])
        assert {role for _parts, role in expected} >= {"base_color", "normal", "emissive"}
        editor.finish(_request(editor, "finish_request", 5))
        project = tmp_path / "draft/mesh_layer_project.json"
        authority._session(editor.authoritative_session_id).mesh_layer_project_path = project
        authority.retry_mesh_layer_autosave(editor.authoritative_session_id)
        descriptor = json.loads(project.read_text())
        manifest = project.parent / descriptor["current_generation"] / "generation.json"
        generation = json.loads(manifest.read_text())
        files = generation["archive_refit_material_files"]["files"]
        assert len(files) == 6  # Repeated normal references own one file.
        originals = {str(path): path.read_bytes() for path in (body, armor, normal, glow, preview, mask)}
        for original, record in files.items():
            owned = project.parent / record["path"]
            assert owned.name == Path(original).name
            assert owned.read_bytes() == originals[original]
            assert hashlib.sha256(owned.read_bytes()).hexdigest() == record["sha256"]
        if legacy:
            generation.pop("archive_refit_material_files")
            manifest.write_text(json.dumps(generation))
            descriptor["current_generation_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
            project.write_text(json.dumps(descriptor))
        # Preserve the body's cached map so legacy partial availability is exercised.
        for path in (armor, normal, glow, preview, mask):
            path.unlink()
        editor.cancel()
        authority.close_edit_session(editor.authoritative_session_id, force_without_saving=True)
        mesh = resumed.load_mesh_bytes(source, primary.path, run_roundtrip=True)
        mesh._cdmw_mesh_layer_project_path = str(project)
        resumed_id = resumed.open_edit_session(mesh, mode="edit").session_id
        reopened = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=resumed, active_session_id=resumed_id),
            tmp_path / "reopened", process_generation=22,
        )
        status = json.loads(reopened.manifest_path.read_text())["texture_status"]
        if legacy:
            assert status["available"] and status["resource_count"] == 1
            assert "missing" in status["reason"] and "armor.dds" in status["reason"]
        else:
            assert _textures(reopened) == expected
            assert status["reason"] == ""
            restored = resumed.working_mesh(resumed_id).submeshes[1].preview_material_texture_inputs[0]
            assert isinstance(restored, PreviewMaterialTextureInput)
            assert Path(restored.preview_texture_path).read_bytes() == originals[str(preview)]
            assert restored.source_texture_path == "character/texture/armor_n.dds"
            assert restored.material_parameters[0].numeric_value == .25
            assert Path(restored.material_parameters[0].texture_path).read_bytes() == originals[str(mask)]
            # Resaving consumes the owned files, after the original cache is gone.
            _edit_both(reopened)
            reopened.finish(_request(reopened, "finish_request", 21))
            resumed.retry_mesh_layer_autosave(resumed_id)
        assert primary.paz_file.read_bytes() == source
    finally:
        if reopened:
            reopened.cancel()
        if resumed_id:
            resumed.close_edit_session(resumed_id, force_without_saving=True)
        if not editor.closed:
            editor.cancel()
        if editor.authoritative_session_id in authority._sessions:
            authority.close_edit_session(editor.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize("damage", ["checksum", "escape", "omitted", "duplicate_checksum", "size"])
def test_refit_material_record_rejects_damage_before_rebasing_bindings(tmp_path, damage):
    image = _image(tmp_path / "armor.dds", (1, 2, 3))
    snapshot = {"submeshes": [{"metadata": {"extra_attrs": {"preview_texture_dds_path": str(image)}}}]}
    project = tmp_path / "draft"
    payload = save_archive_refit_materials(snapshot, project, threading.Event())
    before = copy.deepcopy(snapshot)
    record = payload["files"][str(image)]
    if damage == "checksum":
        path = project / record["path"]
        path.write_bytes(b"x" * path.stat().st_size)
    elif damage == "escape":
        record["path"] = str(image)
    elif damage == "duplicate_checksum":
        payload["files"]["duplicate"] = {**record, "sha256": "0" * 64}
    elif damage == "size":
        record["size"] = None
    else:
        payload["files"].clear()
    with pytest.raises(ValueError, match="material"):
        load_archive_refit_materials(snapshot, payload, project)
    assert snapshot == before


def test_missing_material_does_not_replace_the_saved_draft(tmp_path):
    body = _image(tmp_path / "body.dds", (1, 2, 3))
    armor = _image(tmp_path / "armor.dds", (4, 5, 6))
    _source, authority, editor, _primary, _armor, _loaded = _load_pair(
        tmp_path, assign_body=False, texture_paths=(body, armor),
    )
    try:
        editor.finish(_request(editor, "finish_request", 3))
        sid = editor.authoritative_session_id
        project = tmp_path / "draft/mesh_layer_project.json"
        authority._session(sid).mesh_layer_project_path = project
        authority.retry_mesh_layer_autosave(sid)
        before = project.read_bytes()
        armor.unlink()
        with pytest.raises(ValueError, match="material is missing"):
            authority.retry_mesh_layer_autosave(sid)
        assert project.read_bytes() == before
    finally:
        editor.cancel()
        authority.close_edit_session(editor.authoritative_session_id, force_without_saving=True)


def test_refit_draft_material_copy_is_cancelled_before_generation_publication(tmp_path):
    from cdmw.models import RunCancelled
    from cdmw.services import atomic_file_service
    from cdmw.services.mesh_layer_project_service import save_mesh_layer_project

    body = _image(tmp_path / "body.dds", (1, 2, 3))
    armor = _image(tmp_path / "armor.dds", (4, 5, 6))
    _source, authority, editor, _primary, _armor, _loaded = _load_pair(
        tmp_path, assign_body=False, texture_paths=(body, armor),
    )
    try:
        editor.finish(_request(editor, "finish_request", 3))
        sid = editor.authoritative_session_id
        project = tmp_path / "draft/mesh_layer_project.json"
        authority._session(sid).mesh_layer_project_path = project
        authority.retry_mesh_layer_autosave(sid)
        before = project.read_bytes()
        _image(armor, (9, 8, 7))
        stop = threading.Event()
        original_copy = atomic_file_service.atomic_copy_file

        def cancel_copy(*args, **kwargs):
            original_copy(*args, **kwargs)
            stop.set()

        current = authority._session(sid)
        with patch.object(atomic_file_service, "atomic_copy_file", side_effect=cancel_copy):
            with pytest.raises(RunCancelled):
                save_mesh_layer_project(
                    session_id=sid, mesh=current.working_mesh, project_path=project,
                    source_asset_sha256=hashlib.sha256(current.original_data).hexdigest(),
                    layers=(), active_layer_id="base", copy_counter=0,
                    mesh_revision=current.revision, layer_revision=0,
                    archive_refit_context=current.archive_refit_context, stop_event=stop,
                )
        assert project.read_bytes() == before
    finally:
        editor.cancel()
        authority.close_edit_session(editor.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize("failure", ["size", "write", "cancel"])
def test_rejected_refit_materials_do_not_block_the_next_valid_import(tmp_path, failure):
    from cdmw.services import mesh_rust_authoring as rust

    body = _image(tmp_path / "body.dds", (1, 2, 3))
    armor = _image(tmp_path / "armor.dds", (4, 5, 6))
    third = _image(tmp_path / "helmet.dds", (7, 8, 9))
    source, authority, editor, primary, _armor, _loaded = _load_pair(
        tmp_path, assign_body=False, texture_paths=(body, armor),
    )
    try:
        current = editor.shadow_service._session(editor.shadow_session_id)
        incoming = replace(current.archive_refit_context.assets[-1].source,
                           mesh=copy.deepcopy(current.archive_refit_context.assets[-1].source.mesh))
        incoming.mesh.submeshes[0].preview_texture_dds_path = str(third)
        cache = copy.deepcopy(editor.archive_refit_material_cache)
        references = copy.deepcopy(editor.archive_refit_material_references)
        revision = current.revision
        stop = threading.Event()
        original_write = rust._atomic_write_payload

        def write(*args, **kwargs):
            if str(args[1]).startswith("material-state-"):
                if failure == "write":
                    raise OSError("owned material write failed")
                if failure == "cancel":
                    stop.set()
            return original_write(*args, **kwargs)

        limit = len(_canonical_json_bytes(cache[current.archive_refit_context.context_id])) + 700
        request = _request(editor, "command_request", 20)
        request.update(command="refit_choose_archive", arguments={
            "role": "armor", "_primary_entry": primary,
            "_archive_entry": _entry(tmp_path, "helmet.pac", source), "_archive_snapshot": incoming,
        })
        with patch.object(rust, "_RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES", limit if failure == "size" else 16*1024*1024), \
             patch.object(rust, "_atomic_write_payload", side_effect=write):
            with pytest.raises((ValueError, RuntimeError, OSError)):
                editor.run_command(request, stop_event=stop)
        assert current.revision == revision
        assert editor.archive_refit_material_cache == cache
        assert editor.archive_refit_material_references == references
        assert len(editor.state_payload(include_document=True)["archive_refit_assets"]) == 2
        incoming.mesh.submeshes[0].preview_texture_dds_path = ""
        with patch.object(rust, "_RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES", limit):
            accepted = _rig_command(editor, 21, "refit_choose_archive", {
                "role": "armor", "_primary_entry": primary,
                "_archive_entry": _entry(tmp_path, "valid-small.pac", source), "_archive_snapshot": incoming,
            })
        assert len(accepted["state"]["archive_refit_assets"]) == 3
        assert current.revision > revision
    finally:
        editor.cancel()
        authority.close_edit_session(editor.authoritative_session_id, force_without_saving=True)
