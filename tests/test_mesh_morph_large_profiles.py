"""Owned large-profile regressions through persistence, history and the resident core."""

from dataclasses import asdict, replace
import gc
import hashlib
import io
import json
from pathlib import Path
import threading
import time
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from cdmw.domain.mesh.morph_layers import mesh_morph_macros, mesh_morph_profile_definition_fingerprint
from cdmw.domain.mesh.morph import mesh_topology_fingerprint, mesh_morph_driver_topology_fingerprint
from cdmw.domain.mesh.morph_targets import _source_identity
from cdmw.modding import mesh_native_core
from cdmw.core.streaming_json import JsonArray
from cdmw.services.mesh_morph_file_data import MorphProfileFile
from cdmw.services.mesh_morph_profiles import list_mesh_morph_profiles, save_mesh_morph_profile
from cdmw.services import mesh_morph_profiles as profiles_module
from cdmw.services.mesh_morph_draft import capture_morph_draft, persist_morph_draft, load_morph_draft, restore_morph_draft
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_history_files import (
    _mesh_morph_profile_directory_state, _restore_mesh_morph_profile_directory_state,
)
from cdmw.services.mesh_rust_authoring import _capture_owned_profile_tree, _write_owned_profile_tree
from tests.test_mesh_body_controls_generation import _mesh, _skeleton, _palette_bytes
from tests.test_mesh_morph_service import _Settings, _author_command
from tests.test_mesh_morph_layers import _profile
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh, _open, _profile_payload
from tests.test_mesh_refit_saved_setups import _service as _setup_service, _saved_path


def test_streamed_layer_fingerprint_preserves_existing_preset_identity():
    profile = _profile()
    definitions = []
    for definition in sorted(profile.definitions, key=lambda item: item.definition_id):
        payload = asdict(definition)
        for key in ("label", "category", "garment_corrections", "correction_topology_fingerprint",
                    "correction_base_geometry_fingerprint"):
            payload.pop(key)
        definitions.append(payload)
    payload = {"topology_fingerprint": profile.topology_fingerprint, "definitions": definitions,
               "macro_catalog": [{"macro_id": item.macro_id, "contributions": item.contributions}
                                 for item in mesh_morph_macros(profile)]}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert mesh_morph_profile_definition_fingerprint(profile) == expected


def test_streamed_topology_and_skin_identity_preserve_existing_profiles():
    mesh = _mesh()
    payload = [{"index": index, "vertex_count": len(part.vertices), "faces": part.faces}
               for index, part in enumerate(mesh.submeshes)]
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert mesh_topology_fingerprint(mesh) == expected
    part = mesh.submeshes[0]
    part.source_vertex_map_authority = "mapped ä 🐀"
    identity = {name: getattr(part, name, default) for name, default in (
        ("source_vertex_map", ()), ("source_vertex_map_authority", ""),
        ("source_bone_palette", ()), ("source_skin_weight_layout", ""),
        ("bone_indices", ()), ("bone_weights", ()), ("interchange_skin", {}))}
    assert _source_identity(part) == json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def test_profiles_with_more_than_512_controls_keep_all_definitions(tmp_path):
    base = _profile()
    definitions = tuple(replace(base.definitions[0], definition_id=f"control-{index}") for index in range(513))
    mesh = _mesh()
    profile = replace(base, definitions=definitions,
                      topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, definitions))
    save_mesh_morph_profile(tmp_path, profile)
    assert list_mesh_morph_profiles(tmp_path, mesh) == ((profile,), ())


def test_interrupted_stream_save_preserves_the_previous_profile(tmp_path, monkeypatch):
    profile = _profile()
    path = save_mesh_morph_profile(tmp_path, profile)
    previous = path.read_bytes()

    def disk_full(stream, _payload, **_kwargs):
        stream.write("x" * (1024 * 1024))
        raise OSError("injected disk-full failure")

    monkeypatch.setattr(profiles_module, "write_json", disk_full)
    with pytest.raises(OSError, match="disk-full"):
        save_mesh_morph_profile(tmp_path, replace(profile, name="changed"))
    assert path.read_bytes() == previous
    assert list(path.parent.iterdir()) == [path]


def test_disk_backed_fitting_setup_can_be_matched_and_applied(tmp_path):
    service = _setup_service(tmp_path)
    service.data.profile = replace(service.data.profile, name="Large profile " + "x" * (128 * 1024))
    result, state = service.save_refit_setup("mock", "Large setup")
    assert result.ok
    identifier, path = _saved_path(service, state)
    assert path.stat().st_size > 64 * 1024
    result, applied = service.apply_refit_setup("mock", identifier)
    assert result.ok and applied.profile_id == service.data.profile.profile_id


def test_resident_upload_and_runtime_snapshot_accept_files_above_old_wire_limits():
    mesh = _driver_garment_mesh()
    session_id = _open(mesh)
    snapshot = None
    try:
        payload = _profile_payload(mesh)
        # An ignored extension exercises transport size without allocating a
        # million-vertex native model just to cross the former wire threshold.
        payload["large_extension"] = JsonArray(lambda: ("x" * 1024 for _ in range(65 * 1024)))
        result = mesh_native_core.native_mesh_editor_session_command("morph_upload", session_id, payload, timeout_seconds=30)
        assert result is not None and result["status"] == "ok"
        snapshot = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(session_id)
        assert snapshot is not None
        path = Path(snapshot["path"])
        # JSON permits trailing whitespace. Preserve every runtime field while
        # testing the real native snapshot reader beyond its former 256 MiB cap.
        with path.open("ab") as stream:
            for _ in range(257):
                stream.write(b" " * (1024 * 1024))
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        snapshot.update(byte_length=path.stat().st_size, sha256=digest.hexdigest())
        restored = mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(session_id, snapshot, timeout_seconds=30)
        assert restored is not None and restored["geometry_recomposed"] is False
    finally:
        if snapshot is not None:
            assert mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(snapshot, timeout_seconds=30)
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_large_library_uses_shared_disk_history_and_restores_atomically(tmp_path):
    root = tmp_path / "mesh_slider_profiles"
    root.mkdir()
    # Exceed both former limits: a file >8 MiB and a library >64 MiB.
    for index in range(9):
        with (root / f"profile-{index}.json").open("wb") as stream:
            stream.write(b'{"padding":"')
            for _ in range(9):
                stream.write(bytes([65 + index]) * (1024 * 1024))
            stream.write(b'"}')
    before = _mesh_morph_profile_directory_state(root)
    repeated = _capture_owned_profile_tree(root)
    assert sum(len(data) for _, data in before[1]) > 64 * 1024 * 1024
    assert all(isinstance(data, MorphProfileFile) for _, data in before[1])
    assert all(a[1] is b[1] for a, b in zip(before[1], repeated[1]))
    handles = [data._stream for _, data in before[1]]
    refs = [weakref.ref(data) for _, data in before[1]]
    # A shadow receives real files while its snapshots keep shared handles.
    shadow = tmp_path / "shadow"
    _write_owned_profile_tree(shadow, before[1])
    assert _capture_owned_profile_tree(shadow)[2] == before[2]
    (root / "profile-0.json").write_bytes(b'{"changed":true}')
    after = _mesh_morph_profile_directory_state(root)
    _restore_mesh_morph_profile_directory_state(root, existed=True, files=before[1], expected_fingerprint=after[2])
    assert _mesh_morph_profile_directory_state(root)[2] == before[2]
    # External edits still reject the restore before any publication.
    (root / "profile-0.json").write_bytes(b'{"external":true}')
    with pytest.raises(RuntimeError, match="changed outside"):
        _restore_mesh_morph_profile_directory_state(root, existed=True, files=after[1], expected_fingerprint=before[2])
    assert (root / "profile-0.json").read_bytes() == b'{"external":true}'
    del before, repeated, after
    gc.collect()
    assert all(reference() is None for reference in refs)
    # A retained test reference to a file handle deliberately keeps that handle
    # alive; releasing snapshots itself no longer retains their data in Python.
    for handle in handles:
        handle.close()


def _large_body_workflow(tmp_path):
    mesh = _mesh()
    skeleton = _skeleton()
    mesh._cdmw_original_data = _palette_bytes(skeleton)
    for index, part in enumerate(mesh.submeshes):
        copies = 12_000 if index == 0 else 1
        part.vertices *= copies
        part.faces = [(i, i + 1, i + 2) for i in range(0, len(part.vertices), 3)]
        part.bone_indices *= copies
        part.bone_weights *= copies
        part.source_vertex_map = list(range(len(part.vertices)))
        part.normals = [(1.0, 0.0, 0.0)] * len(part.vertices)
        part.uvs = [(0.0, 0.0)] * len(part.vertices)
        part.vertex_count, part.face_count = len(part.vertices), len(part.faces)
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    sessions = []
    try:
        session_id = service.open_edit_session(mesh, mode="edit").session_id
        sessions.append(session_id)
        service._session(session_id).skeleton = skeleton
        assert service.apply_command(session_id, _author_command()).ok
        previous_profile = service.cached_morph_state(session_id).profile_id
        assert service.set_refit_driver(session_id, (0,))[0].ok
        assert service.generate_body_morph_controls(session_id)[0].ok
        profile = service._morph_sessions[session_id].profile
        assert len(profile.definitions) == 5
        assert len({id(item.vertices) for item in profile.definitions}) == 1
        assert service.undo(session_id).ok
        assert service.cached_morph_state(session_id).profile_id == previous_profile
        assert service.redo(session_id).ok
        assert service.cached_morph_state(session_id).profile_id == profile.profile_id
        assert service.set_morph_value(session_id, "upper_arm_l_size", 50.0)[0].ok
        expected = tuple(service.working_mesh(session_id).submeshes[0].vertices)
        service.save_active_morph_profile(session_id)
        path = tmp_path / "mesh_slider_profiles" / "definitions" / f"{profile.profile_id}.json"
        assert path.stat().st_size > 8 * 1024 * 1024
        assert service.undo(session_id).ok and not path.exists()
        assert service.redo(session_id).ok and path.is_file()
        loaded, diagnostics = list_mesh_morph_profiles(path.parent.parent, mesh)
        assert not diagnostics and loaded == (profile,)
        reopened = service.open_edit_session(mesh, mode="edit").session_id
        sessions.append(reopened)
        assert service.activate_morph_profile(reopened, profile.profile_id)[0].ok
        assert service.set_morph_value(reopened, "upper_arm_l_size", 50.0)[0].ok
        assert tuple(service.working_mesh(reopened).submeshes[0].vertices) == expected
        service.save_morph_preset(reopened, "large", "Large Body")
        portable = service.export_morph_preset(reopened, str(tmp_path / "large.json"), "Large Body")
        assert Path(portable).stat().st_size > 8 * 1024 * 1024
        assert service.reset_morph(reopened)[0].ok
        assert service.import_morph_preset(reopened, portable).profile_id == profile.profile_id
        draft = capture_morph_draft(service, service._session(reopened))
        generation = tmp_path / "draft-generation"
        generation.mkdir()
        descriptor = persist_morph_draft(draft, generation, tmp_path)
        assert descriptor["size"] > 8 * 1024 * 1024
        loaded_draft = load_morph_draft(descriptor, tmp_path)
        recovered = service.open_edit_session(service.working_mesh(reopened, clone=True), mode="edit").session_id
        sessions.append(recovered)
        restore_morph_draft(service, service._session(recovered), loaded_draft)
        assert service.cached_morph_state(recovered).values == service.cached_morph_state(reopened).values
        assert tuple(service.working_mesh(recovered).submeshes[0].vertices) == expected
        with (generation / "morph.json").open("r+b") as stream:
            stream.seek(-1, 2)
            stream.write(b" ")
        with pytest.raises(ValueError):
            load_morph_draft(descriptor, tmp_path)
        # Budgets evict older entries, never the sole reversible profile edit.
        service.max_history_bytes = 1
        service.save_active_morph_profile(reopened)
        assert service.session_view(reopened).undo_count == 1
        assert service.undo(reopened).ok
        assert service.redo(reopened).ok
        assert service.set_morph_value(reopened, "upper_arm_l_size", 25.0)[0].ok
        assert service.undo(reopened).ok
        assert dict(service.cached_morph_state(reopened).values)["upper_arm_l_size"] == 50.0
        assert service.redo(reopened).ok
        assert dict(service.cached_morph_state(reopened).values)["upper_arm_l_size"] == 25.0
    finally:
        for session_id in reversed(sessions):
            service.close_edit_session(session_id, force_without_saving=True)


def test_large_body_creation_save_reload_and_history_keep_qt_responsive(tmp_path):
    if not mesh_native_core.native_mesh_core_available():
        pytest.fail("The rebuilt resident mesh core is required for this regression")
    app = QCoreApplication.instance() or QCoreApplication([])
    loop = QEventLoop()
    done = threading.Event()
    failures = []
    ticks = [time.perf_counter()]

    def work():
        try:
            _large_body_workflow(tmp_path)
        except BaseException as exc:
            failures.append(exc)
        finally:
            done.set()

    def tick():
        ticks.append(time.perf_counter())
        if done.is_set():
            loop.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(10)
    thread = threading.Thread(target=work, name="large-body-regression")
    thread.start()
    loop.exec()
    thread.join()
    timer.stop()
    if failures:
        raise failures[0]
    gaps = [end - start for start, end in zip(ticks, ticks[1:])]
    print(f"Large-body Qt heartbeat: {len(ticks)} ticks, maximum gap {max(gaps) * 1000:.1f} ms")
    assert len(ticks) > 100
    assert max(gaps) < 0.250
