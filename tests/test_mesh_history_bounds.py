from __future__ import annotations

import json
import subprocess
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding import mesh_native_core
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service import MeshService


def _mesh(*, first_x: float = 0.0, vertex_count: int = 4) -> ParsedMesh:
    vertices = [(first_x, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]
    vertices.extend((float(index), 2.0, 0.0) for index in range(4, vertex_count))
    faces = [(0, 1, 2), (1, 3, 2)] if vertex_count >= 4 else []
    submesh = SubMesh(
        name="history",
        material="mat",
        texture="a.dds",
        vertices=vertices,
        uvs=[(0.0, 0.0)] * len(vertices),
        normals=[(0.0, 0.0, 1.0)] * len(vertices),
        faces=faces,
        vertex_count=len(vertices),
        face_count=len(faces),
    )
    return ParsedMesh(
        path="history.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=len(vertices),
        total_faces=len(faces),
        has_uvs=True,
    )


def _two_loose_submesh_mesh() -> ParsedMesh:
    first = _mesh(vertex_count=5).submeshes[0]
    second = _mesh(first_x=10.0, vertex_count=5).submeshes[0]
    first.name = "first"
    second.name = "second"
    return ParsedMesh(
        path="two-loose.pac",
        format="pac",
        submeshes=[first, second],
        total_vertices=10,
        total_faces=4,
        has_uvs=True,
    )


def _native_required() -> None:
    if not mesh_native_core.native_mesh_core_available():
        pytest.skip("native mesh core binary not available")


def _export_vertices(session_id: str) -> list[tuple[float, float, float]]:
    with tempfile.TemporaryDirectory(prefix="cdmw_history_vertices_") as temp_dir:
        path = Path(temp_dir) / "vertices.bin"
        report = mesh_native_core.export_native_mesh_editor_session_snapshot(
            session_id,
            [{"index": 0, "vertices_output_path": str(path)}],
            timeout_seconds=5.0,
        )
        assert report is not None
        return [tuple(values) for values in struct.iter_unpack("=ddd", path.read_bytes())]


def _open_selected_native_session(mesh: ParsedMesh, *, vertices: tuple[int, ...]) -> str:
    session_id = f"history-{uuid4().hex}"
    assert mesh_native_core.open_native_mesh_editor_session(mesh, session_id, timeout_seconds=10.0) is not None
    assert mesh_native_core.select_native_mesh_editor_session(
        session_id,
        {"vertices_by_submesh": {0: vertices}},
        timeout_seconds=5.0,
    ) is not None
    return session_id


def test_python_history_evicts_whole_units_by_count_and_bytes() -> None:
    with (
        patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", return_value=None),
        patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=False),
    ):
        service = MeshService(max_history=64, max_history_bytes=1 << 30)
        view = service.open_edit_session(_mesh(first_x=0.0), session_id="python-history-bounds")
        service.replace_working_mesh(view.session_id, _mesh(first_x=1.0))
        one_unit_bytes = service.history_usage(view.session_id)["python_retained_bytes"]
        service.max_history_bytes = one_unit_bytes * 2 + 128
        service.replace_working_mesh(view.session_id, _mesh(first_x=2.0))
        service.replace_working_mesh(view.session_id, _mesh(first_x=3.0))

        usage = service.history_usage(view.session_id)
        assert usage["undo_count"] == 2
        assert usage["retained_bytes"] <= service.max_history_bytes
        assert service.undo(view.session_id).ok
        assert service.working_mesh(view.session_id).submeshes[0].vertices[0] == (2.0, 0.0, 0.0)
        assert service.undo(view.session_id).ok
        assert service.working_mesh(view.session_id).submeshes[0].vertices[0] == (1.0, 0.0, 0.0)
        assert service.undo(view.session_id).status == "noop"

        count_service = MeshService(max_history=3, max_history_bytes=1 << 30)
        count_view = count_service.open_edit_session(_mesh(first_x=0.0), session_id="python-history-count")
        for value in range(1, 5):
            count_service.replace_working_mesh(count_view.session_id, _mesh(first_x=float(value)))
        assert count_service.history_usage(count_view.session_id)["undo_count"] == 3


def test_native_sparse_history_is_exact_and_branch_safe() -> None:
    _native_required()
    session_id = _open_selected_native_session(_mesh(), vertices=(1,))
    try:
        for amount in (1.0, 2.0):
            assert mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {"operation": "transform", "translate": (amount, 0.0, 0.0), "recompute_normals": False},
                capture_deltas=False,
                timeout_seconds=10.0,
            ) is not None
        assert mesh_native_core.undo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        ) is not None
        assert _export_vertices(session_id)[1] == pytest.approx((2.0, 0.0, 0.0))

        assert mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {"operation": "transform", "translate": (4.0, 0.0, 0.0), "recompute_normals": False},
            capture_deltas=False,
            timeout_seconds=10.0,
        ) is not None
        summary = mesh_native_core.summarize_native_mesh_editor_session(session_id, timeout_seconds=5.0)
        assert summary is not None
        assert summary["history_redo_count"] == 0
        assert mesh_native_core.redo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=5.0
        ) is None
        assert mesh_native_core.undo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        ) is not None
        assert _export_vertices(session_id)[1] == pytest.approx((2.0, 0.0, 0.0))
        assert mesh_native_core.redo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        ) is not None
        assert _export_vertices(session_id)[1] == pytest.approx((6.0, 0.0, 0.0))
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_native_record_history_false_edits_without_creating_undo_unit() -> None:
    _native_required()
    session_id = _open_selected_native_session(_mesh(), vertices=(1,))
    try:
        report = mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {
                "operation": "transform",
                "translate": (0.25, 0.0, 0.0),
                "recompute_normals": False,
                "record_history": False,
            },
            capture_deltas=False,
            timeout_seconds=10.0,
        )
        assert report is not None
        assert report["history_undo_count"] == 0
        assert _export_vertices(session_id)[1] == pytest.approx((1.25, 0.0, 0.0))
        assert mesh_native_core.undo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=5.0
        ) is None
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_native_sparse_history_retains_changed_channels_not_full_mesh() -> None:
    _native_required()
    session_id = _open_selected_native_session(_mesh(vertex_count=20_000), vertices=(1,))
    try:
        report = mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {"operation": "transform", "translate": (0.25, 0.0, 0.0), "recompute_normals": False},
            capture_deltas=False,
            timeout_seconds=10.0,
        )
        assert report is not None
        assert report["history_undo_count"] == 1
        assert report["history_retained_bytes"] < 128 * 1024
        assert report["history_retained_bytes"] <= report["history_max_bytes"]
        assert mesh_native_core.undo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        ) is not None
        assert _export_vertices(session_id)[1] == pytest.approx((1.0, 0.0, 0.0))
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_native_snapshot_restore_reuses_existing_payload_files() -> None:
    _native_required()
    snapshot = mesh_native_core.snapshot_native_mesh_submeshes(_mesh())
    assert snapshot is not None
    try:
        with patch.object(
            mesh_native_core,
            "_export_native_submesh_snapshot_handle",
            side_effect=AssertionError("redundant snapshot export"),
        ):
            first = ParsedMesh()
            second = ParsedMesh()
            assert mesh_native_core.restore_native_mesh_submesh_snapshot(first, snapshot)
            assert mesh_native_core.restore_native_mesh_submesh_snapshot(second, snapshot)
        assert first.submeshes[0].vertices == second.submeshes[0].vertices == _mesh().submeshes[0].vertices
    finally:
        mesh_native_core.dispose_native_mesh_submesh_snapshot(snapshot)


def test_native_history_evicts_oldest_whole_units_at_64_and_keeps_old_fields() -> None:
    _native_required()
    session_id = _open_selected_native_session(_mesh(), vertices=(1,))
    try:
        for _ in range(65):
            assert mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {"operation": "transform", "translate": (0.01, 0.0, 0.0), "recompute_normals": False},
                capture_deltas=False,
                timeout_seconds=10.0,
            ) is not None
        summary = mesh_native_core.summarize_native_mesh_editor_session(session_id, timeout_seconds=5.0)
        assert summary is not None
        assert summary["history_undo_count"] == summary["history_max_operations"] == 64
        assert summary["history_retained_bytes"] <= summary["history_max_bytes"] == 256 * 1024 * 1024
        for old_field in ("submesh_count", "vertex_count", "face_count", "submeshes", "edit_revision"):
            assert old_field in summary

        for _ in range(64):
            assert mesh_native_core.undo_native_mesh_editor_session(
                session_id, capture_deltas=False, timeout_seconds=10.0
            ) is not None
        assert _export_vertices(session_id)[1] == pytest.approx((1.01, 0.0, 0.0))
        assert mesh_native_core.undo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=5.0
        ) is None
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_native_topology_history_swaps_one_affected_snapshot_for_undo_redo() -> None:
    _native_required()
    session_id = f"topology-history-{uuid4().hex}"
    try:
        assert mesh_native_core.open_native_mesh_editor_session(_mesh(), session_id, timeout_seconds=10.0) is not None
        assert mesh_native_core.select_native_mesh_editor_session(
            session_id,
            {"faces_by_submesh": {0: (0,)}},
            timeout_seconds=5.0,
        ) is not None
        deleted = mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {"operation": "delete"},
            capture_deltas=False,
            timeout_seconds=10.0,
        )
        assert deleted is not None
        assert deleted["topology_changed"] is True
        assert (deleted["vertex_count"], deleted["face_count"]) == (3, 1)

        restored = mesh_native_core.undo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        )
        assert restored is not None
        assert restored["topology_changed"] is True
        assert (restored["vertex_count"], restored["face_count"]) == (4, 2)
        assert restored["history_undo_count"] == 0
        assert restored["history_redo_count"] == 1

        removed_again = mesh_native_core.redo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        )
        assert removed_again is not None
        assert (removed_again["vertex_count"], removed_again["face_count"]) == (3, 1)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_native_global_topology_scope_and_history_follow_selected_submesh() -> None:
    _native_required()
    session_id = f"topology-scope-{uuid4().hex}"
    try:
        assert mesh_native_core.open_native_mesh_editor_session(
            _two_loose_submesh_mesh(), session_id, timeout_seconds=10.0
        ) is not None
        assert mesh_native_core.select_native_mesh_editor_session(
            session_id, {"source_indices": (0,)}, timeout_seconds=5.0
        ) is not None
        compacted = mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {"operation": "compact_orphans"},
            capture_deltas=False,
            timeout_seconds=10.0,
        )
        assert compacted is not None
        assert compacted["affected_submesh_indices"] == [0]
        assert {item["index"]: item["vertex_count"] for item in compacted["submeshes"]} == {0: 4, 1: 5}

        restored = mesh_native_core.undo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        )
        assert restored is not None
        assert {item["index"]: item["vertex_count"] for item in restored["submeshes"]} == {0: 5, 1: 5}
        redone = mesh_native_core.redo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        )
        assert redone is not None
        assert {item["index"]: item["vertex_count"] for item in redone["submeshes"]} == {0: 4, 1: 5}
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_native_component_material_history_captures_metadata_only_edit() -> None:
    _native_required()
    session_id = f"material-history-{uuid4().hex}"
    try:
        assert mesh_native_core.open_native_mesh_editor_session(
            _mesh(), session_id, timeout_seconds=10.0
        ) is not None
        assert mesh_native_core.select_native_mesh_editor_session(
            session_id,
            {"source_indices": (0,), "faces_by_submesh": {0: (0, 1)}},
            timeout_seconds=5.0,
        ) is not None
        assigned = mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {"operation": "material_assign", "material": "edited", "texture": "edited.dds"},
            capture_deltas=False,
            timeout_seconds=10.0,
        )
        assert assigned is not None
        assert assigned["topology_changed"] is False
        assert assigned["history_undo_count"] == 1
        assert assigned["submeshes"][0]["material"] == "edited"

        restored = mesh_native_core.undo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        )
        assert restored is not None
        assert restored["submeshes"][0]["material"] == "mat"
        redone = mesh_native_core.redo_native_mesh_editor_session(
            session_id, capture_deltas=False, timeout_seconds=10.0
        )
        assert redone is not None
        assert redone["submeshes"][0]["material"] == "edited"
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_mesh_service_reports_native_and_python_retained_history_bytes() -> None:
    _native_required()
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id=f"service-history-{uuid4().hex}", mode="edit")
    try:
        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)}),
                params={"translate": (0.25, 0.0, 0.0), "recompute_normals": False},
                mode="edit",
            ),
        )
        usage = service.history_usage(view.session_id)
        assert result.ok
        assert usage["undo_count"] == usage["native_undo_count"] == 1
        assert usage["native_retained_bytes"] > 0
        assert usage["retained_bytes"] == usage["python_retained_bytes"] + usage["native_retained_bytes"]
        assert result.metrics["native_history_retained_bytes"] == usage["native_retained_bytes"]
        assert result.metrics["native_resident_sparse_update_count"] == 1
    finally:
        service.close_edit_session(view.session_id)


def test_native_service_inlines_job_report_and_keeps_file_protocol() -> None:
    _native_required()
    binary = mesh_native_core.find_native_mesh_core_binary()
    assert binary is not None
    process = subprocess.Popen(
        [str(binary), "--service"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert json.loads(process.stdout.readline())["event"] == "ready"

    def request(payload: dict[str, object]) -> dict[str, object]:
        process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        assert isinstance(response, dict)
        return response

    session_id = f"inline-history-{uuid4().hex}"
    vertices = [[float(index), 0.0, 0.0] for index in range(300)]
    try:
        assert request({"command": "ping"})["event"] == "pong"
        opened = request(
            {
                "command": "mesh-editor-session-json",
                "payload": {
                    "command": "open",
                    "session_id": session_id,
                    "submeshes": [{"index": 0, "vertices": vertices, "faces": [[0, 1, 2]]}],
                },
            }
        )
        assert opened["status"] == "ok"

        with tempfile.TemporaryDirectory(prefix="cdmw_inline_delta_test_") as delta_dir:
            applied = request(
                {
                    "command": "mesh-editor-session-json",
                    "payload": {
                        "command": "apply",
                        "session_id": session_id,
                        "selection": {"vertices_by_submesh": {"0": list(range(300))}},
                        "edit": {
                            "operation": "transform",
                            "translate": [0.0, 0.0, 0.25],
                            "recompute_normals": False,
                        },
                        "delta_output_dir": delta_dir,
                        "include_edit_report": True,
                        "include_preview_deltas": True,
                    },
                }
            )
            report = applied["inline_report"]
            assert applied["status"] == report["status"] == "ok"
            item = report["edit_report"]["submeshes"][0]
            changed_positions = item["changed_positions_binary"]
            preview_positions = item["preview_vertex_update_group"]["positions_binary"]
            assert changed_positions["path"] == preview_positions["path"]
            assert Path(changed_positions["path"]).parent == Path(delta_dir)
            assert Path(changed_positions["path"]).is_file()
            assert list(Path(delta_dir).iterdir())

        with tempfile.TemporaryDirectory(prefix="cdmw_file_protocol_test_") as root:
            job_path = Path(root) / "job.json"
            report_path = Path(root) / "report.json"
            job_path.write_text(
                json.dumps({"command": "summary", "session_id": session_id}),
                encoding="utf-8",
            )
            response = request(
                {
                    "command": "mesh-editor-session-json",
                    "job_path": str(job_path),
                    "report_path": str(report_path),
                }
            )
            assert response["status"] == "ok"
            assert json.loads(report_path.read_text(encoding="utf-8"))["vertex_count"] == 300
    finally:
        if process.poll() is None:
            try:
                request({"command": "shutdown"})
            except (BrokenPipeError, json.JSONDecodeError, OSError):
                process.kill()
        process.wait(timeout=5)
