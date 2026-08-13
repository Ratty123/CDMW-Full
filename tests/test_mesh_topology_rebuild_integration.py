"""End-to-end: a resident topology edit rebuilt into its original PAC.

These drive the real service and the real native session, then rebuild through
the ordinary importer entry point, so they prove the contract survives every hop
between the native editor and the bytes on disk.
"""

from __future__ import annotations

import hashlib

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection, validate_mesh_export
from cdmw.domain.mesh.topology import (
    TOPOLOGY_PROVENANCE_VERSION,
    validate_topology_operation_history,
    validate_topology_provenance,
)
from cdmw.modding.mesh_importer import rebuild_mesh_with_report
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package
from cdmw.services.mesh_service import MeshService

from tests.test_mesh_pac_topology_serializer import _pac_fixture


pytestmark = pytest.mark.skipif(
    not native_mesh_core_available(), reason="native mesh core binary is unavailable"
)


def _session(service: MeshService, session_id: str, data: bytes):
    mesh = parse_pac(data, "target.pac")
    # The app opens a session with the source bytes attached; without them the
    # export snapshot carries no original and nothing can be rebuilt into it.
    setattr(mesh, "_cdmw_original_data", data)
    view = service.open_edit_session(mesh, session_id=session_id, mode="edit")
    # The native session opens lazily, on the first command.
    service.apply_command(
        view.session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            params={"operation": "replace"},
            mode="edit",
        ),
    )
    return view


def _subdivide(service: MeshService, session_id: str) -> None:
    result = service.apply_command(
        session_id,
        MeshEditCommand(
            "subdivide",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            params={"max_faces_per_submesh": 4096, "_include_preview_deltas": False},
            mode="edit",
        ),
    )
    assert result.ok, result


def test_a_resident_subdivide_rebuilds_through_the_exact_serializer() -> None:
    data = _pac_fixture(skinned=True)
    original = parse_pac(data, "target.pac")
    service = MeshService()
    view = _session(service, "topology-rebuild-subdivide", data)
    try:
        _subdivide(service, view.session_id)
        working = service.working_mesh(view.session_id, clone=True)

        provenance = working.submeshes[0].topology_provenance
        assert provenance is not None
        assert provenance.version == TOPOLOGY_PROVENANCE_VERSION
        assert (
            validate_topology_provenance(
                provenance,
                output_vertex_count=len(working.submeshes[0].vertices),
                output_face_count=len(working.submeshes[0].faces),
            )
            == ()
        )

        result = rebuild_mesh_with_report(working, data, original_mesh=original)
        report = dict(result.report.topology_rebuild or {})

        assert report["serializer"] == "pac_lod0_topology_exact_v1"
        assert report["fallback_used"] is False
        assert report["lost_influence_mass"] == 0.0
        assert report["blended_vertex_count"] >= 1
        assert report["protected_bytes_preserved"] is True
        assert report["original_bounds_preserved"] is True
        assert report["lower_lods_preserved"] is True

        reparsed = parse_pac(result.data, "target.pac")
        assert len(reparsed.submeshes[0].vertices) == len(working.submeshes[0].vertices)
        assert len(reparsed.submeshes[0].faces) == len(working.submeshes[0].faces)
        assert reparsed.submeshes[0].source_bbox_min == original.submeshes[0].source_bbox_min
        assert reparsed.submeshes[0].source_bbox_extent == original.submeshes[0].source_bbox_extent
    finally:
        service.close_edit_session(view.session_id)


def test_a_face_delete_that_removes_the_first_face_keeps_its_contract() -> None:
    # The surviving face origins are then a contiguous range that does not start
    # at zero, and the native report sends them as start/count rather than as a
    # binary payload. Bounding that range by the output face count instead of the
    # original one silently dropped the whole contract, which read as "Face
    # Delete produced no usable topology contract".
    data = _pac_fixture(skinned=True)
    original = parse_pac(data, "target.pac")
    service = MeshService()
    view = _session(service, "topology-rebuild-first-face", data)
    try:
        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "delete",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"_include_preview_deltas": False},
                mode="edit",
            ),
        )
        assert result.ok

        working = service.working_mesh(view.session_id, clone=True)
        submesh = working.submeshes[0]
        provenance = submesh.topology_provenance

        assert provenance is not None
        assert provenance.face_origins == (1,)
        assert provenance.original_face_count == 2
        assert (
            validate_topology_provenance(
                provenance,
                output_vertex_count=len(submesh.vertices),
                output_face_count=len(submesh.faces),
            )
            == ()
        )

        rebuild = rebuild_mesh_with_report(working, data, original_mesh=original)
        assert dict(rebuild.report.topology_rebuild or {})["serializer"] == "pac_lod0_topology_exact_v1"
    finally:
        service.close_edit_session(view.session_id)


def test_recorded_operations_do_not_divert_the_rebuild_back_to_the_original() -> None:
    # The rebuild path re-applies named channels onto a deep copy of the
    # original when edit operations are present. Topology operations map to no
    # channel, so that reconstruction handed the writer the unedited original
    # and still called it a rebuild: a plausible file, silently not the edit.
    data = _pac_fixture(skinned=True)
    original = parse_pac(data, "target.pac")
    service = MeshService()
    view = _session(service, "topology-rebuild-operations", data)
    try:
        _subdivide(service, view.session_id)
        snapshot = service.capture_export_snapshot(view.session_id)
        assert snapshot.edit_operations, "the subdivide should have recorded an operation"

        # Exactly what the service does before rebuilding.
        setattr(snapshot.mesh, "_cdmw_edit_operations", tuple(snapshot.edit_operations))
        result = rebuild_mesh_with_report(
            snapshot.mesh, snapshot.original_data, original_mesh=snapshot.base_mesh
        )

        report = dict(result.report.topology_rebuild or {})
        assert report.get("serializer") == "pac_lod0_topology_exact_v1"
        assert report.get("fallback_used") is False
        reparsed = parse_pac(result.data, "target.pac")
        assert len(reparsed.submeshes[0].faces) == len(snapshot.mesh.submeshes[0].faces)
        assert len(reparsed.submeshes[0].faces) != len(original.submeshes[0].faces)
    finally:
        service.close_edit_session(view.session_id)


def test_the_session_records_a_continuous_topology_operation_history() -> None:
    data = _pac_fixture()
    service = MeshService()
    view = _session(service, "topology-rebuild-history", data)
    try:
        _subdivide(service, view.session_id)
        _subdivide(service, view.session_id)
        operations = tuple(service._sessions[view.session_id].edit_operations)  # noqa: SLF001

        assert [operation.operation for operation in operations] == [
            "subdivide_midpoint_topology",
            "subdivide_midpoint_topology",
        ]
        assert [operation.metadata["source_revision"] for operation in operations] == [0, 1]
        assert [operation.metadata["result_revision"] for operation in operations] == [1, 2]
        assert validate_topology_operation_history(operations) == ()
    finally:
        service.close_edit_session(view.session_id)


def test_an_unsupported_topology_edit_records_no_operation_and_blocks_rebuild() -> None:
    data = _pac_fixture()
    original = parse_pac(data, "target.pac")
    service = MeshService()
    view = _session(service, "topology-rebuild-unsupported", data)
    try:
        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "refine_smooth",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"max_faces_per_submesh": 4096, "_include_preview_deltas": False},
                mode="edit",
            ),
        )
        assert result.ok
        assert tuple(service._sessions[view.session_id].edit_operations) == ()  # noqa: SLF001

        working = service.working_mesh(view.session_id, clone=True)
        assert working.submeshes[0].topology_provenance is None

        report = validate_mesh_export(working, original_mesh=original)
        codes = {issue.code for issue in report.issues if issue.severity == "blocker"}
        assert "submesh_vertex_count_changed" in codes
    finally:
        service.close_edit_session(view.session_id)


def test_export_readiness_admits_the_contract_and_names_no_topology_blocker() -> None:
    data = _pac_fixture()
    original = parse_pac(data, "target.pac")
    service = MeshService()
    view = _session(service, "topology-rebuild-checks", data)
    try:
        _subdivide(service, view.session_id)
        working = service.working_mesh(view.session_id, clone=True)

        report = validate_mesh_export(working, original_mesh=original)
        codes = {issue.code for issue in report.issues if issue.severity == "blocker"}

        assert "submesh_vertex_count_changed" not in codes
        assert "submesh_index_count_changed" not in codes
        assert "source_vertex_map_missing" not in codes
        assert "source_vertex_map_invalid" not in codes
        assert not any(code.startswith("topology_") for code in codes)
    finally:
        service.close_edit_session(view.session_id)


def test_editable_package_export_refuses_resident_topology_state(tmp_path) -> None:
    data = _pac_fixture()
    service = MeshService()
    view = _session(service, "topology-rebuild-package", data)
    try:
        _subdivide(service, view.session_id)
        working = service.working_mesh(view.session_id, clone=True)

        with pytest.raises(RuntimeError) as blocked:
            build_mesh_dotnet_experiment_package(working, output_root=tmp_path)

        assert "Editable Package Export is unavailable" in str(blocked.value)
    finally:
        service.close_edit_session(view.session_id)


def test_a_rebuild_blocked_by_protected_bytes_writes_nothing() -> None:
    data = _pac_fixture(protected_divergence=True)
    original = parse_pac(data, "target.pac")
    digest = hashlib.sha256(data).hexdigest()
    service = MeshService()
    view = _session(service, "topology-rebuild-blocked", data)
    try:
        _subdivide(service, view.session_id)
        working = service.working_mesh(view.session_id, clone=True)

        with pytest.raises(Exception) as blocked:
            rebuild_mesh_with_report(working, data, original_mesh=original)

        assert "TOPOLOGY_PROTECTED_BYTES_DIVERGE" in str(blocked.value)
        assert hashlib.sha256(data).hexdigest() == digest
    finally:
        service.close_edit_session(view.session_id)


def test_a_same_count_session_still_rebuilds_without_the_topology_writer() -> None:
    data = _pac_fixture()
    original = parse_pac(data, "target.pac")
    service = MeshService()
    view = _session(service, "topology-rebuild-same-count", data)
    try:
        working = service.working_mesh(view.session_id, clone=True)
        assert working.submeshes[0].topology_provenance is None

        result = rebuild_mesh_with_report(working, data, original_mesh=original)

        assert dict(result.report.topology_rebuild or {}) == {}
        rebuilt = parse_pac(result.data, "target.pac").submeshes[0]
        assert len(rebuilt.vertices) == len(original.submeshes[0].vertices)
        assert [tuple(face) for face in rebuilt.faces] == [
            tuple(face) for face in original.submeshes[0].faces
        ]
        # Positions round-trip through the u16 frame, so compare within a
        # quantization unit rather than exactly.
        for rebuilt_position, original_position in zip(rebuilt.vertices, original.submeshes[0].vertices):
            assert rebuilt_position == pytest.approx(original_position, abs=1e-4)
    finally:
        service.close_edit_session(view.session_id)
