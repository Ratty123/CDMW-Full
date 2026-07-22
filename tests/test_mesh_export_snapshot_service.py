from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_importer import MeshRebuildReport
from cdmw.models import RunCancelled
from cdmw.services.mesh_dotnet_material_state import mesh_dotnet_texture_resource_id
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_state import MeshExportSnapshot, MeshExportTextureSnapshot
from cdmw.workers.mesh_editor_workers import (
    MeshEditablePackageExportWorker,
    MeshRebuildReportWorker,
    _apply_export_texture_bindings,
    _package_reparse_report,
    _wait_for_texture_updates,
)
from tools.mesh_harness.fixtures import build_synthetic_mesh


def _open_service(tmp_path: Path, *, session_id: str = "export-snapshot") -> tuple[MeshService, str]:
    mesh = build_synthetic_mesh()
    mesh.path = str(tmp_path / "source.pac")
    service = MeshService()
    view = service.open_edit_session(mesh, session_id=session_id, mode="edit")
    return service, view.session_id


def test_committed_assignment_overrides_older_painted_binding_for_same_channel(tmp_path: Path) -> None:
    original = tmp_path / "original.dds"
    assigned = tmp_path / "assigned.dds"
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(assigned)
    snapshot = MeshExportSnapshot(
        session_id="binding-authority",
        mesh_revision=1,
        native_edit_revision=1,
        material_generation=2,
        texture_revisions=(("painted", "base", 5), ("assigned", "base", 1)),
        mesh=mesh,
        base_mesh=mesh,
        original_data=b"",
        texture_resources=(
            MeshExportTextureSnapshot(
                resource_id="painted",
                channel="base",
                affected_submeshes=(0,),
                revision=5,
                logical_path=str(original),
                width=1,
                height=1,
                row_pitch=4,
                bgra_data=b"\x00\x00\x00\xff",
            ),
            MeshExportTextureSnapshot(
                resource_id="assigned",
                channel="base",
                affected_submeshes=(0,),
                revision=1,
                logical_path=str(assigned),
                dds_data=b"assigned",
            ),
        ),
    )

    bindings = _apply_export_texture_bindings(
        snapshot,
        (
            {"resource_id": "painted", "channel": "base", "path": "textures/painted.dds"},
            {"resource_id": "assigned", "channel": "base", "path": "textures/assigned.dds"},
        ),
    )

    assert bindings[0]["resource_id"] == "assigned"
    assert mesh.submeshes[0].texture == "textures/assigned.dds"


def test_resident_texture_snapshot_and_regions_are_revisioned_and_capture_is_immutable(tmp_path: Path) -> None:
    service, session_id = _open_service(tmp_path)
    padded = bytes(
        [1, 2, 3, 4, 5, 6, 7, 8, 99, 99, 99, 99]
        + [9, 10, 11, 12, 13, 14, 15, 16, 88, 88, 88, 88]
    )

    assert service.commit_texture_snapshot(
        session_id,
        "body/base",
        channel="base",
        affected_submeshes=(0,),
        width=2,
        height=2,
        row_pitch=12,
        bgra=padded,
        logical_path="character/body_d.dds",
    ) == 1
    assert service.commit_texture_region(
        session_id,
        "body/base",
        channel="base",
        rect=(1, 0, 1, 2),
        row_pitch=4,
        bgra=bytes([21, 22, 23, 24, 31, 32, 33, 34]),
        expected_revision=1,
    ) == 2

    captured = service.capture_export_snapshot(session_id, expected_mesh_revision=0)
    assert captured.material_generation == 2
    assert captured.texture_revisions == (("body/base", "base", 2),)
    assert captured.texture_resources[0].bgra_data == bytes(
        [1, 2, 3, 4, 21, 22, 23, 24, 9, 10, 11, 12, 31, 32, 33, 34]
    )

    assert service.commit_texture_region(
        session_id,
        "body/base",
        channel="base",
        rect=(0, 0, 1, 1),
        row_pitch=4,
        bgra=bytes([41, 42, 43, 44]),
        expected_revision=2,
    ) == 3
    assert captured.texture_revisions == (("body/base", "base", 2),)
    assert captured.texture_resources[0].bgra_data[:4] == bytes([1, 2, 3, 4])
    assert service.capture_export_snapshot(session_id).texture_resources[0].bgra_data[:4] == bytes([41, 42, 43, 44])

    root = service._sessions[session_id].texture_resource_root
    assert root is not None and root.is_dir()
    service.close_edit_session(session_id)
    assert not root.exists()


def test_acknowledged_material_parameters_merge_clear_and_capture_coherently(tmp_path: Path) -> None:
    service, session_id = _open_service(tmp_path, session_id="material-parameters")
    assert service.capture_export_snapshot(session_id).material_parameter_groups == ()

    assert service.commit_resident_material_parameters(
        session_id,
        ({"source_submesh_indices": [0], "roughness": 0.25, "tint_color": [0.2, 0.4, 0.6]},),
        expected_mesh_revision=0,
    ) == 1
    first = service.capture_export_snapshot(session_id)
    assert first.material_generation == 1
    assert first.material_parameter_groups == ({
        "source_submesh_indices": [0],
        "roughness": 0.25,
        "tint_color": [0.2, 0.4, 0.6],
    },)

    assert service.commit_resident_material_parameters(
        session_id,
        ({"source_submesh_indices": [0], "roughness": None, "metalness": 0.75},),
        expected_mesh_revision=0,
    ) == 2
    second = service.capture_export_snapshot(session_id)
    assert second.material_parameter_groups == ({
        "source_submesh_indices": [0],
        "metalness": 0.75,
        "tint_color": [0.2, 0.4, 0.6],
    },)
    assert service.export_snapshot_report(second)["material_parameter_groups"] == list(
        second.material_parameter_groups
    )
    assert first.material_parameter_groups[0]["roughness"] == 0.25

    with pytest.raises(RuntimeError, match="stale resident material revision"):
        service.commit_resident_material_parameters(
            session_id,
            ({"source_submesh_indices": [0], "roughness": 0.5},),
            expected_mesh_revision=1,
        )


def test_acknowledged_material_resources_publish_as_one_authoritative_batch(tmp_path: Path) -> None:
    service, session_id = _open_service(tmp_path, session_id="material-resources")
    source = tmp_path / "generated.dds"
    source.write_bytes(b"generated-resource")
    assert service.commit_resident_material_resources(
        session_id,
        ({
            "resource_id": "generated/base",
            "channel": "base",
            "source_dds_path": source,
            "affected_submeshes": [0],
            "logical_path": "generated/base.dds",
        },),
        expected_mesh_revision=0,
    ) == 1
    snapshot = service.capture_export_snapshot(session_id)
    assert snapshot.texture_revisions == (("generated/base", "base", 1),)
    assert snapshot.texture_resources[0].dds_data == b"generated-resource"
    assert snapshot.texture_resources[0].affected_submeshes == (0,)

    with pytest.raises(FileNotFoundError):
        service.commit_resident_material_resources(
            session_id,
            (
                {"resource_id": "generated/second", "path": source, "affected_submeshes": [0]},
                {"resource_id": "generated/missing", "path": tmp_path / "missing.dds", "affected_submeshes": [0]},
            ),
        )
    rolled_back = service.capture_export_snapshot(session_id)
    assert rolled_back.material_generation == 1
    assert rolled_back.texture_revisions == snapshot.texture_revisions

    png = tmp_path / "generated.png"
    png.write_bytes(b"not-dds")
    with pytest.raises(ValueError, match="must be a DDS"):
        service.commit_resident_material_resources(
            session_id,
            ({"resource_id": "generated/png", "path": png, "affected_submeshes": [0]},),
        )

    assert service.commit_resident_material_resources(
        session_id,
        ({"resource_id": "generated/base", "channel": "base", "remove": True},),
    ) == 2
    assert service.capture_export_snapshot(session_id).texture_resources == ()


def test_acknowledged_material_state_commits_resources_parameters_and_fingerprint_atomically(
    tmp_path: Path,
) -> None:
    service, session_id = _open_service(tmp_path, session_id="material-authority-atomic")
    source = tmp_path / "resolved.dds"
    source.write_bytes(b"resolved material authority DDS")
    content_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    assert service.commit_resident_material_state(
        session_id,
        (
            {
                "resource_id": "material-authority/base",
                "channel": "base",
                "source_dds_path": source,
                "affected_submeshes": [0],
                "logical_path": "source/base.dds",
                "content_sha256": content_hash,
            },
        ),
        parameter_groups=(
            {"source_submesh_indices": [0], "texture_brightness": 1.0, "roughness_scale": 1.0},
        ),
        material_authority_fingerprint="fingerprint-1",
        material_authority_revision=7,
        expected_mesh_revision=0,
    ) == 1
    snapshot = service.capture_export_snapshot(session_id)
    assert snapshot.material_generation == 1
    assert snapshot.texture_resources[0].dds_data == source.read_bytes()
    assert snapshot.material_parameter_groups == (
        {"source_submesh_indices": [0], "roughness_scale": 1.0, "texture_brightness": 1.0},
    )
    assert snapshot.material_authority_fingerprint == "fingerprint-1"
    assert snapshot.material_authority_revision == 7
    report = service.export_snapshot_report(snapshot)
    assert report["material_authority_fingerprint"] == "fingerprint-1"
    assert report["texture_resources"][0]["content_sha256"] == content_hash

    replacement = tmp_path / "replacement.dds"
    replacement.write_bytes(b"replacement material authority DDS")
    with pytest.raises(ValueError, match="hash does not match"):
        service.commit_resident_material_state(
            session_id,
            (
                {
                    "resource_id": "material-authority/base",
                    "channel": "base",
                    "source_dds_path": replacement,
                    "affected_submeshes": [0],
                    "content_sha256": "0" * 64,
                },
            ),
            parameter_groups=({"source_submesh_indices": [0], "roughness": 0.2},),
            material_authority_fingerprint="fingerprint-2",
            material_authority_revision=8,
        )
    rolled_back = service.capture_export_snapshot(session_id)
    assert rolled_back.material_generation == 1
    assert rolled_back.texture_resources[0].dds_data == source.read_bytes()
    assert rolled_back.material_authority_fingerprint == "fingerprint-1"


def test_resident_texture_region_rejects_stale_or_invalid_payloads(tmp_path: Path) -> None:
    service, session_id = _open_service(tmp_path)
    service.commit_texture_snapshot(
        session_id,
        "body/base",
        width=2,
        height=2,
        row_pitch=8,
        bgra=bytes(range(16)),
    )

    with pytest.raises(RuntimeError, match="stale resident texture revision"):
        service.commit_texture_region(
            session_id,
            "body/base",
            rect=(0, 0, 1, 1),
            row_pitch=4,
            bgra=b"\x00" * 4,
            expected_revision=0,
        )
    with pytest.raises(ValueError, match="exceeds the texture bounds"):
        service.commit_texture_region(
            session_id,
            "body/base",
            rect=(1, 1, 2, 1),
            row_pitch=8,
            bgra=b"\x00" * 8,
        )
    with pytest.raises(ValueError, match="truncated"):
        service.commit_texture_region(
            session_id,
            "body/base",
            rect=(0, 0, 2, 1),
            row_pitch=8,
            bgra=b"\x00" * 4,
        )


def test_only_committed_dds_is_included_in_export_snapshot(tmp_path: Path) -> None:
    preview = tmp_path / "preview.dds"
    assigned = tmp_path / "assigned.dds"
    preview.write_bytes(b"preview-only")
    assigned.write_bytes(b"committed")
    service, session_id = _open_service(tmp_path)
    session = service._sessions[session_id]
    session.working_mesh.submeshes[0].texture = str(preview)

    assert service.capture_export_snapshot(session_id).texture_resources == ()

    session.working_mesh.submeshes[0].texture = str(assigned)
    assert service.record_committed_texture_assignment(
        session_id,
        assigned,
        resource_id="body/base",
        affected_submeshes=(0,),
        logical_path="character/body_d.dds",
    ) == 1
    assigned.unlink()
    captured = service.capture_export_snapshot(session_id)
    assert captured.texture_revisions == (("body/base", "base", 1),)
    assert captured.texture_resources[0].dds_data == b"committed"
    assert captured.texture_resources[0].logical_path == "character/body_d.dds"
    owned_root = service._sessions[session_id].texture_resource_root
    assert owned_root is not None and owned_root.is_dir()
    service.close_edit_session(session_id)
    assert not owned_root.exists()


def test_material_assign_automatically_registers_committed_dds(tmp_path: Path) -> None:
    source = tmp_path / "source.dds"
    assigned = tmp_path / "assigned.dds"
    source.write_bytes(b"source")
    assigned.write_bytes(b"assigned")
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(source)
    service = MeshService()
    view = service.open_edit_session(mesh, session_id="automatic-dds-record", mode="edit")
    try:
        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                mode="edit",
                params={"texture": str(assigned)},
            ),
        )
        assert result.ok
        captured = service.capture_export_snapshot(view.session_id)
        assert captured.material_generation == 1
        assert len(captured.texture_resources) == 1
        assert captured.texture_resources[0].dds_data == b"assigned"
        resource_id = mesh_dotnet_texture_resource_id(assigned)
        assert captured.texture_resources[0].resource_id == resource_id
        assert service.commit_texture_snapshot(
            view.session_id,
            resource_id,
            affected_submeshes=(0,),
            width=1,
            height=1,
            row_pitch=4,
            bgra=b"\x10\x20\x30\x40",
        ) == 2
        painted = service.capture_export_snapshot(view.session_id)
        assert len(painted.texture_resources) == 1
        assert painted.texture_resources[0].resource_id == resource_id
        assert painted.texture_resources[0].bgra_data == b"\x10\x20\x30\x40"
    finally:
        service.close_edit_session(view.session_id)


def test_material_assignment_undo_and_redo_restore_export_state_without_reverting_paint(tmp_path: Path) -> None:
    source = tmp_path / "source.dds"
    assigned = tmp_path / "assigned.dds"
    source.write_bytes(b"source")
    assigned.write_bytes(b"assigned")
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(source)
    service = MeshService()
    view = service.open_edit_session(mesh, session_id="assignment-history", mode="edit")
    try:
        service.commit_texture_snapshot(
            view.session_id,
            "body/paint",
            width=1,
            height=1,
            row_pitch=4,
            bgra=b"\x01\x02\x03\x04",
        )
        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                mode="edit",
                params={"texture": str(assigned), "resource_id": "body/assigned"},
            ),
        )
        assert result.ok
        assigned_snapshot = service.capture_export_snapshot(view.session_id)
        assert assigned_snapshot.material_generation == 2
        assert {item.resource_id for item in assigned_snapshot.texture_resources} == {"body/assigned"}

        assert service.undo(view.session_id).ok
        undone = service.capture_export_snapshot(view.session_id)
        assert undone.material_generation == 3
        assert undone.texture_revisions == (("body/paint", "base", 1),)
        assert undone.texture_resources[0].bgra_data == b"\x01\x02\x03\x04"

        assert service.redo(view.session_id).ok
        redone = service.capture_export_snapshot(view.session_id)
        assert redone.material_generation == 4
        assert {item.resource_id for item in redone.texture_resources} == {"body/assigned"}
        assert next(item for item in redone.texture_resources if item.resource_id == "body/assigned").dds_data == b"assigned"
    finally:
        service.close_edit_session(view.session_id)


def test_assignment_only_supersedes_overlapping_painted_targets(tmp_path: Path) -> None:
    from copy import deepcopy

    source = tmp_path / "source.dds"
    assigned = tmp_path / "assigned.dds"
    source.write_bytes(b"source")
    assigned.write_bytes(b"assigned")
    mesh = build_synthetic_mesh()
    mesh.submeshes.append(deepcopy(mesh.submeshes[0]))
    for submesh in mesh.submeshes:
        submesh.texture = str(source)
    service = MeshService()
    view = service.open_edit_session(mesh, session_id="partial-assignment", mode="edit")
    try:
        service.commit_texture_snapshot(
            view.session_id,
            "body/paint",
            affected_submeshes=(0, 1),
            width=1,
            height=1,
            row_pitch=4,
            bgra=b"\x01\x02\x03\x04",
        )
        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                mode="edit",
                params={"texture": str(assigned), "resource_id": "body/assigned"},
            ),
        )
        assert result.ok
        resources = {item.resource_id: item for item in service.capture_export_snapshot(view.session_id).texture_resources}
        assert resources["body/assigned"].affected_submeshes == (0,)
        assert resources["body/paint"].affected_submeshes == (1,)
    finally:
        service.close_edit_session(view.session_id)


def test_capture_export_snapshot_rejects_stale_service_or_native_revision(tmp_path: Path) -> None:
    service, session_id = _open_service(tmp_path)
    session = service._sessions[session_id]

    with pytest.raises(RuntimeError, match="changed before capture"):
        service.capture_export_snapshot(session_id, expected_mesh_revision=1)

    session.native_editor_mesh_dirty = True
    session.native_editor_session_ready = True
    session.revision = 4
    with patch(
        "cdmw.services.mesh_service.export_native_mesh_editor_session_snapshot",
        return_value={"edit_revision": 3},
    ):
        with pytest.raises(RuntimeError, match="revision mismatch"):
            service.capture_export_snapshot(session_id)


def test_capture_export_snapshot_detects_revision_change_during_native_copy(tmp_path: Path) -> None:
    service, session_id = _open_service(tmp_path)
    session = service._sessions[session_id]
    session.native_editor_mesh_dirty = True
    session.native_editor_session_ready = True
    session.revision = 2

    def mutate_during_copy(_mesh: object, _session_id: str, **_kwargs: object) -> bool:
        session.revision += 1
        return True

    with (
        patch(
            "cdmw.services.mesh_service.export_native_mesh_editor_session_snapshot",
            side_effect=({"edit_revision": 2}, {"edit_revision": 2}),
        ),
        patch(
            "cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh",
            side_effect=mutate_during_copy,
        ),
    ):
        with pytest.raises(RuntimeError, match="changed during native snapshot capture"):
            service.capture_export_snapshot(session_id)


def test_editable_package_export_waits_for_texture_ack_and_reports_coherent_artifacts(tmp_path: Path) -> None:
    service, session_id = _open_service(tmp_path, session_id="coherent-package")
    service.commit_texture_snapshot(
        session_id,
        "body/base",
        width=1,
        height=1,
        row_pitch=4,
        bgra=b"\x01\x02\x03\x04",
        logical_path="character/body_d.dds",
    )
    service.commit_texture_snapshot(
        session_id,
        "body/material",
        channel="material",
        affected_submeshes=(0,),
        width=1,
        height=1,
        row_pitch=4,
        bgra=b"\x05\x06\x07\x08",
        logical_path="character/body_m.dds",
    )
    waits: list[float] = []
    completed: list[dict[str, object]] = []
    errors: list[str] = []
    output_dir = tmp_path / "editable"
    worker = MeshEditablePackageExportWorker(
        1,
        service,
        session_id,
        output_dir,
        expected_mesh_revision=0,
        texture_updates_waiter=lambda timeout: waits.append(timeout) is None,
    )
    worker.completed.connect(lambda _request_id, result, _elapsed: completed.append(result))
    worker.error.connect(lambda _request_id, message: errors.append(message))

    def write_fake_dds(_resource: object, target: Path, _stop: object) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"DDS export")

    with (
        patch(
            "cdmw.workers.mesh_editor_workers._encode_bgra_snapshot_dds",
            side_effect=write_fake_dds,
        ),
        patch(
            "cdmw.core.dds_native.inspect_dds_native_path",
            return_value=SimpleNamespace(width=1, height=1, mip_count=1, format_name="BGRA8", reason=""),
        ),
    ):
        worker.run()

    assert errors == []
    assert len(waits) == 1 and 0.0 < waits[0] <= 0.05
    assert len(completed) == 1
    report_path = output_dir / "mesh_export_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema"] == "cdmw_mesh_export_snapshot_v1"
    assert report["mesh_revision"] == 0
    assert report["material_generation"] == 2
    assert report["texture_revisions"] == [
        {"resource_id": "body/base", "channel": "base", "revision": 1},
        {"resource_id": "body/material", "channel": "material", "revision": 1},
    ]
    assert report["output_reparse"]["status"] == "passed"
    assert report["output_reparse"]["draw_section_lineage_readback"] == "passed"
    assert report["output_reparse"]["rig_skinning_readback"] == "passed"
    assert report["output_reparse"]["reference_metadata_readback"] == "passed"
    assert any(row["role"] == "mesh_glb" for row in report["artifacts"])
    texture_rows = [row for row in report["artifacts"] if row["role"] == "texture_dds"]
    assert {row["channel"] for row in texture_rows} == {"base", "material"}
    texture_row = next(row for row in texture_rows if row["channel"] == "base")
    texture_path = output_dir / texture_row["path"]
    assert texture_path.read_bytes() == b"DDS export"
    assert texture_row["sha256"] == hashlib.sha256(b"DDS export").hexdigest()
    assert texture_row["readback"] == {
        "status": "passed",
        "format": "BGRA8",
        "width": 1,
        "height": 1,
        "mip_count": 1,
        "reason": "",
    }
    assert report["output_reparse"]["texture_bindings"][0]["path"] == texture_row["path"]
    assert texture_row["path"] in (output_dir / "mesh.mtl").read_text(encoding="utf-8")
    material_row = next(row for row in texture_rows if row["channel"] == "material")
    bindings = report["resolved_texture_bindings"]
    assert {row["channel"] for row in bindings} == {"base", "material"}
    assert material_row["path"] not in (output_dir / "mesh.mtl").read_text(encoding="utf-8")
    assert material_row["path"] in (output_dir / "mesh.glb.meta.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("contract", "message"),
    (
        ("draw", "draw-section lineage"),
        ("rig", "rig/skinning"),
        ("reference", "reference metadata"),
    ),
)
def test_editable_package_reparse_rejects_corrupted_metadata_contract(
    tmp_path: Path,
    contract: str,
    message: str,
) -> None:
    service, session_id = _open_service(tmp_path, session_id=f"corrupt-{contract}")
    output_dir = tmp_path / "editable"
    errors: list[str] = []
    worker = MeshEditablePackageExportWorker(1, service, session_id, output_dir)
    worker.error.connect(lambda _request_id, error: errors.append(error))
    worker.run()
    assert errors == []

    sidecar_path = output_dir / "mesh.glb.meta.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if contract == "draw":
        sidecar["lods"][0]["submeshes"][0]["stable_id"] = "corrupt-draw-section"
    elif contract == "rig":
        sidecar["skeleton_info"]["skinned"] = not bool(sidecar["skeleton_info"]["skinned"])
    else:
        sidecar["material_slots"][0]["name"] = "corrupt-reference"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    snapshot = service.capture_export_snapshot(session_id)
    with pytest.raises(RuntimeError, match=message):
        _package_reparse_report(output_dir, "mesh", source_mesh=snapshot.mesh)
    service.close_edit_session(session_id)


def test_rebuild_worker_publishes_reparse_and_snapshot_report_atomically(tmp_path: Path) -> None:
    mesh = build_synthetic_mesh()
    mesh.path = str(tmp_path / "source.pac")
    snapshot = MeshExportSnapshot(
        session_id="rebuild-export",
        mesh_revision=7,
        native_edit_revision=7,
        material_generation=3,
        texture_revisions=(),
        mesh=mesh,
        base_mesh=mesh,
        original_data=b"source",
    )
    base_report = MeshRebuildReport(
        mesh_format="pac",
        source_asset_hash=hashlib.sha256(b"source").hexdigest(),
        rebuilt_asset_hash=hashlib.sha256(b"rebuilt").hexdigest(),
        source_size=6,
        rebuilt_size=7,
        parse_confidence="exact",
        validation_status="passed",
        byte_identical=False,
        changed_byte_ranges=((0, 7),),
    )

    class Service:
        @staticmethod
        def capture_export_snapshot(_session_id: str, **kwargs: object) -> MeshExportSnapshot:
            assert kwargs["expected_mesh_revision"] == 7
            return snapshot

        @staticmethod
        def rebuild_result_from_snapshot(_snapshot: MeshExportSnapshot, **_kwargs: object):
            return SimpleNamespace(data=b"rebuilt"), base_report

        export_snapshot_report = staticmethod(MeshService.export_snapshot_report)

    output_path = tmp_path / "rebuilt.pac"
    completed: list[MeshRebuildReport] = []
    errors: list[str] = []
    worker = MeshRebuildReportWorker(
        2,
        Service(),  # type: ignore[arg-type]
        snapshot.session_id,
        output_path=output_path,
        expected_mesh_revision=7,
        texture_updates_waiter=lambda _timeout: True,
    )
    worker.completed.connect(lambda _request_id, report: completed.append(report))
    worker.error.connect(lambda _request_id, message: errors.append(message))

    with patch("cdmw.workers.mesh_editor_workers.parse_mesh", return_value=mesh):
        worker.run()

    assert errors == []
    assert output_path.read_bytes() == b"rebuilt"
    assert len(completed) == 1
    report_path = tmp_path / "rebuilt.pac.export.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["export_snapshot"]["mesh_revision"] == 7
    assert report["export_snapshot"]["material_generation"] == 3
    assert report["export_snapshot"]["output_reparse"]["status"] == "passed"
    artifact = report["export_snapshot"]["artifacts"][0]
    assert artifact["path"] == "rebuilt.pac"
    assert artifact["sha256"] == hashlib.sha256(b"rebuilt").hexdigest()


def test_editable_export_rejects_invalid_committed_dds_before_publish(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.dds"
    invalid.write_bytes(b"not a dds")
    service, session_id = _open_service(tmp_path, session_id="invalid-dds-export")
    service._sessions[session_id].working_mesh.submeshes[0].texture = str(invalid)
    service.record_committed_texture_assignment(
        session_id,
        invalid,
        affected_submeshes=(0,),
    )
    output_dir = tmp_path / "invalid-package"
    errors: list[str] = []
    worker = MeshEditablePackageExportWorker(3, service, session_id, output_dir)
    worker.error.connect(lambda _request_id, message: errors.append(message))

    worker.run()

    assert len(errors) == 1
    assert "DDS readback failed" in errors[0]
    assert not output_dir.exists()
    service.close_edit_session(session_id)


def test_texture_ack_drain_checks_cancellation_between_short_waits() -> None:
    stop_event = threading.Event()
    waits: list[float] = []

    def cancel_after_first_wait(timeout: float) -> bool:
        waits.append(timeout)
        stop_event.set()
        return False

    with pytest.raises(RunCancelled):
        _wait_for_texture_updates(cancel_after_first_wait, stop_event)
    assert len(waits) == 1 and 0.0 < waits[0] <= 0.05
