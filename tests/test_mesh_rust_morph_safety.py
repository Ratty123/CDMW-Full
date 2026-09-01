from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.services import mesh_rust_authoring as rust_authoring_module
from cdmw.services import mesh_service as mesh_service_module
from cdmw.domain.mesh import MeshEditCommand
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_rust_authoring import (
    RustMeshAuthoringSession,
    RustMeshProtocolError,
    RustMeshValidationError,
)
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_state import _MeshMorphSessionState
from tests.test_mesh_morph_service import (
    _Settings,
    _author_command,
)
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring import _request
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


def _mesh_without_skinning() -> object:
    mesh = _driver_garment_mesh()
    for submesh in mesh.submeshes:
        submesh.bone_indices = []
        submesh.bone_weights = []
    mesh.has_bones = False
    return mesh


def _assert_latest_history_transaction(
    service: MeshService,
    session_id: str,
    *,
    previous_undo_count: int,
    action: str,
    label: str,
) -> None:
    view = service.session_view(session_id)
    assert view.undo_count == previous_undo_count + 1
    assert view.history_entries[-1].action == action
    assert view.history_entries[-1].label == label
    assert view.history_entries[-1].state == "applied"


def _persist_resident_body_profile(settings: _Settings) -> None:
    service = MeshService(settings=settings)
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        assert service.apply_command(session_id, _author_command()).ok
        assert service.apply_command(
            session_id,
            MeshEditCommand("morph_save_profile"),
        ).ok
    finally:
        service.close_edit_session(session_id, force_without_saving=True)


def _open_exact_rust_session(
    root: Path,
) -> tuple[MeshService, RustMeshAuthoringSession]:
    source = _pac_fixture(skinned=True)
    mesh = parse_pac(source, "owned-rust-morph-safety.pac")
    setattr(mesh, "_cdmw_original_data", source)
    setattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", 8)
    setattr(
        mesh,
        "_cdmw_no_op_roundtrip_report",
        {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
    )
    authoritative = MeshService(settings=_Settings(root.parent / "settings.ini"))
    view = authoritative.open_edit_session(
        mesh,
        session_id="authoritative-rust-test",
        mode="edit",
    )
    rust_session = RustMeshAuthoringSession.create(
        SimpleNamespace(
            mesh_service=authoritative,
            active_session_id=view.session_id,
        ),
        root,
        process_generation=7,
    )
    return authoritative, rust_session


def test_shadow_profile_copy_rejects_source_change_during_capture(
    tmp_path: Path,
) -> None:
    settings = _Settings(tmp_path / "settings.ini")
    profile_root = tmp_path / "mesh_slider_profiles"
    definitions = profile_root / "definitions"
    definitions.mkdir(parents=True)
    (definitions / "base.json").write_text("{}", encoding="utf-8")
    session_root = tmp_path / "rust-session"
    session_root.mkdir()
    original_capture = rust_authoring_module._capture_owned_profile_tree
    source_capture_calls = 0

    def capture_with_intervening_change(root: Path | None):
        nonlocal source_capture_calls
        if root == profile_root:
            source_capture_calls += 1
            if source_capture_calls == 2:
                (profile_root / "definitions" / "external.json").write_text(
                    "{}",
                    encoding="utf-8",
                )
        return original_capture(root)

    with (
        patch.object(
                rust_authoring_module,
                "_capture_owned_profile_tree",
                side_effect=capture_with_intervening_change,
        ),
        pytest.raises(
            RustMeshValidationError,
            match="changed while the Rust shadow session was being created",
        ),
    ):
        rust_authoring_module._copy_shadow_morph_profiles(
            settings,
            session_root,
        )

    assert not (session_root / "mesh_slider_profiles").exists()


def test_finish_rejects_runtime_only_authoritative_morph_restore_by_morph_revision_cas(
    tmp_path: Path,
) -> None:
    authoritative = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = authoritative.open_edit_session(
        _mesh_without_skinning(),
        session_id="authoritative-rust-morph-cas",
        mode="edit",
    ).session_id
    earlier_runtime = None
    rust_session = None
    try:
        assert authoritative.apply_command(session_id, _author_command()).ok
        earlier_runtime = authoritative.capture_morph_session_state(session_id)
        assert authoritative.set_refit_driver(session_id, (0, 1))[0].ok
        authoritative.configure_output_policy(
            session_id,
            "free_edit_rebuild",
            output_destination=str(tmp_path / "free-edit-output"),
        )
        rust_session = RustMeshAuthoringSession.create(
            SimpleNamespace(
                mesh_service=authoritative,
                active_session_id=session_id,
            ),
            tmp_path / "rust-session",
            process_generation=17,
        )
        mesh_revision_at_open = authoritative.session_view(session_id).revision
        morph_revision_at_open = rust_session.base_morph_session_revision

        restored = authoritative.install_morph_session_state(
            session_id,
            earlier_runtime,
        )

        assert restored is not None
        assert restored.refit.driver_submesh_indices == ()
        assert authoritative.session_view(session_id).revision == mesh_revision_at_open
        assert (
            authoritative._session(session_id).morph_session_revision
            == morph_revision_at_open + 1
        )
        with pytest.raises(
            RustMeshValidationError,
            match="Morph & Refit state changed while Rust Edit Mesh was open",
        ):
            rust_session.finish(_request(rust_session, "finish_request", 1))

        assert authoritative.session_view(session_id).revision == mesh_revision_at_open
        assert not rust_session.closed
    finally:
        if rust_session is not None and not rust_session.closed:
            rust_session.cancel()
        if earlier_runtime is not None:
            authoritative.dispose_morph_session_state(earlier_runtime)
        authoritative.close_edit_session(session_id, force_without_saving=True)


def test_finish_rejects_valid_unacknowledged_shadow_profile_edit(
    tmp_path: Path,
) -> None:
    settings = _Settings(tmp_path / "settings.ini")
    _persist_resident_body_profile(settings)
    authoritative_profile = (
        tmp_path
        / "mesh_slider_profiles"
        / "definitions"
        / "resident-body.json"
    )
    authoritative_profile_bytes = authoritative_profile.read_bytes()
    authoritative, rust_session = _open_exact_rust_session(tmp_path / "session")
    shadow_profile = (
        rust_session.root
        / "mesh_slider_profiles"
        / "definitions"
        / "resident-body.json"
    )
    profile_payload = json.loads(shadow_profile.read_text(encoding="utf-8"))
    profile_payload["name"] = "Unacknowledged but valid profile edit"
    shadow_profile.write_text(
        json.dumps(profile_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shadow_revision_before = rust_session.shadow_service.session_view(
        rust_session.shadow_session_id
    ).revision
    authoritative_view_before = authoritative.session_view(
        rust_session.authoritative_session_id
    )
    authoritative_vertex_before = authoritative.working_mesh(
        rust_session.authoritative_session_id,
        clone=False,
    ).submeshes[0].vertices[0]

    try:
        with pytest.raises(
            RustMeshProtocolError,
            match="outside an acknowledged CDMW command",
        ):
            rust_session.finish(_request(rust_session, "finish_request", 1))

        assert (
            rust_session.shadow_service.session_view(
                rust_session.shadow_session_id
            ).revision
            == shadow_revision_before + 1
        )
        authoritative_view_after = authoritative.session_view(
            rust_session.authoritative_session_id
        )
        assert authoritative_view_after.revision == authoritative_view_before.revision
        assert authoritative_view_after.undo_count == authoritative_view_before.undo_count
        assert (
            authoritative.working_mesh(
                rust_session.authoritative_session_id,
                clone=False,
            ).submeshes[0].vertices[0]
            == authoritative_vertex_before
        )
        assert authoritative_profile.read_bytes() == authoritative_profile_bytes
        assert not rust_session.closed
    finally:
        if not rust_session.closed:
            rust_session.cancel()
        authoritative.close_edit_session(
            rust_session.authoritative_session_id,
            force_without_saving=True,
        )


def test_profile_publication_detects_staging_race_and_restores_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mesh_slider_profiles"
    shadow = tmp_path / "shadow_profiles"
    (source / "definitions").mkdir(parents=True)
    (shadow / "definitions").mkdir(parents=True)
    source_file = source / "definitions" / "profile.json"
    shadow_file = shadow / "definitions" / "profile.json"
    source_file.write_text('{"name":"Before"}', encoding="utf-8")
    shadow_file.write_text('{"name":"Rust"}', encoding="utf-8")
    publication = rust_authoring_module._MorphProfilePublication(
        source=source,
        shadow=shadow,
        expected_fingerprint=rust_authoring_module._directory_fingerprint(source),
        shadow_expected_fingerprint=rust_authoring_module._directory_fingerprint(shadow),
    )
    publication.prepare()
    real_replace = rust_authoring_module.os.replace

    def race_staging_replace(raw_source, raw_destination) -> None:
        if Path(raw_source) == publication.staging:
            (publication.staging / "definitions" / "profile.json").write_text(  # type: ignore[operator]
                '{"name":"Raced"}',
                encoding="utf-8",
            )
        real_replace(raw_source, raw_destination)

    try:
        with (
            patch.object(
                rust_authoring_module.os,
                "replace",
                side_effect=race_staging_replace,
            ),
            pytest.raises(
                RustMeshValidationError,
                match="changed before validation",
            ),
        ):
            publication.publish()

        assert source_file.read_text(encoding="utf-8") == '{"name":"Before"}'
        assert not publication.published
        assert publication.backup is not None
        assert not publication.backup.exists()
    finally:
        publication.finalize()


def test_profile_publication_rejects_replaced_source_entry(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mesh_slider_profiles"
    shadow = tmp_path / "shadow_profiles"
    (source / "definitions").mkdir(parents=True)
    (shadow / "definitions").mkdir(parents=True)
    (source / "definitions" / "profile.json").write_text(
        '{"name":"Before"}',
        encoding="utf-8",
    )
    (shadow / "definitions" / "profile.json").write_text(
        '{"name":"Rust"}',
        encoding="utf-8",
    )
    publication = rust_authoring_module._MorphProfilePublication(
        source=source,
        shadow=shadow,
        expected_fingerprint=rust_authoring_module._directory_fingerprint(source),
        shadow_expected_fingerprint=rust_authoring_module._directory_fingerprint(shadow),
    )
    publication.prepare()
    displaced = tmp_path / "displaced-source"
    source.rename(displaced)
    (source / "definitions").mkdir(parents=True)
    replacement_file = source / "definitions" / "profile.json"
    replacement_file.write_text('{"name":"Before"}', encoding="utf-8")
    try:
        with pytest.raises(
            RustMeshValidationError,
            match="storage was replaced",
        ):
            publication.publish()
        assert replacement_file.read_text(encoding="utf-8") == '{"name":"Before"}'
    finally:
        publication.finalize()


def test_profile_publication_restores_source_after_backup_identity_check_error(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mesh_slider_profiles"
    shadow = tmp_path / "shadow_profiles"
    (source / "definitions").mkdir(parents=True)
    (shadow / "definitions").mkdir(parents=True)
    source_file = source / "definitions" / "profile.json"
    source_file.write_text('{"name":"Before"}', encoding="utf-8")
    (shadow / "definitions" / "profile.json").write_text(
        '{"name":"Rust"}',
        encoding="utf-8",
    )
    publication = rust_authoring_module._MorphProfilePublication(
        source=source,
        shadow=shadow,
        expected_fingerprint=rust_authoring_module._directory_fingerprint(source),
        shadow_expected_fingerprint=rust_authoring_module._directory_fingerprint(shadow),
    )
    publication.prepare()
    real_identity = rust_authoring_module._mesh_history_directory_identity
    injected = False

    def fail_first_backup_check(path: Path):
        nonlocal injected
        if publication.backup is not None and Path(path) == publication.backup and not injected:
            injected = True
            raise OSError("injected backup identity check failure")
        return real_identity(path)

    try:
        with (
            patch.object(
                rust_authoring_module,
                "_mesh_history_directory_identity",
                side_effect=fail_first_backup_check,
            ),
            pytest.raises(OSError, match="backup identity check failure"),
        ):
            publication.publish()
        assert source_file.read_text(encoding="utf-8") == '{"name":"Before"}'
        assert publication.backup is not None
        assert not publication.backup.exists()
    finally:
        publication.finalize()


def test_profile_publication_rollback_restores_backup_after_quarantine_check_error(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mesh_slider_profiles"
    shadow = tmp_path / "shadow_profiles"
    (source / "definitions").mkdir(parents=True)
    (shadow / "definitions").mkdir(parents=True)
    source_file = source / "definitions" / "profile.json"
    source_file.write_text('{"name":"Before"}', encoding="utf-8")
    (shadow / "definitions" / "profile.json").write_text(
        '{"name":"Rust"}',
        encoding="utf-8",
    )
    publication = rust_authoring_module._MorphProfilePublication(
        source=source,
        shadow=shadow,
        expected_fingerprint=rust_authoring_module._directory_fingerprint(source),
        shadow_expected_fingerprint=rust_authoring_module._directory_fingerprint(shadow),
    )
    publication.prepare()
    publication.publish()
    real_identity = rust_authoring_module._mesh_history_directory_identity
    injected = False

    def fail_first_quarantine_check(path: Path):
        nonlocal injected
        if (
            publication.rejected is not None
            and Path(path) == publication.rejected
            and not injected
        ):
            injected = True
            raise OSError("injected quarantine identity check failure")
        return real_identity(path)

    try:
        with (
            patch.object(
                rust_authoring_module,
                "_mesh_history_directory_identity",
                side_effect=fail_first_quarantine_check,
            ),
            pytest.raises(OSError, match="quarantine identity check failure"),
        ):
            publication.rollback()
        assert source_file.read_text(encoding="utf-8") == '{"name":"Before"}'
        assert publication.backup is not None
        assert not publication.backup.exists()
    finally:
        publication.finalize()


def test_failed_morph_create_prunes_markers_for_destroyed_native_history(
    tmp_path: Path,
) -> None:
    authoritative, rust_session = _open_exact_rust_session(tmp_path / "session")
    service = rust_session.shadow_service
    session_id = rust_session.shadow_session_id
    shadow = service._session(session_id)
    surviving = mesh_service_module._snapshot(shadow, prefer_native=False)
    surviving.history_label = "Surviving Python History"
    old_native = mesh_service_module._snapshot(shadow, prefer_native=False)
    old_native.native_editor_history = True
    old_native.history_label = "Old Native History"
    redo_native = mesh_service_module._snapshot(shadow, prefer_native=False)
    redo_native.native_editor_history = True
    redo_native.history_label = "Redo Native History"
    new_native = mesh_service_module._snapshot(shadow, prefer_native=False)
    new_native.native_editor_history = True
    new_native.history_label = "Failed Create Native History"
    shadow.undo_stack[:] = [surviving, old_native]
    shadow.redo_stack[:] = [redo_native]
    disposed: set[int] = set()
    real_dispose = mesh_service_module._dispose_history_snapshot

    def activate_then_fail(_session_id, _profile_id):
        shadow.morph_session_revision += 1
        shadow.undo_stack.append(new_native)
        for snapshot in tuple(shadow.redo_stack):
            record_dispose(snapshot)
        shadow.redo_stack.clear()
        shadow.native_history_undo_count = 3
        shadow.native_history_redo_count = 0
        shadow.native_history_retained_bytes = 4096
        raise RuntimeError("injected post-native activation failure")

    def record_dispose(snapshot) -> None:
        disposed.add(id(snapshot))
        real_dispose(snapshot)

    try:
        with (
            patch.object(
                service,
                "capture_morph_session_state",
                return_value=_MeshMorphSessionState(present=False),
            ),
            patch.object(
                service,
                "create_morph_definition",
                return_value=SimpleNamespace(profile_id="created-profile"),
            ),
            patch.object(
                service,
                "activate_cached_morph_profile",
                side_effect=activate_then_fail,
            ),
            patch.object(service, "install_morph_session_state", return_value=None),
            patch.object(service, "dispose_morph_session_state", return_value=None),
            patch.object(
                rust_authoring_module,
                "_dispose_history_snapshot",
                side_effect=record_dispose,
            ),
            pytest.raises(RuntimeError, match="post-native activation failure"),
        ):
            rust_session._run_morph_command(
                "morph_create",
                {"definition": {}},
            )

        assert shadow.undo_stack == [surviving]
        assert shadow.redo_stack == []
        assert shadow.native_history_undo_count == 0
        assert shadow.native_history_redo_count == 0
        assert shadow.native_history_retained_bytes == 0
        assert {id(old_native), id(redo_native), id(new_native)} <= disposed
    finally:
        if not rust_session.closed:
            rust_session.cancel()
        authoritative.close_edit_session(
            rust_session.authoritative_session_id,
            force_without_saving=True,
        )


def test_rejected_morph_create_before_activation_preserves_native_history(
    tmp_path: Path,
) -> None:
    authoritative, rust_session = _open_exact_rust_session(tmp_path / "session")
    service = rust_session.shadow_service
    session_id = rust_session.shadow_session_id
    shadow = service._session(session_id)
    native_marker = mesh_service_module._snapshot(shadow, prefer_native=False)
    native_marker.native_editor_history = True
    native_marker.history_label = "Existing Native History"
    shadow.undo_stack[:] = [native_marker]
    shadow.native_history_undo_count = 1
    shadow.native_history_retained_bytes = 512

    try:
        with (
            patch.object(
                service,
                "capture_morph_session_state",
                return_value=_MeshMorphSessionState(present=False),
            ),
            patch.object(
                service,
                "create_morph_definition",
                side_effect=ValueError("invalid Morph definition"),
            ),
            patch.object(service, "install_morph_session_state") as install,
            patch.object(service, "dispose_morph_session_state", return_value=None),
            pytest.raises(ValueError, match="invalid Morph definition"),
        ):
            rust_session._run_morph_command(
                "morph_create",
                {"definition": {}},
            )

        install.assert_not_called()
        assert shadow.undo_stack == [native_marker]
        assert shadow.native_history_undo_count == 1
        assert shadow.native_history_retained_bytes == 512
    finally:
        if not rust_session.closed:
            rust_session.cancel()
        authoritative.close_edit_session(
            rust_session.authoritative_session_id,
            force_without_saving=True,
        )


def test_rejected_morph_activation_preflight_restores_only_cache_and_history(
    tmp_path: Path,
) -> None:
    authoritative, rust_session = _open_exact_rust_session(tmp_path / "session")
    service = rust_session.shadow_service
    session_id = rust_session.shadow_session_id
    shadow = service._session(session_id)
    original_cache = service._morph_sessions[session_id]
    captured_cache = service._clone_morph_session_data(
        original_cache,
        operation="test.rejected_morph_activation_preflight",
    )
    original_profile = captured_cache.profile
    original_known_profiles = dict(captured_cache.known_profiles)
    original_revision = shadow.morph_session_revision
    previous_state = _MeshMorphSessionState(
        present=True,
        native_snapshot={"path": "owned-test-snapshot", "retained_bytes": 1},
        cache=captured_cache,
        retained_bytes=1,
        session_revision=original_revision,
    )
    native_marker = mesh_service_module._snapshot(shadow, prefer_native=False)
    native_marker.native_editor_history = True
    shadow.undo_stack[:] = [native_marker]
    shadow.native_history_undo_count = 1
    shadow.native_history_retained_bytes = 512

    def create_then_preflight_fail(_session_id, **_definition):
        service._morph_sessions[session_id].profile = SimpleNamespace(
            profile_id="too-large-profile"
        )
        shadow.morph_session_revision += 1
        return SimpleNamespace(profile_id="too-large-profile")

    try:
        with (
            patch.object(
                service,
                "capture_morph_session_state",
                return_value=previous_state,
            ),
            patch.object(
                service,
                "create_morph_definition",
                side_effect=create_then_preflight_fail,
            ),
            patch.object(
                service,
                "activate_cached_morph_profile",
                side_effect=RuntimeError(
                    "Resident Morph upload exceeds its 64 MiB limit"
                ),
            ),
            patch.object(service, "install_morph_session_state") as install,
            patch.object(service, "dispose_morph_session_state", return_value=None),
            pytest.raises(RuntimeError, match="exceeds its 64 MiB limit"),
        ):
            rust_session._run_morph_command(
                "morph_create",
                {"definition": {}},
            )

        install.assert_not_called()
        restored_cache = service._morph_sessions[session_id]
        assert restored_cache.profile == original_profile
        assert restored_cache.known_profiles == original_known_profiles
        assert shadow.undo_stack == [native_marker]
        assert shadow.native_history_undo_count == 1
        assert shadow.native_history_retained_bytes == 512
        assert shadow.morph_session_revision == original_revision + 2
    finally:
        if not rust_session.closed:
            rust_session.cancel()
        authoritative.close_edit_session(
            rust_session.authoritative_session_id,
            force_without_saving=True,
        )


def test_oversized_profile_save_is_rejected_before_file_or_history_mutation(
    tmp_path: Path,
) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        assert service.apply_command(session_id, _author_command()).ok
        data = service._morph_sessions[session_id]
        oversized = replace(data.profile, name="x" * (8 * 1024 * 1024))
        data.profile = oversized
        data.known_profiles[oversized.profile_id] = oversized
        before_undo = tuple(service._session(session_id).undo_stack)
        before_redo = tuple(service._session(session_id).redo_stack)

        with pytest.raises(ValueError, match="JSON exceeds"):
            service.save_active_morph_profile(session_id)

        assert not (
            tmp_path
            / "mesh_slider_profiles"
            / "definitions"
            / "resident-body.json"
        ).exists()
        assert tuple(service._session(session_id).undo_stack) == before_undo
        assert tuple(service._session(session_id).redo_stack) == before_redo
    finally:
        service.close_edit_session(session_id, force_without_saving=True)


def test_profile_activation_and_refit_driver_are_visible_undoable_native_history(
    tmp_path: Path,
) -> None:
    settings = _Settings(tmp_path / "settings.ini")
    _persist_resident_body_profile(settings)
    service = MeshService(settings=settings)
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        initial_state = service.morph_state(session_id)
        assert initial_state.profile_id == ""
        assert ("resident-body", "Resident Body") in initial_state.available_profiles

        before_activation = service.session_view(session_id).undo_count
        activated, activated_state = service.activate_morph_profile(
            session_id,
            "resident-body",
        )
        assert activated.ok
        assert activated_state.profile_id == "resident-body"
        _assert_latest_history_transaction(
            service,
            session_id,
            previous_undo_count=before_activation,
            action="morph_upload",
            label="Select Morph Profile",
        )

        assert service.undo(session_id).ok
        undone_activation = service.cached_morph_state(session_id)
        assert undone_activation is not None
        assert undone_activation.profile_id == ""
        assert service.session_view(session_id).history_entries[-1].state == "undone"
        assert service.redo(session_id).ok
        redone_activation = service.cached_morph_state(session_id)
        assert redone_activation is not None
        assert redone_activation.profile_id == "resident-body"

        before_driver = service.session_view(session_id).undo_count
        driver_result, driver_state = service.set_refit_driver(session_id, (0, 1))
        assert driver_result.ok
        assert driver_state.driver_submesh_indices == (0, 1)
        _assert_latest_history_transaction(
            service,
            session_id,
            previous_undo_count=before_driver,
            action="morph_set_driver",
            label="Set Refit Driver",
        )

        assert service.undo(session_id).ok
        undone_driver = service.cached_morph_state(session_id)
        assert undone_driver is not None
        assert undone_driver.profile_id == "resident-body"
        assert undone_driver.driver_submesh_indices == ()
        assert service.session_view(session_id).history_entries[-1].state == "undone"
        assert service.redo(session_id).ok
        redone_driver = service.cached_morph_state(session_id)
        assert redone_driver is not None
        assert redone_driver.driver_submesh_indices == (0, 1)
    finally:
        service.close_edit_session(session_id, force_without_saving=True)


def test_profile_and_preset_file_transactions_restore_runtime_and_files_on_undo_redo(
    tmp_path: Path,
) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    profile_path = (
        tmp_path
        / "mesh_slider_profiles"
        / "definitions"
        / "resident-body.json"
    )
    preset_path = (
        tmp_path
        / "mesh_slider_profiles"
        / "presets"
        / "resident-body"
        / "full.json"
    )
    try:
        assert service.apply_command(session_id, _author_command()).ok
        assert not profile_path.exists()

        before_profile_save = service.session_view(session_id).undo_count
        saved_profile = service.save_active_morph_profile(session_id)
        assert saved_profile.profile_id == "resident-body"
        saved_profile_bytes = profile_path.read_bytes()
        _assert_latest_history_transaction(
            service,
            session_id,
            previous_undo_count=before_profile_save,
            action="morph_save_profile",
            label="Save Morph Profile",
        )
        assert service.undo(session_id).ok
        assert not profile_path.exists()
        assert service.cached_morph_state(session_id).profile_id == "resident-body"  # type: ignore[union-attr]
        assert service.redo(session_id).ok
        assert profile_path.read_bytes() == saved_profile_bytes
        assert service.cached_morph_state(session_id).profile_id == "resident-body"  # type: ignore[union-attr]

        assert service.set_morph_value(
            session_id,
            "volume",
            65.0,
            phase="end",
            change_id="preset-runtime-state",
        )[0].ok
        before_preset_save = service.session_view(session_id).undo_count
        saved_preset = service.save_morph_preset(session_id, "full", "Full")
        assert saved_preset.preset_id == "full"
        saved_preset_bytes = preset_path.read_bytes()
        _assert_latest_history_transaction(
            service,
            session_id,
            previous_undo_count=before_preset_save,
            action="morph_save_preset",
            label="Save Morph Preset",
        )
        assert service.undo(session_id).ok
        assert not preset_path.exists()
        assert service.cached_morph_state(session_id).values == (("volume", 65.0),)  # type: ignore[union-attr]
        assert service.redo(session_id).ok
        assert preset_path.read_bytes() == saved_preset_bytes
        assert service.cached_morph_state(session_id).values == (("volume", 65.0),)  # type: ignore[union-attr]

        assert service.set_morph_value(
            session_id,
            "volume",
            20.0,
            phase="end",
            change_id="before-preset-apply",
        )[0].ok
        assert service.apply_morph_preset(session_id, "full")[0].ok
        applied_preset_state = service.cached_morph_state(session_id)
        assert applied_preset_state is not None
        assert applied_preset_state.preset_id == "full"
        assert applied_preset_state.values == (("volume", 65.0),)

        before_preset_delete = service.session_view(session_id).undo_count
        assert service.delete_morph_preset(session_id, "full")
        _assert_latest_history_transaction(
            service,
            session_id,
            previous_undo_count=before_preset_delete,
            action="morph_delete_preset",
            label="Delete Morph Preset",
        )
        assert not preset_path.exists()
        assert service.cached_morph_state(session_id).preset_id == ""  # type: ignore[union-attr]
        assert service.undo(session_id).ok
        assert preset_path.read_bytes() == saved_preset_bytes
        assert service.cached_morph_state(session_id).preset_id == "full"  # type: ignore[union-attr]
        assert service.cached_morph_state(session_id).values == (("volume", 65.0),)  # type: ignore[union-attr]
        assert service.redo(session_id).ok
        assert not preset_path.exists()
        assert service.cached_morph_state(session_id).preset_id == ""  # type: ignore[union-attr]

        before_profile_delete = service.session_view(session_id).undo_count
        assert service.delete_morph_profile(session_id, "resident-body")
        _assert_latest_history_transaction(
            service,
            session_id,
            previous_undo_count=before_profile_delete,
            action="morph_delete_profile",
            label="Delete Morph Profile",
        )
        deleted_profile_state = service.cached_morph_state(session_id)
        assert deleted_profile_state is not None
        assert deleted_profile_state.profile_id == ""
        assert not profile_path.exists()
        assert service.undo(session_id).ok
        assert profile_path.read_bytes() == saved_profile_bytes
        restored_profile_state = service.cached_morph_state(session_id)
        assert restored_profile_state is not None
        assert restored_profile_state.profile_id == "resident-body"
        assert restored_profile_state.values == (("volume", 65.0),)
        assert service.redo(session_id).ok
        assert not profile_path.exists()
        assert service.cached_morph_state(session_id).profile_id == ""  # type: ignore[union-attr]
    finally:
        service.close_edit_session(session_id, force_without_saving=True)


def test_post_commit_morph_snapshot_cleanup_failure_warns_without_profile_rollback(
    tmp_path: Path,
) -> None:
    original_profile = (
        tmp_path
        / "mesh_slider_profiles"
        / "definitions"
        / "original.json"
    )
    original_profile.parent.mkdir(parents=True)
    original_profile.write_text('{"name":"Original"}', encoding="utf-8")
    authoritative, rust_session = _open_exact_rust_session(tmp_path / "session")
    rust_profile = (
        rust_session.root
        / "mesh_slider_profiles"
        / "definitions"
        / "rust.json"
    )
    (rust_session.root / "mesh_slider_profiles" / "definitions" / "original.json").unlink()
    rust_profile.write_text('{"name":"Rust"}', encoding="utf-8")
    rust_session.acknowledged_morph_profile_fingerprint = (
        rust_authoring_module._directory_fingerprint(
            rust_session.root / "mesh_slider_profiles"
        )
    )
    authoritative_rust_profile = (
        tmp_path
        / "mesh_slider_profiles"
        / "definitions"
        / "rust.json"
    )
    cleanup_states: list[object] = []
    publication_seen: list[tuple[int, bool, bool]] = []

    def fail_after_commit(state: object) -> None:
        cleanup_states.append(state)
        publication_seen.append(
            (
                authoritative.session_view("authoritative-rust-test").revision,
                original_profile.exists(),
                authoritative_rust_profile.exists(),
            )
        )
        raise RuntimeError("injected post-commit Morph snapshot cleanup failure")

    try:
        with patch.object(
            rust_session.shadow_service,
            "dispose_morph_session_state",
            side_effect=fail_after_commit,
        ):
            result = rust_session.finish(
                _request(rust_session, "finish_request", 1)
            )

        assert result["status"] == "accepted"
        assert result["authoritative_revision"] == 1
        assert publication_seen == [(1, False, True)]
        assert cleanup_states
        assert any(
            "injected post-commit Morph snapshot cleanup failure" in warning
            for warning in result["warnings"]
        )
        assert not original_profile.exists()
        assert authoritative_rust_profile.read_text(encoding="utf-8") == '{"name":"Rust"}'

        assert rust_session.shadow_service.retry_deferred_morph_session_state_disposals() == 0
        cleaned_state = cleanup_states[0]
        assert cleaned_state.native_snapshot is None  # type: ignore[attr-defined]
        assert cleaned_state.retained_bytes == 0  # type: ignore[attr-defined]
    finally:
        if not rust_session.closed:
            rust_session.cancel()
        authoritative.close_edit_session(
            "authoritative-rust-test",
            force_without_saving=True,
        )
