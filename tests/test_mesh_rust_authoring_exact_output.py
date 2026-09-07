from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.modding.mesh_pac_builder import _patch_exact_pac_skin_weights
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_rust_authoring import (
    RUST_MESH_CANDIDATE,
    RUST_MESH_EDITOR_PROTOCOL,
    RustMeshAuthoringSession,
    RustMeshValidationError,
)
from cdmw.services.mesh_service import MeshService
from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring import _with_resolvable_bone_palette


def _request(
    session: RustMeshAuthoringSession,
    event: str,
    request_id: int,
) -> dict[str, object]:
    return {
        "event": event,
        "protocol": RUST_MESH_EDITOR_PROTOCOL,
        "session_id": session.session_id,
        "request_id": request_id,
        "base_revision": session.shadow_service.session_view(
            session.shadow_session_id
        ).revision,
        "process_generation": session.process_generation,
    }


def _candidate_reference(
    session: RustMeshAuthoringSession,
    *,
    request_id: int,
    first_x: float,
) -> dict[str, object]:
    mesh = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
    submeshes: list[dict[str, object]] = []
    for submesh_index, submesh in enumerate(mesh.submeshes):
        positions = [list(row) for row in submesh.vertices]
        if submesh_index == 0:
            positions[0][0] = first_x
        submeshes.append(
            {
                "positions": positions,
                "normals": [list(row) for row in submesh.normals],
                "uvs": [list(row) for row in submesh.uvs],
                "indices": [index for face in submesh.faces for index in face],
            }
        )
    payload = {
        "schema": RUST_MESH_CANDIDATE,
        "session_id": session.session_id,
        "submeshes": submeshes,
        "selection": {
            "vertices_by_submesh": {"0": [0]},
            "edges_by_submesh": {},
            "faces_by_submesh": {},
            "source_indices": [0],
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    name = f"candidate-{request_id}-exact-output.json"
    (session.root / name).write_bytes(encoded)
    return {
        "path": name,
        "data_type": "mesh_candidate_json",
        "count": len(submeshes),
        "byte_length": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest().upper(),
        "content_type": "application/json",
    }


def _open_exact_session(
    root: Path,
    *,
    resolved_rig: bool = False,
    base_texture_path: Path | None = None,
) -> tuple[bytes, MeshService, RustMeshAuthoringSession]:
    source = _pac_fixture(skinned=True)
    skeleton = None
    if resolved_rig:
        skeleton = Skeleton(
            path="character/model/owned-rust-exact.pab",
            bones=[
                Bone(
                    index=index,
                    name=f"Bone {index}",
                    name_hash=0xA2000000 + index,
                )
                for index in range(8)
            ],
            bone_count=8,
        )
        source = _with_resolvable_bone_palette(
            source,
            tuple(bone.name_hash for bone in skeleton.bones),
        )
    mesh = parse_pac(source, "owned-rust-exact.pac")
    setattr(mesh, "_cdmw_original_data", source)
    setattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", 8)
    setattr(
        mesh,
        "_cdmw_no_op_roundtrip_report",
        {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
    )
    if base_texture_path is not None:
        mesh.submeshes[0].preview_texture_dds_path = str(base_texture_path)
    authoritative = MeshService()
    view = authoritative.open_edit_session(
        mesh,
        session_id="authoritative-rust-exact",
        mode="edit",
    )
    if skeleton is not None:
        authoritative.attach_skeleton(
            view.session_id,
            skeleton,
            source_path=skeleton.path,
        )
    assert view.output_policy == "exact_game_asset"
    session = RustMeshAuthoringSession.create(
        SimpleNamespace(
            mesh_service=authoritative,
            active_session_id=view.session_id,
        ),
        root,
        process_generation=11,
    )
    return source, authoritative, session


def _rig_command(
    session: RustMeshAuthoringSession,
    request_id: int,
    command: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    request = _request(session, "command_request", request_id)
    request.update(command=command, arguments=arguments)
    return session.run_command(request)


def _apply_position_edit(session: RustMeshAuthoringSession) -> float:
    original_x = session.shadow_service.working_mesh(
        session.shadow_session_id,
        clone=False,
    ).submeshes[0].vertices[0][0]
    edited_x = original_x + 0.125
    request = _request(session, "transaction_request", 1)
    request["candidate"] = _candidate_reference(
        session,
        request_id=1,
        first_x=edited_x,
    )
    request["label"] = "Move"
    session.apply_candidate(request)
    return edited_x


def test_exact_finish_runs_existing_snapshot_writer_before_atomic_commit(
    tmp_path: Path,
) -> None:
    source, authoritative, session = _open_exact_session(tmp_path / "session")
    edited_x = _apply_position_edit(session)
    writer_results: list[object] = []
    original_writer = session.shadow_service.rebuild_result_from_snapshot

    def record_writer(snapshot: object):
        result = original_writer(snapshot)  # type: ignore[arg-type]
        writer_results.append(result)
        return result

    with patch.object(
        session.shadow_service,
        "rebuild_result_from_snapshot",
        side_effect=record_writer,
    ) as writer:
        result = session.finish(_request(session, "finish_request", 2))

    assert writer.call_count == 1
    assert len(writer_results) == 1
    rebuilt, report = writer_results[0]  # type: ignore[misc]
    evidence = result["exact_output_validation"]
    assert evidence["status"] == "passed"
    assert evidence["writer"] == "exact_same_count"
    assert evidence["fallback_used"] is False
    assert evidence["byte_identical"] is False
    assert evidence["source_asset_hash"] == hashlib.sha256(source).hexdigest().upper()
    assert evidence["rebuilt_asset_hash"] == hashlib.sha256(rebuilt.data).hexdigest().upper()
    assert report.validation_status == "passed"
    assert report.developer_overrides == ()
    assert report.output_path == ""

    original = parse_pac(source, "owned-rust-exact.pac")
    reparsed = parse_pac(rebuilt.data, "owned-rust-exact.pac")
    assert reparsed.submeshes[0].vertices[0][0] == pytest.approx(edited_x, abs=2e-5)
    assert reparsed.lod_levels[1:] == original.lod_levels[1:]
    assert reparsed.submeshes[0].bone_indices == original.submeshes[0].bone_indices
    assert reparsed.submeshes[0].bone_weights == original.submeshes[0].bone_weights

    assert authoritative.session_view("authoritative-rust-exact").revision == 1
    assert (
        authoritative.working_mesh("authoritative-rust-exact", clone=False)
        .submeshes[0]
        .vertices[0][0]
        == edited_x
    )
    assert (
        authoritative.capture_export_snapshot("authoritative-rust-exact").original_data
        == source
    )


def test_exact_finish_publishes_only_explicit_safe_skin_weight_rows(
    tmp_path: Path,
) -> None:
    source, authoritative, session = _open_exact_session(
        tmp_path / "session",
        resolved_rig=True,
    )
    selection = {
        "vertices_by_submesh": {"0": [0]},
        "edges_by_submesh": {},
        "faces_by_submesh": {},
        "source_indices": [],
    }
    _rig_command(session, 1, "rig_select_bone", {"bone_index": 7})
    changed = _rig_command(
        session,
        2,
        "rig_adjust_weight",
        {"selection": selection, "delta": 0.1},
    )
    capability = changed["state"]["skeleton"]["weight_edit_capability"]
    assert capability["enabled"] is True
    shadow = session.shadow_service._session(session.shadow_session_id)
    operations = tuple(shadow.edit_operations)
    skin_operations = [
        operation
        for operation in operations
        if operation["operation"] == "replace_skin_weights_same_count"
    ]
    assert len(skin_operations) == 1
    assert skin_operations[0]["submesh_index"] == 0

    session.finish(_request(session, "finish_request", 3))
    snapshot = authoritative.capture_export_snapshot("authoritative-rust-exact")
    rebuilt, report = authoritative.rebuild_result_from_snapshot(snapshot)
    assert report.validation_status == "passed"
    original = parse_pac(source, "owned-rust-exact.pac")
    reparsed = parse_pac(rebuilt.data, "owned-rust-exact.pac")
    assert reparsed.submeshes[0].bone_indices[0] == (3, 7)
    assert reparsed.submeshes[0].bone_weights[0] == pytest.approx(
        (174.0 / 255.0, 81.0 / 255.0),
        abs=1e-12,
    )
    assert len(rebuilt.data) == len(source)
    authorized_skin_bytes = {
        byte_offset
        for record_offset in original.submeshes[0].source_vertex_offsets
        for byte_offset in range(record_offset + 20, record_offset + 34)
    }
    changed_bytes = {
        byte_offset
        for byte_offset, (before, after) in enumerate(zip(source, rebuilt.data))
        if before != after
    }
    assert changed_bytes
    assert changed_bytes <= authorized_skin_bytes
    for offset in original.submeshes[0].source_vertex_offsets:
        assert rebuilt.data[offset + 12 : offset + 16] == source[
            offset + 12 : offset + 16
        ]
        assert rebuilt.data[offset + 34 : offset + 36] == source[
            offset + 34 : offset + 36
        ]
    assert reparsed.lod_levels[1:] == original.lod_levels[1:]
    assert snapshot.original_data == source


def test_exact_skin_patch_rejects_conflicting_shared_source_records() -> None:
    source = _pac_fixture(skinned=True)
    original = parse_pac(source, "owned-shared-skin-record.pac")
    original.submeshes.append(copy.deepcopy(original.submeshes[0]))
    edited = copy.deepcopy(original)
    edited.submeshes[0].bone_weights[0] = (0.7, 0.3)
    edited.submeshes[1].bone_weights[0] = (0.6, 0.4)

    with pytest.raises(
        ValueError,
        match="conflicting edits for shared source vertex record",
    ):
        _patch_exact_pac_skin_weights(
            original,
            edited,
            source,
            source,
            frozenset({0, 1}),
        )


def test_rust_finish_geometry_is_the_geometry_published_in_a_loose_manager_package(
    tmp_path: Path,
) -> None:
    source, authoritative, session = _open_exact_session(tmp_path / "session")
    edited_x = _apply_position_edit(session)
    session.finish(_request(session, "finish_request", 2))
    accepted_revision = authoritative.session_view("authoritative-rust-exact").revision

    archive_root = tmp_path / "game" / "0009"
    archive_root.mkdir(parents=True)
    pamt = archive_root / "0.pamt"
    paz = archive_root / "0.paz"
    pamt.write_bytes(b"owned source index")
    paz.write_bytes(b"owned source payload")
    source_fingerprints = (pamt.read_bytes(), paz.read_bytes())
    entry = ArchiveEntry(
        path="character/model/rust-finished.pac",
        pamt_path=pamt,
        paz_file=paz,
        offset=0,
        comp_size=len(source),
        orig_size=len(source),
        flags=0,
        paz_index=0,
    )
    output_root = tmp_path / "jmm-rust-finished-mesh"
    worker = MeshDirectOutputWorker(
        91,
        authoritative,
        "authoritative-rust-exact",
        entry,
        kind="loose_mod",
        output_path=output_root,
        manager_profile="jmm",
        expected_mesh_revision=accepted_revision,
    )
    completed: list[object] = []
    errors: list[str] = []
    worker.completed.connect(lambda _request_id, result: completed.append(result))
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.run()

    assert not errors
    assert len(completed) == 1
    published = parse_pac(
        (output_root / entry.path).read_bytes(),
        entry.path,
    )
    original = parse_pac(source, entry.path)
    assert published.submeshes[0].vertices[0][0] == pytest.approx(edited_x, abs=2e-5)
    assert published.lod_levels[1:] == original.lod_levels[1:]
    assert (output_root / "mod.json").is_file()
    assert (pamt.read_bytes(), paz.read_bytes()) == source_fingerprints


def test_exact_writer_rejection_keeps_authoritative_mesh_and_source_unchanged(
    tmp_path: Path,
) -> None:
    source, authoritative, session = _open_exact_session(tmp_path / "session")
    original_vertex = authoritative.working_mesh(
        "authoritative-rust-exact",
        clone=True,
    ).submeshes[0].vertices[0]
    _apply_position_edit(session)

    with (
        patch.object(
            session.shadow_service,
            "rebuild_result_from_snapshot",
            side_effect=RuntimeError("synthetic exact writer rejection"),
        ) as writer,
        patch.object(
            authoritative,
            "prepare_working_mesh_replacement",
            wraps=authoritative.prepare_working_mesh_replacement,
        ) as prepare,
        pytest.raises(
            RustMeshValidationError,
            match="Exact game-asset writer rejected.*synthetic exact writer rejection",
        ),
    ):
        session.finish(_request(session, "finish_request", 2))

    assert writer.call_count == 1
    assert prepare.call_count == 0
    assert authoritative.session_view("authoritative-rust-exact").revision == 0
    assert (
        authoritative.working_mesh("authoritative-rust-exact", clone=False)
        .submeshes[0]
        .vertices[0]
        == original_vertex
    )
    assert (
        authoritative.capture_export_snapshot("authoritative-rust-exact").original_data
        == source
    )


def test_untracked_skin_weight_change_cannot_finish_or_publish(
    tmp_path: Path,
) -> None:
    source, authoritative, session = _open_exact_session(tmp_path / "session")
    authoritative_before = authoritative.working_mesh(
        "authoritative-rust-exact",
        clone=True,
    ).submeshes[0].bone_weights
    shadow = session.shadow_service._session(session.shadow_session_id)
    with shadow.export_lock:
        shadow.working_mesh.submeshes[0].bone_weights[0] = (0.7, 0.3)
        shadow.revision += 1

    with pytest.raises(
        RustMeshValidationError,
        match="Bone indices and weights must match the original asset",
    ):
        session.finish(_request(session, "finish_request", 1))

    assert authoritative.session_view("authoritative-rust-exact").revision == 0
    assert (
        authoritative.working_mesh(
            "authoritative-rust-exact",
            clone=False,
        ).submeshes[0].bone_weights
        == authoritative_before
    )
    assert authoritative.capture_export_snapshot(
        "authoritative-rust-exact"
    ).original_data == source
    assert not session.closed
    session.cancel()


def test_authoritative_edit_during_exact_writer_cannot_be_overwritten(
    tmp_path: Path,
) -> None:
    source, authoritative, session = _open_exact_session(tmp_path / "session")
    _apply_position_edit(session)
    concurrent = authoritative.working_mesh(
        "authoritative-rust-exact",
        clone=True,
    )
    concurrent.submeshes[0].vertices[0] = (0.375, 0.0, 0.0)
    original_writer = session.shadow_service.rebuild_result_from_snapshot

    def race_writer(snapshot: object):
        authoritative.replace_working_mesh(
            "authoritative-rust-exact",
            concurrent,
        )
        return original_writer(snapshot)  # type: ignore[arg-type]

    with (
        patch.object(
            session.shadow_service,
            "rebuild_result_from_snapshot",
            side_effect=race_writer,
        ),
        pytest.raises(
            RustMeshValidationError,
            match="changed while Edit Mesh was open",
        ),
    ):
        session.finish(_request(session, "finish_request", 2))

    assert authoritative.session_view("authoritative-rust-exact").revision == 1
    assert (
        authoritative.working_mesh("authoritative-rust-exact", clone=False)
        .submeshes[0]
        .vertices[0]
        == (0.375, 0.0, 0.0)
    )
    assert (
        authoritative.capture_export_snapshot("authoritative-rust-exact").original_data
        == source
    )
    assert not session.closed
    session.cancel()


def test_exact_finish_rejects_writer_report_that_used_topology_fallback(
    tmp_path: Path,
) -> None:
    source, authoritative, session = _open_exact_session(tmp_path / "session")
    original_vertex = authoritative.working_mesh(
        "authoritative-rust-exact",
        clone=True,
    ).submeshes[0].vertices[0]
    _apply_position_edit(session)
    original_writer = session.shadow_service.rebuild_result_from_snapshot

    def report_fallback(snapshot: object):
        rebuilt, report = original_writer(snapshot)  # type: ignore[arg-type]
        return rebuilt, replace(
            report,
            topology_rebuild={
                "serializer": "synthetic_fallback",
                "fallback_used": True,
            },
        )

    with (
        patch.object(
            session.shadow_service,
            "rebuild_result_from_snapshot",
            side_effect=report_fallback,
        ),
        pytest.raises(
            RustMeshValidationError,
            match="fallback was disabled",
        ),
    ):
        session.finish(_request(session, "finish_request", 2))

    assert authoritative.session_view("authoritative-rust-exact").revision == 0
    assert (
        authoritative.working_mesh("authoritative-rust-exact", clone=False)
        .submeshes[0]
        .vertices[0]
        == original_vertex
    )
    assert (
        authoritative.capture_export_snapshot("authoritative-rust-exact").original_data
        == source
    )
    session.cancel()
