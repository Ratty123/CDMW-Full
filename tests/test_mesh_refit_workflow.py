from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_rust_authoring import RustMeshCancellationError, RustMeshValidationError
from cdmw.services.mesh_morph_profiles import MESH_MORPH_BUNDLE_FORMAT
from cdmw.services.mesh_refit_loading import append_refit_mesh
from tests.test_mesh_morph_service import _Settings, _author_command
from tests.test_mesh_rust_authoring import _request
from tests.test_mesh_rust_morph_safety import _open_exact_rust_session
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


def _positions(service, session_id):
    return [list(part.vertices) for part in service.working_mesh(session_id, clone=True).submeshes]


def _saved_bundle(root):
    service = MeshService(settings=_Settings(root / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    assert service.apply_command(session_id, _author_command()).ok
    assert service.set_morph_value(session_id, "volume", 65.0, phase="end")[0].ok
    bundle = root / "shared" / "body.json"
    service.export_morph_preset(session_id, str(bundle), "My body")
    return service, session_id, bundle


def test_save_preset_also_saves_its_profile_and_portable_load_needs_no_selection(tmp_path):
    source, source_id, bundle = _saved_bundle(tmp_path / "source")
    target = MeshService(settings=_Settings(tmp_path / "target" / "settings.ini"))
    target_id = target.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        source.save_morph_preset(source_id, "my-body", "My body")
        assert (tmp_path / "source/mesh_slider_profiles/definitions/resident-body.json").is_file()
        assert json.loads(bundle.read_text())["format"] == MESH_MORPH_BUNDLE_FORMAT
        before = _positions(target, target_id)
        state = target.import_morph_preset(target_id, str(bundle))
        assert state.profile_id == "resident-body"
        assert dict(state.values) == {"volume": 65.0}
        assert state.unbaked
        assert _positions(target, target_id) == _positions(source, source_id)
        library = tmp_path / "target/mesh_slider_profiles"
        files = {p.relative_to(library): p.read_bytes() for p in library.rglob("*.json")}
        assert len(files) == 2
        assert target.undo(target_id).ok
        assert _positions(target, target_id) == before
        assert not list(library.rglob("*.json"))
        assert target.redo(target_id).ok
        assert _positions(target, target_id) == _positions(source, source_id)
        assert {p.relative_to(library): p.read_bytes() for p in library.rglob("*.json")} == files
    finally:
        source.close_edit_session(source_id)
        target.close_edit_session(target_id)


@pytest.mark.parametrize("bad", ["topology", "range", "missing", "format"])
def test_bad_preset_keeps_mesh_and_library_unchanged(tmp_path, bad):
    source, source_id, bundle = _saved_bundle(tmp_path / "source")
    target = MeshService(settings=_Settings(tmp_path / "target/settings.ini"))
    target_id = target.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        payload = json.loads(bundle.read_text())
        if bad == "topology":
            payload["profile"]["topology_fingerprint"] = "wrong"
        elif bad == "range":
            payload["preset"]["values"]["volume"] = 9999
        elif bad == "missing":
            payload["preset"]["values"] = {}
        else:
            payload["format"] = "wrong"
        bundle.write_text(json.dumps(payload))
        before = _positions(target, target_id)
        with pytest.raises((ValueError, RuntimeError)):
            target.import_morph_preset(target_id, str(bundle))
        assert _positions(target, target_id) == before
        assert not list((tmp_path / "target").rglob("*.json"))
    finally:
        source.close_edit_session(source_id)
        target.close_edit_session(target_id)


def test_import_second_file_failure_rolls_back_geometry_profile_and_history(tmp_path):
    source, source_id, bundle = _saved_bundle(tmp_path / "source")
    target = MeshService(settings=_Settings(tmp_path / "target/settings.ini"))
    target_id = target.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        before = _positions(target, target_id)
        with patch("cdmw.services.mesh_service_morph.save_mesh_morph_preset", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                target.import_morph_preset(target_id, str(bundle))
        assert _positions(target, target_id) == before
        assert not target._session(target_id).undo_stack
        assert not list((tmp_path / "target").rglob("*.json"))
    finally:
        source.close_edit_session(source_id)
        target.close_edit_session(target_id)


def test_refit_setup_requires_baked_preview_but_garment_settings_remain_live(tmp_path):
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        assert service.apply_command(session_id, _author_command()).ok
        assert service.set_refit_driver(session_id, (0, 1))[0].ok
        assert service.bind_refit(session_id, (2,))[0].ok
        assert service.set_morph_value(session_id, "volume", 50.0, phase="end")[0].ok
        for operation, indices in [(service.set_refit_driver, (0, 1)), (service.bind_refit, (2,))]:
            with pytest.raises(RuntimeError, match="Bake or Reset"):
                operation(session_id, indices)
        assert service.configure_refit(session_id, (2,), enabled=True, intensity_percent=50,
                                       mode="surface", clearance_percent=0)[0].ok
        assert service.reset_morph(session_id)[0].ok
    finally:
        service.close_edit_session(session_id)


def _obj(path: Path):
    path.write_text("o shirt\nv 0 0 0.1\nv 1 0 0.1\nv 0 1 0.1\nvt 0 0\nvt 1 0\nvt 0 1\nusemtl cloth\nf 1/1 2/2 3/3\n")
    return path


def test_append_custom_mesh_is_additive_and_reads_source_without_writing(tmp_path):
    path = _obj(tmp_path / "armor.obj")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    current = _driver_garment_mesh()
    original = [list(part.vertices) for part in current.submeshes]
    combined, indices = append_refit_mesh(current, str(path), "armor")
    assert indices == (len(original),)
    assert [part.vertices for part in combined.submeshes[:len(original)]] == original
    assert combined.submeshes[len(original)].name.startswith("Armor / armor /")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(RunCancelled):
        append_refit_mesh(_driver_garment_mesh(), str(path), "body", stop_event=stopped)


def test_host_load_body_and_armor_preserves_parts_undo_and_exact_policy(tmp_path):
    authoritative, editor = _open_exact_rust_session(tmp_path / "session")
    path = _obj(tmp_path / "armor.obj")
    request_id = 0
    def command(command_name, **args):
        nonlocal request_id
        request_id += 1
        request = _request(editor, "command", request_id)
        request.update(command=command_name, arguments=args)
        return editor.run_command(request)
    try:
        before = _positions(editor.shadow_service, editor.shadow_session_id)
        with pytest.raises(RustMeshValidationError, match="Free Edit"):
            command("refit_load_mesh", path=str(path), role="body")
        command("configure_output_policy", policy="free_edit_rebuild", destination=str(tmp_path / "output"))
        command("refit_load_mesh", path=str(path), role="body")
        one = _positions(editor.shadow_service, editor.shadow_session_id)
        assert one[:len(before)] == before and len(one) == len(before) + 1
        body = len(before)
        command("select", selection={"source_indices": [body]})
        command("morph_create", definition={"profile_id": "fit", "profile_name": "Fit",
            "definition_id": "height", "label": "Height", "rule": "move", "axis": "z",
            "amount": 0.1, "feather": 0})
        command("refit_set_driver", submesh_indices=[body])
        command("refit_load_mesh", path=str(path), role="armor")
        assert len(_positions(editor.shadow_service, editor.shadow_session_id)) == len(before) + 2
        command("undo")
        assert _positions(editor.shadow_service, editor.shadow_session_id) == one
        command("redo")
        assert len(_positions(editor.shadow_service, editor.shadow_session_id)) == len(before) + 2
        assert editor.shadow_service.cached_morph_state(editor.shadow_session_id).profile_id == "fit"
        command("refit_bind", submesh_indices=[body + 1])
        command("morph_set_value", definition_id="height", value=50.0, phase="end")
        changed = _positions(editor.shadow_service, editor.shadow_session_id)
        assert changed[:len(before)] == before
        assert changed[body + 1][0][2] == pytest.approx(0.15)
        command("morph_bake")
        command("morph_save_preset", preset_id="baked", name="Baked")
        assert len(authoritative.working_mesh("authoritative-rust-test", clone=True).submeshes) == len(before)
        result = editor.finish(_request(editor, "finish_request", request_id + 1))
        assert result["status"] == "accepted"
        assert len(authoritative.working_mesh("authoritative-rust-test", clone=True).submeshes) == len(before) + 2
    finally:
        editor.cancel()
        authoritative.close_edit_session("authoritative-rust-test")


@pytest.mark.parametrize("failure", ["invalid_mesh", "cancel_prepared"])
def test_host_refit_load_failure_keeps_the_current_scene(tmp_path, failure):
    from cdmw.services import mesh_rust_authoring as owner
    authoritative, editor = _open_exact_rust_session(tmp_path / "session")
    path = _obj(tmp_path / "armor.obj")
    stopped = threading.Event()
    try:
        request = _request(editor, "command", 1)
        request.update(command="configure_output_policy", arguments={
            "policy": "free_edit_rebuild", "destination": str(tmp_path / "output"),
        })
        editor.run_command(request)
        before = _positions(editor.shadow_service, editor.shadow_session_id)
        request = _request(editor, "command", 2)
        request.update(command="refit_load_mesh", arguments={"path": str(path), "role": "armor"})
        if failure == "invalid_mesh":
            path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
            with pytest.raises(RustMeshValidationError, match="Cannot add armor"):
                editor.run_command(request)
        else:
            original = owner.stage_refit_morph_runtime
            def cancel_after_preparing(*args):
                result = original(*args)
                stopped.set()
                return result
            with patch.object(owner, "stage_refit_morph_runtime", side_effect=cancel_after_preparing):
                with pytest.raises(RustMeshCancellationError):
                    editor.run_command(request, stop_event=stopped)
        assert _positions(editor.shadow_service, editor.shadow_session_id) == before
        assert not (tmp_path / "output").exists()
    finally:
        editor.cancel()
        authoritative.close_edit_session("authoritative-rust-test")
