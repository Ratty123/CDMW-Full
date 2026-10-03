from __future__ import annotations

import hashlib
from array import array
from dataclasses import replace
from types import SimpleNamespace
import threading
import tempfile
import unittest
from collections.abc import Iterable, Mapping
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cdmw.domain.mesh import (
    MESH_EDIT_ACTIONS,
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
    MeshEditCommand,
    MeshEditSelection,
    mesh_animation_clip_from_document,
)
from cdmw.domain.mesh.export_validation import validate_mesh_export
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_importer import MeshRebuildReport
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service import _add_native_editor_screen_selection_payload
from cdmw.services.mesh_service import _native_editor_edit_payload


def _quad_mesh(*, two_parts: bool = False) -> ParsedMesh:
    submesh = SubMesh(
        name="quad",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[(0, 1, 2), (1, 3, 2)],
        vertex_count=4,
        face_count=2,
    )
    submeshes = [submesh]
    if two_parts:
        second = SubMesh(
            name="quad_b",
            material="mat_b",
            texture="b.dds",
            vertices=list(submesh.vertices),
            uvs=list(submesh.uvs),
            normals=list(submesh.normals),
            faces=list(submesh.faces),
            vertex_count=4,
            face_count=2,
        )
        submeshes.append(second)
    return ParsedMesh(path="quad.pac", format="pac", submeshes=submeshes, total_vertices=4 * len(submeshes), total_faces=2 * len(submeshes), has_uvs=True)


def _changed_vertices_as_set(result: object, submesh_index: int = 0) -> set[int]:
    changed = dict(getattr(result, "changed_vertices_by_submesh"))[submesh_index]
    if isinstance(changed, Mapping):
        descriptor = changed.get("changed_vertices_binary")
        if isinstance(descriptor, Mapping):
            from cdmw.modding.mesh_native_core import _read_i32_binary_report_payload

            count = int(descriptor.get("count", 0) or 0)
            return set(_read_i32_binary_report_payload(descriptor, expected_count=count) or ())
    return {int(value) for value in changed}  # type: ignore[union-attr]


def _large_mesh_for_native_fallback_guard() -> ParsedMesh:
    vertex_count = 10_001
    vertices = [(float(index), 0.0, 0.0) for index in range(vertex_count)]
    submesh = SubMesh(
        name="large",
        material="mat_a",
        texture="a.dds",
        vertices=vertices,
        uvs=[(0.0, 0.0)] * vertex_count,
        normals=[(0.0, 0.0, 1.0)] * vertex_count,
        faces=[(0, 1, 2)],
        vertex_count=vertex_count,
        face_count=1,
    )
    return ParsedMesh(path="large.pac", format="pac", submeshes=[submesh], total_vertices=vertex_count, total_faces=1, has_uvs=True)


def _spike_mesh() -> ParsedMesh:
    return ParsedMesh(
        path="spike.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="spike",
                material="mat_a",
                texture="a.dds",
                vertices=[
                    (0.0, 0.0, 1.0),
                    (-1.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                    (0.0, -1.0, 0.0),
                    (0.0, 1.0, 0.0),
                ],
                uvs=[(0.5, 0.5), (0.0, 0.5), (1.0, 0.5), (0.5, 0.0), (0.5, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 5,
                faces=[(0, 1, 3), (0, 3, 2), (0, 2, 4), (0, 4, 1)],
                vertex_count=5,
                face_count=4,
            )
        ],
        total_vertices=5,
        total_faces=4,
        has_uvs=True,
    )


def _bent_two_face_mesh() -> ParsedMesh:
    return ParsedMesh(
        path="bent.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="bent",
                material="mat_a",
                texture="a.dds",
                vertices=[
                    (0.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                    (0.0, 1.0, 0.0),
                    (0.0, 0.0, 1.0),
                ],
                uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 4,
                faces=[(0, 1, 2), (0, 1, 3)],
                vertex_count=4,
                face_count=2,
            )
        ],
        total_vertices=4,
        total_faces=2,
        has_uvs=True,
    )


def _malformed_face_mesh() -> ParsedMesh:
    mesh = _quad_mesh()
    submesh = mesh.submeshes[0]
    submesh.faces = [
        (0, "bad", 3),
        (0, 1, 2),
        (0, float("inf"), 2),
        (0, True, 2),
        (0, 1.9, 2),
    ]  # type: ignore[list-item]
    submesh.face_count = len(submesh.faces)
    mesh.total_faces = len(submesh.faces)
    return mesh


def _loose_edge_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="loose_edges",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[],
        vertex_count=4,
        face_count=0,
    )
    return ParsedMesh(path="loose_edges.pac", format="pac", submeshes=[submesh], total_vertices=4, total_faces=0, has_uvs=True)


def _triangle_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="triangle",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(path="triangle.pac", format="pac", submeshes=[submesh], total_vertices=3, total_faces=1, has_uvs=True)


def _duplicate_vertex_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="duplicate_vertex",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 5,
        faces=[(0, 1, 2), (1, 3, 2), (0, 4, 2)],
        vertex_count=5,
        face_count=3,
    )
    return ParsedMesh(path="duplicate_vertex.pac", format="pac", submeshes=[submesh], total_vertices=5, total_faces=3, has_uvs=True)


def _two_uv_island_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="uv_islands",
        material="mat",
        texture="uv.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (3.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (3.0, 1.0, 0.0),
        ],
        uvs=[
            (0.0, 0.0),
            (0.5, 0.0),
            (0.0, 0.5),
            (2.0, 0.0),
            (2.5, 0.0),
            (2.0, 0.5),
        ],
        normals=[(0.0, 0.0, 1.0)] * 6,
        faces=[(0, 1, 2), (3, 4, 5)],
        vertex_count=6,
        face_count=2,
    )
    return ParsedMesh(path="uv_islands.pac", format="pac", submeshes=[submesh], total_vertices=6, total_faces=2, has_uvs=True)


def _overlapping_uv_island_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="overlapping_uv_islands",
        material="mat",
        texture="uv.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (3.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (3.0, 1.0, 0.0),
        ],
        uvs=[
            (0.0, 0.0),
            (1.0, 0.0),
            (0.0, 1.0),
            (0.0, 0.0),
            (1.0, 0.0),
            (0.0, 1.0),
        ],
        normals=[(0.0, 0.0, 1.0)] * 6,
        faces=[(0, 1, 2), (3, 4, 5)],
        vertex_count=6,
        face_count=2,
    )
    return ParsedMesh(path="overlapping_uv_islands.pac", format="pac", submeshes=[submesh], total_vertices=6, total_faces=2, has_uvs=True)


class MeshServiceEditingTests(unittest.TestCase):
    def test_owned_shadow_session_adopts_its_disposable_working_mesh(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        base = _quad_mesh()
        with (
            patch(
                "cdmw.services.mesh_service._clone_mesh_pair_for_session_open",
                side_effect=AssertionError("adopted shadow must not clone a working pair"),
            ),
            patch(
                "cdmw.services.mesh_service._clone_mesh_for_service_native_snapshot",
                return_value=base,
            ) as base_clone,
        ):
            view = service.open_edit_session(
                mesh,
                session_id="owned-shadow",
                mode="edit",
                load_layer_project=False,
                adopt_owned_mesh=True,
            )

        self.assertIs(mesh, service.working_mesh(view.session_id, clone=False))
        self.assertIs(base, service._session(view.session_id).base_mesh)
        base_clone.assert_called_once()

        with self.assertRaisesRegex(ValueError, "cannot load a mutable layer project"):
            MeshService().open_edit_session(
                _quad_mesh(),
                load_layer_project=True,
                adopt_owned_mesh=True,
            )


    def test_native_binary_readers_reject_non_finite_and_out_of_bounds(self) -> None:
        from cdmw.modding.mesh_native_core import (
            _read_face_binary_report_payload,
            _read_vec2_binary_report_payload,
            _read_vec3_binary_report_payload,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vec3_path = root / "vec3.bin"
            vec2_path = root / "vec2.bin"
            faces_path = root / "faces.bin"
            vec3_path.write_bytes(array("d", [0.0, float("nan"), 1.0]).tobytes())
            vec2_path.write_bytes(array("d", [0.0, float("inf")]).tobytes())
            faces_path.write_bytes(array("i", [0, 1, 4]).tobytes())

            self.assertIsNone(_read_vec3_binary_report_payload({"path": str(vec3_path), "count": 1, "components": 3, "type": "f64"}, expected_count=1))
            self.assertIsNone(_read_vec2_binary_report_payload({"path": str(vec2_path), "count": 1, "components": 2, "type": "f64"}, expected_count=1))
            self.assertIsNone(_read_face_binary_report_payload({"path": str(faces_path), "count": 1, "components": 3, "type": "i32"}, expected_count=1, vertex_count=4))


    def test_service_geometry_action_uses_native_editor_session_path(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-editor-session-service", mode="edit")
        command = MeshEditCommand(
            "delete",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            params={"_include_preview_deltas": False},
            mode="edit",
        )
        report = {
            "status": "ok",
            "topology_changed": True,
            "submesh_count": 1,
            "affected_submesh_indices": [0],
            "submeshes": [{"index": 0, "vertex_count": 3, "face_count": 1}],
            "metrics": {"cpp_ms": 1.25, "io_serialization_ms": 0.5},
            "edit_report": {
                "operation": "delete",
                "submeshes": [{"index": 0, "vertex_count": 3, "face_count": 1, "changed_vertices": [0, 1, 2]}],
            },
        }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}) as opened,
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session", side_effect=AssertionError("edit apply should inline native selection")) as selected,
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", return_value=report) as applied,
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("native mesh hydrated")),
            patch("cdmw.services.mesh_service._prune_selection_to_mesh", side_effect=AssertionError("native topology should clear selection without Python prune")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            result = service.apply_command(view.session_id, command)

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertTrue(service._session(view.session_id).selection.is_empty())
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(1.0, result.metrics["python_apply_deferred"])
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual(1, service.session_view(view.session_id).face_count)
        opened.assert_called_once()
        selected.assert_not_called()
        applied.assert_called_once()
        self.assertEqual("delete", applied.call_args.args[1]["operation"])
        self.assertNotIn("_include_preview_deltas", applied.call_args.args[1])
        self.assertFalse(applied.call_args.kwargs["include_preview_deltas"])
        self.assertEqual(
            {"vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {0: {0}}},
            applied.call_args.kwargs["selection"],
        )
        self.assertEqual(1.25, result.metrics["cpp_ms"])
        self.assertEqual(0.5, result.metrics["io_serialization_ms"])
        self.assertGreaterEqual(result.metrics["python_apply_ms"], 0.0)
        self.assertGreaterEqual(result.metrics["editor_open_roundtrip_ms"], 0.0)
        self.assertEqual(0.0, result.metrics["editor_select_roundtrip_ms"])
        self.assertEqual(1.0, result.metrics["editor_select_inlined"])
        self.assertGreaterEqual(result.metrics["native_apply_roundtrip_ms"], 0.0)
        self.assertGreaterEqual(result.metrics["native_apply_overhead_ms"], 0.0)
        self.assertGreaterEqual(result.metrics["service_dispatch_ms"], 0.0)
        self.assertGreaterEqual(result.metrics["service_total_ms"], 0.0)

    def test_service_chains_dirty_native_geometry_without_python_mesh_export(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-editor-dirty-geometry-chain", mode="edit")
        command = MeshEditCommand(
            "transform",
            selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}),
            params={"delta": (0.0, 0.0, 0.25), "_include_preview_deltas": False},
            mode="edit",
        )
        apply_count = 0

        def transform_report() -> dict[str, object]:
            nonlocal apply_count
            apply_count += 1
            return {
                "status": "ok",
                "topology_changed": False,
                "submesh_count": 1,
                "affected_submesh_indices": [0],
                "submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}],
                "metrics": {"cpp_ms": float(apply_count), "io_serialization_ms": 0.5},
                "edit_report": {
                    "operation": "transform",
                    "submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2, "changed_vertices": [0, 1]}],
                },
            }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}) as opened,
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", side_effect=lambda *_args, **_kwargs: transform_report()),
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("dirty native geometry hydrated Python mesh")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            first = service.apply_command(view.session_id, command)
            second = service.apply_command(view.session_id, command)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(1.0, first.metrics["python_apply_deferred"])
        self.assertEqual(1.0, second.metrics["python_apply_deferred"])
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        opened.assert_called_once()
        self.assertEqual(2, apply_count)


    def test_native_dirty_topology_undo_redo_stays_resident_until_mesh_read(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-editor-dirty-history", mode="edit")
        command = MeshEditCommand(
            "subdivide",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            mode="edit",
        )

        def topology_report(command_name: str, vertex_count: int, face_count: int) -> dict[str, object]:
            return {
                "status": "ok",
                "protocol": "mesh-editor-session-json",
                "command": command_name,
                "topology_changed": True,
                "submesh_count": 1,
                "vertex_count": vertex_count,
                "face_count": face_count,
                "affected_submesh_indices": [0],
                "submeshes": [{"index": 0, "name": "quad", "material": "mat", "texture": "a.dds", "vertex_count": vertex_count, "face_count": face_count}],
                "metrics": {"cpp_ms": 1.0, "io_serialization_ms": 0.5},
                "edit_report": {
                    "operation": command_name,
                    "topology_changed": True,
                    "submeshes": [
                        {
                            "index": 0,
                            "vertex_count": vertex_count,
                            "face_count": face_count,
                            "preview_triangle_group": {
                                "preview_backend": "cdmw_mesh_core",
                                "source_submesh_index": 0,
                                "face_count": face_count,
                            },
                        }
                    ],
                },
            }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", return_value=topology_report("subdivide", 5, 4)),
            patch("cdmw.services.mesh_service.undo_native_mesh_editor_session", return_value=topology_report("undo", 4, 2)),
            patch("cdmw.services.mesh_service.redo_native_mesh_editor_session", return_value=topology_report("redo", 5, 4)),
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("dirty native history should not export before mesh read")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            applied = service.apply_command(view.session_id, command)
            undo = service.undo(view.session_id)
            undo_view = service.session_view(view.session_id)
            redo = service.redo(view.session_id)
            redo_view = service.session_view(view.session_id)

        session = service._session(view.session_id)
        self.assertTrue(applied.ok)
        self.assertTrue(undo.ok)
        self.assertTrue(redo.ok)
        self.assertTrue(session.native_editor_mesh_dirty)
        self.assertEqual(1.0, applied.metrics["python_apply_deferred"])
        self.assertEqual(1.0, undo.metrics["python_apply_deferred"])
        self.assertEqual(1.0, redo.metrics["python_apply_deferred"])
        self.assertEqual(4, undo_view.vertex_count)
        self.assertEqual(2, undo_view.face_count)
        self.assertEqual(5, redo_view.vertex_count)
        self.assertEqual(4, redo_view.face_count)


    def test_dirty_native_undo_redo_blocks_python_history_fallback(self) -> None:
        from cdmw.services import mesh_service as mesh_service_module

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dirty-history-fallback", mode="edit")
        session = service._session(view.session_id)
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((5, 4),)
        legacy_snapshot = mesh_service_module._MeshHistorySnapshot(
            mesh=_quad_mesh(),
            mode="edit",
            selection=MeshEditSelection(),
        )
        session.undo_stack.append(legacy_snapshot)
        session.redo_stack.append(
            mesh_service_module._MeshHistorySnapshot(
                mesh=_quad_mesh(),
                mode="edit",
                selection=MeshEditSelection(),
            )
        )

        with (
            patch("cdmw.services.mesh_service._sync_native_editor_session_to_working_mesh", side_effect=AssertionError("undo exported dirty native mesh")),
            self.assertRaisesRegex(RuntimeError, "undo requires native history"),
        ):
            service.undo(view.session_id)
        with (
            patch("cdmw.services.mesh_service._sync_native_editor_session_to_working_mesh", side_effect=AssertionError("redo exported dirty native mesh")),
            self.assertRaisesRegex(RuntimeError, "redo requires native history"),
        ):
            service.redo(view.session_id)


    def test_service_native_editor_session_failure_blocks_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-editor-session-fail-closed", mode="edit")
        command = MeshEditCommand("delete", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), mode="edit")

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value=None),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("history snapshot fallback used")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Python mesh-edit fallback is disabled"):
                service.apply_command(view.session_id, command)

        self.assertEqual(2, service.working_mesh(view.session_id).total_faces)
        self.assertEqual(0, service.session_view(view.session_id).undo_count)

    def test_service_native_editor_session_missing_core_blocks_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-editor-session-missing-core", mode="edit")
        command = MeshEditCommand("delete", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), mode="edit")

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=False),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("history snapshot fallback used")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            with self.assertRaisesRegex(RuntimeError, "native mesh editor unavailable.*Python mesh-edit fallback is disabled"):
                service.apply_command(view.session_id, command)

        self.assertEqual(2, service.working_mesh(view.session_id).total_faces)
        self.assertEqual(0, service.session_view(view.session_id).undo_count)

    def test_service_native_editor_session_undo_redo_uses_native_history(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-editor-session-history", mode="edit")
        command = MeshEditCommand("delete", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), mode="edit")

        def native_history_report(command_name: str, vertex_count: int, face_count: int) -> dict[str, object]:
            return {
                "command": command_name,
                "topology_changed": True,
                "submesh_count": 1,
                "affected_submesh_indices": [0],
                "submeshes": [{"index": 0, "vertex_count": vertex_count, "face_count": face_count}],
                "edit_report": {
                    "submeshes": [
                        {
                            "index": 0,
                            "vertex_count": vertex_count,
                            "face_count": face_count,
                            "changed_vertices": list(range(vertex_count)),
                        }
                    ]
                },
            }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", return_value=native_history_report("apply", 3, 1)),
            patch("cdmw.services.mesh_service.undo_native_mesh_editor_session", return_value=native_history_report("undo", 4, 2)) as undone,
            patch("cdmw.services.mesh_service.redo_native_mesh_editor_session", return_value=native_history_report("redo", 3, 1)) as redone,
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("native mesh hydrated")),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("python/native snapshot used")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            deleted = service.apply_command(view.session_id, command)
            undo = service.undo(view.session_id)
            undo_view = service.session_view(view.session_id)
            redo = service.redo(view.session_id)
            redo_view = service.session_view(view.session_id)

        self.assertTrue(deleted.ok)
        self.assertTrue(undo.ok)
        self.assertTrue(redo.ok)
        self.assertTrue(undo.topology_changed)
        self.assertTrue(redo.topology_changed)
        self.assertEqual(1.0, deleted.metrics["python_apply_deferred"])
        self.assertEqual(1.0, undo.metrics["python_apply_deferred"])
        self.assertEqual(1.0, redo.metrics["python_apply_deferred"])
        self.assertGreaterEqual(undo.metrics["native_history_roundtrip_ms"], 0.0)
        self.assertGreaterEqual(undo.metrics["python_apply_ms"], 0.0)
        self.assertGreaterEqual(undo.metrics["service_total_ms"], 0.0)
        self.assertGreaterEqual(redo.metrics["native_history_roundtrip_ms"], 0.0)
        self.assertGreaterEqual(redo.metrics["python_apply_ms"], 0.0)
        self.assertGreaterEqual(redo.metrics["service_total_ms"], 0.0)
        self.assertEqual(2, undo_view.face_count)
        self.assertEqual(1, redo_view.face_count)
        undone.assert_called_once()
        redone.assert_called_once()


    def test_file_session_validation_exposes_mesh_asset_roundtrip_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_path = Path(temp_dir) / "part.pac"
            mesh_path.write_bytes(b"PAR original bytes")
            parsed = _quad_mesh()
            parsed.path = ""
            service = MeshService()

            with (
                patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed),
                patch(
                    "cdmw.services.mesh_service.roundtrip_mesh_bytes",
                    return_value=SimpleNamespace(
                        report={
                            "result": "PASS",
                            "byte_identical": True,
                            "unexpected_differences": 0,
                        }
                    ),
                ) as roundtrip,
            ):
                mesh = service.load_mesh_file(mesh_path, run_roundtrip=True)
                view = service.open_edit_session(mesh, session_id="roundtrip-status", mode="edit")

            report = service.validate_export(view.session_id, available_textures=("a.dds",))

            roundtrip.assert_called_once()
            self.assertEqual("inferred", report.parse_confidence)
            self.assertEqual("PASS", report.no_op_roundtrip_status)
            self.assertIs(report.no_op_byte_identical, True)
            self.assertEqual(0, report.no_op_unexpected_differences)
            self.assertTrue(report.source_asset_hash)
            self.assertTrue(report.ok)
            self.assertIn("inferred_parse_confidence", {issue.code for issue in report.warnings})


    def test_file_session_validation_blocks_failed_mesh_asset_roundtrip(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "FAIL", "byte_identical": False, "unexpected_differences": 1},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="roundtrip-failed", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blockers = {issue.code for issue in report.blockers}
        self.assertFalse(report.ok)
        self.assertIn("no_op_roundtrip_not_passed", blockers)
        self.assertIn("no_op_roundtrip_unexpected_differences", blockers)

    def test_file_session_validation_blocks_fallback_scan_parse_confidence(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "fallback_scan")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="fallback-parse-confidence", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertFalse(report.ok)
        self.assertIn("unsafe_parse_confidence", {issue.code for issue in report.blockers})

    def test_replace_working_mesh_preserves_original_contract_and_import_operations(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        mesh.has_bones = True
        mesh.submeshes[0].bone_indices = [(0,), (0,), (1,), (1,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", 2)
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(mesh, "_cdmw_no_op_roundtrip_report", {"result": "PASS", "byte_identical": True, "unexpected_differences": 0})
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="replace-working-mesh", mode="edit")
        imported = _quad_mesh()
        imported.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        imported.submeshes[0].vertices[0] = (0.25, 0.0, 0.0)
        setattr(imported, "_cdmw_imported_from_obj", True)
        setattr(imported, "_cdmw_obj_sidecar_present", True)
        setattr(
            imported,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )

        updated = service.replace_working_mesh(view.session_id, imported)
        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertEqual(1, updated.revision)
        self.assertEqual(1, updated.undo_count)
        self.assertEqual("Replace Working Mesh", updated.history_entries[0].label)
        working = service.working_mesh(view.session_id, clone=False)
        self.assertEqual(b"original", getattr(working, "_cdmw_original_data"))
        self.assertEqual([(0,), (0,), (1,), (1,)], working.submeshes[0].bone_indices)
        self.assertEqual([(1.0,), (1.0,), (1.0,), (1.0,)], working.submeshes[0].bone_weights)
        self.assertEqual((0.0, 0.0, 0.0), service.base_mesh(view.session_id, clone=False).submeshes[0].vertices[0])
        self.assertTrue(report.ok)
        self.assertEqual("replace_positions_same_count", service._sessions[view.session_id].edit_operations[0]["operation"])
    def test_replace_working_mesh_preserves_selection_for_same_topology_import(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="replace-preserve-selection", mode="edit")
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh={0: {0, 2}},
            faces_by_submesh={0: {1}},
            source_indices={1},
        )
        service._sessions[view.session_id].selection = selection
        imported = _quad_mesh(two_parts=True)
        imported.submeshes[0].vertices[0] = (0.25, 0.0, 0.0)

        updated = service.replace_working_mesh(view.session_id, imported)

        self.assertEqual(selection, updated.selection)
        self.assertEqual(selection, service.session_view(view.session_id).selection)
        self.assertFalse(hasattr(service.working_mesh(view.session_id, clone=False), "_cdmw_selection_diagnostics"))

    def test_replace_working_mesh_clears_selection_with_diagnostic_for_topology_change(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="replace-clear-selection", mode="edit")
        service._sessions[view.session_id].selection = MeshEditSelection.from_maps(
            vertices_by_submesh={0: {0, 2}},
            faces_by_submesh={0: {1}},
        )
        imported = _quad_mesh()
        imported.submeshes[0].vertices.append((2.0, 2.0, 0.0))
        imported.submeshes[0].vertex_count = len(imported.submeshes[0].vertices)
        imported.total_vertices = len(imported.submeshes[0].vertices)

        updated = service.replace_working_mesh(view.session_id, imported)
        working = service.working_mesh(view.session_id, clone=False)

        self.assertTrue(updated.selection.is_empty())
        self.assertTrue(service.session_view(view.session_id).selection.is_empty())
        diagnostics = tuple(getattr(working, "_cdmw_selection_diagnostics", ()) or ())
        self.assertTrue(diagnostics)
        self.assertIn("selection_cleared_after_external_import", diagnostics[0])
        self.assertIn("topology changed", diagnostics[0])
        self.assertEqual(1, updated.undo_count)
        self.assertEqual(1, updated.revision)

    def test_replace_working_mesh_blocks_obj_sidecar_source_hash_mismatch(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_original_data", b"original")
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="replace-working-hash-mismatch", mode="edit")
        imported = _quad_mesh()
        setattr(imported, "_cdmw_imported_from_obj", True)
        setattr(imported, "_cdmw_obj_sidecar_present", True)
        setattr(imported, "_cdmw_sidecar_source_asset_hash", hashlib.sha256(b"different").hexdigest())
        setattr(imported, "_cdmw_sidecar_source_asset_size", len(b"original"))

        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            service.replace_working_mesh(view.session_id, imported)


    def test_rebuild_report_uses_validated_session_and_original_bytes(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        setattr(
            mesh,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-report", mode="edit")
        base_report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="abc123",
            rebuilt_asset_hash="abc123",
            source_size=8,
            rebuilt_size=8,
            parse_confidence="exact",
            validation_status="passed",
            byte_identical=True,
            changed_byte_ranges=(),
            output_path="out.pac",
        )

        with patch(
            "cdmw.services.mesh_service.rebuild_mesh_with_report",
            return_value=SimpleNamespace(data=b"original", report=base_report),
        ) as rebuilt:
            report = service.rebuild_report(
                view.session_id,
                available_textures=("a.dds",),
                output_path="out.pac",
            )

        rebuilt.assert_called_once()
        self.assertEqual(b"original", rebuilt.call_args.args[1])
        self.assertEqual("passed", rebuilt.call_args.kwargs["validation_status"])
        self.assertEqual("out.pac", rebuilt.call_args.kwargs["output_path"])
        self.assertEqual("abc123", report.source_asset_hash)
        self.assertEqual("out.pac", report.output_path)
        self.assertIn("missing_tangents", report.warnings)
        self.assertEqual("replace_positions_same_count", report.edit_operations[0]["operation"])

    def test_rebuild_asset_writes_validated_output_file(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-asset", mode="edit")
        base_report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="abc123",
            rebuilt_asset_hash="def456",
            source_size=8,
            rebuilt_size=7,
            parse_confidence="exact",
            validation_status="passed",
            byte_identical=False,
            changed_byte_ranges=((0, 2),),
            output_path="",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "rebuilt.pac"
            with patch(
                "cdmw.services.mesh_service.rebuild_mesh_with_report",
                return_value=SimpleNamespace(data=b"rebuilt", report=base_report),
            ) as rebuilt:
                report = service.rebuild_asset(view.session_id, target, available_textures=("a.dds",))

            self.assertEqual(b"rebuilt", target.read_bytes())

        rebuilt.assert_called_once()
        self.assertEqual(str(target), rebuilt.call_args.kwargs["output_path"])
        self.assertEqual(str(target), report.output_path)

    def test_rebuild_asset_refuses_original_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "quad.pac"
            source.write_bytes(b"original")
            mesh = _quad_mesh()
            mesh.path = str(source)
            mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
            setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
            setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
            setattr(mesh, "_cdmw_original_data", b"original")
            setattr(
                mesh,
                "_cdmw_no_op_roundtrip_report",
                {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
            )
            service = MeshService()
            view = service.open_edit_session(mesh, session_id="rebuild-asset-original", mode="edit")

            with patch("cdmw.services.mesh_service.rebuild_mesh_with_report") as rebuilt:
                with self.assertRaisesRegex(RuntimeError, "must not overwrite"):
                    service.rebuild_asset(view.session_id, source, available_textures=("a.dds",))

        rebuilt.assert_not_called()

    def test_rebuild_report_blocks_failed_validation_before_rebuild(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "fallback_scan")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-report-blocked", mode="edit")

        with patch("cdmw.services.mesh_service.rebuild_mesh_with_report") as rebuilt:
            with self.assertRaisesRegex(RuntimeError, "mesh rebuild blocked"):
                service.rebuild_report(view.session_id, available_textures=("a.dds",))

        rebuilt.assert_not_called()

    def test_rebuild_asset_developer_override_reports_unsafe_conditions(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "fallback_scan")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-developer-override", mode="edit")
        base_report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="abc123",
            rebuilt_asset_hash="def456",
            source_size=8,
            rebuilt_size=7,
            parse_confidence="fallback_scan",
            validation_status="not_run",
            byte_identical=False,
            changed_byte_ranges=((0, 1),),
            output_path="",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "rebuilt.pac"
            with patch(
                "cdmw.services.mesh_service.rebuild_mesh_with_report",
                return_value=SimpleNamespace(data=b"rebuilt", report=base_report),
            ) as rebuilt:
                report = service.rebuild_asset(
                    view.session_id,
                    target,
                    available_textures=("a.dds",),
                    developer_override=True,
                    developer_override_reason="Forced rebuild for local testing",
                )

            self.assertEqual(b"rebuilt", target.read_bytes())

        rebuilt.assert_called_once()
        self.assertEqual("developer_override", rebuilt.call_args.kwargs["validation_status"])
        self.assertEqual("developer_override", report.validation_status)
        self.assertIn("developer_override_blocker:unsafe_parse_confidence", report.warnings)
        self.assertIn("override_reason=Forced rebuild for local testing", report.developer_overrides)
        self.assertIn("unsafe_conditions=unsafe_parse_confidence", report.developer_overrides)

    def test_rebuild_asset_developer_override_does_not_bypass_topology_blockers(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-developer-override-blocked", mode="edit")
        service._sessions[view.session_id].working_mesh.submeshes[0].vertices.append((2.0, 2.0, 0.0))

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "rebuilt.pac"
            with patch("cdmw.services.mesh_service.rebuild_mesh_with_report") as rebuilt:
                with self.assertRaisesRegex(RuntimeError, "mesh rebuild blocked"):
                    service.rebuild_asset(
                        view.session_id,
                        target,
                        available_textures=("a.dds",),
                        developer_override=True,
                        developer_override_reason="Forced rebuild for local testing",
                    )

        rebuilt.assert_not_called()


    def test_whole_part_delete_removes_submesh_rows_and_undo_restores_them(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="delete-part", mode="edit")

        deleted = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "delete",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={"delete_parts": True},
                mode="edit",
            ),
        )
        after_delete_names = [part.name for part in service.working_mesh(view.session_id).submeshes]
        selection_after_delete = service.session_view(view.session_id).selection.source_indices
        undo = service.undo(view.session_id)
        after_undo = service.working_mesh(view.session_id)

        self.assertTrue(deleted.ok)
        self.assertTrue(deleted.topology_changed)
        self.assertEqual((0,), deleted.affected_submesh_indices)
        self.assertEqual(["quad_b"], after_delete_names)
        self.assertEqual((), selection_after_delete)
        self.assertTrue(undo.ok)
        self.assertEqual(["quad", "quad_b"], [part.name for part in after_undo.submeshes])

    def test_export_validator_reports_format_geometry_material_and_skinning_blockers(self) -> None:
        mesh = _malformed_face_mesh()
        submesh = mesh.submeshes[0]
        submesh.faces.append((0, 1, 99))
        submesh.uvs = submesh.uvs[:2]
        submesh.normals = []
        submesh.texture = "missing.dds"
        # A PAC vertex record holds six influences, so seven is what overruns it.
        submesh.bone_indices = [(0, 1, 2, 3, 4, 5, 6)] * len(submesh.vertices)
        submesh.bone_weights = [(0.25, 0.15, 0.15, 0.15, 0.1, 0.1, 0.1)] * len(submesh.vertices)
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-invalid", mode="edit")

        report = service.validate_export(view.session_id, available_textures=())
        blocker_codes = {issue.code for issue in report.blockers}

        self.assertFalse(report.ok)
        self.assertIn("invalid_face", blocker_codes)
        self.assertIn("invalid_face_index", blocker_codes)
        self.assertIn("uv_count_mismatch", blocker_codes)
        self.assertIn("missing_normals", blocker_codes)
        self.assertIn("missing_referenced_texture", blocker_codes)
        self.assertIn("too_many_bone_influences", blocker_codes)
        self.assertIn("missing_skeleton_metadata", blocker_codes)
        missing_skeleton = next(issue for issue in report.blockers if issue.code == "missing_skeleton_metadata")
        self.assertIn("Inferred bone count from vertex weights: 7", missing_skeleton.message)
        self.assertIn("missing_tangents", {issue.code for issue in report.warnings})

    def test_export_validator_accepts_a_six_influence_vertex(self) -> None:
        """Six is the format's own limit, so it must not be reported as an overrun."""

        mesh = _malformed_face_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0, 1, 2, 3, 4, 5)] * len(submesh.vertices)
        submesh.bone_weights = [(0.25, 0.15, 0.15, 0.15, 0.15, 0.15)] * len(submesh.vertices)
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-six", mode="edit")

        report = service.validate_export(view.session_id, available_textures=())

        self.assertNotIn("too_many_bone_influences", {issue.code for issue in report.blockers})

    def test_export_validator_reports_import_sidecar_warnings_after_session_clone(self) -> None:
        mesh = _quad_mesh()
        setattr(
            mesh,
            "_cdmw_sidecar_warnings",
            (
                {
                    "code": "sidecar_material_name_changed",
                    "message": "OBJ sidecar material changed for submesh 0.",
                    "submesh_index": 0,
                    "blocks_rebuild": True,
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-sidecar-warning", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        warning = next(issue for issue in report.warnings if issue.code == "sidecar_material_name_changed")
        self.assertEqual("sidecar", warning.category)
        self.assertEqual(0, warning.submesh_index)
        blocker = next(issue for issue in report.blockers if issue.code == "sidecar_material_name_changed_blocks_rebuild")
        self.assertEqual("sidecar", blocker.category)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_material_and_texture_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-material-texture-changed", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False)
        edited.submeshes[0].material = "changed_material"
        edited.submeshes[0].texture = "changed.dds"

        report = service.validate_export(view.session_id, available_textures=("changed.dds",))

        blocker_codes = {issue.code for issue in report.blockers}
        self.assertIn("material_slot_changed", blocker_codes)
        self.assertIn("texture_reference_changed", blocker_codes)

    def test_export_validator_blocks_material_slot_count_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_material_slots", ("mat_a", "mat_b"))
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-material-slot-count-changed", mode="edit")
        setattr(service.working_mesh(view.session_id, clone=False), "_cdmw_mesh_asset_material_slots", ("mat_a",))

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "material_slot_count_changed")
        self.assertEqual("material", blocker.category)
        self.assertEqual(2, blocker.expected)
        self.assertEqual(1, blocker.actual)

    def test_export_validator_blocks_unknown_section_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_unknown_sections", (("section_9", 64, 32),))
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-unknown-section-changed", mode="edit")
        setattr(service.working_mesh(view.session_id, clone=False), "_cdmw_mesh_asset_unknown_sections", ())

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "unknown_sections_changed")
        self.assertEqual("metadata", blocker.category)
        self.assertEqual((("section_9", 64, 32),), blocker.expected)
        self.assertEqual((), blocker.actual)

    def test_export_validator_blocks_unknown_submesh_field_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh.submeshes[0], "unknown_fields", {"descriptor_flags": 7})
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-unknown-field-changed", mode="edit")
        setattr(service.working_mesh(view.session_id, clone=False).submeshes[0], "unknown_fields", {"descriptor_flags": 8})

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "unknown_fields_changed")
        self.assertEqual("metadata", blocker.category)
        self.assertEqual({"descriptor_flags": 7}, blocker.expected)
        self.assertEqual({"descriptor_flags": 8}, blocker.actual)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_vertex_stride_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_stride = 40
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-vertex-stride-changed", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].source_vertex_stride = 48

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "vertex_stride_changed")
        self.assertEqual("metadata", blocker.category)
        self.assertEqual(40, blocker.expected)
        self.assertEqual(48, blocker.actual)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_source_offset_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.source_vertex_offsets = [100, 140, 180, 220]
        submesh.source_index_offset = 500
        submesh.source_index_count = 6
        submesh.source_descriptor_offset = 64
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-source-offset-changed", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False).submeshes[0]
        edited.source_vertex_offsets = []
        edited.source_index_offset = -1
        edited.source_index_count = 3
        edited.source_descriptor_offset = -1

        report = service.validate_export(view.session_id, available_textures=("a.dds",))
        blockers = {issue.code: issue for issue in report.blockers}

        self.assertEqual((100, 140, 180, 220), blockers["source_vertex_offsets_changed"].expected)
        self.assertEqual("missing", blockers["source_vertex_offsets_changed"].actual)
        self.assertEqual(500, blockers["source_index_offset_changed"].expected)
        self.assertEqual("missing", blockers["source_index_offset_changed"].actual)
        self.assertEqual(6, blockers["source_index_count_changed"].expected)
        self.assertEqual(3, blockers["source_index_count_changed"].actual)
        self.assertEqual(64, blockers["source_descriptor_offset_changed"].expected)
        self.assertEqual("missing", blockers["source_descriptor_offset_changed"].actual)

    def test_export_validator_reports_topology_count_expected_actual_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-topology-counts-changed", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False).submeshes[0]
        edited.vertices.append((2.0, 2.0, 0.0))
        edited.uvs.append((1.0, 1.0))
        edited.normals.append((0.0, 0.0, 1.0))
        edited.faces.append((2, 3, 4))

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        vertex_count = next(issue for issue in report.blockers if issue.code == "submesh_vertex_count_changed")
        index_count = next(issue for issue in report.blockers if issue.code == "submesh_index_count_changed")
        self.assertEqual(4, vertex_count.expected)
        self.assertEqual(5, vertex_count.actual)
        self.assertEqual(0, vertex_count.lod_index)
        self.assertEqual(6, index_count.expected)
        self.assertEqual(9, index_count.actual)

    def test_export_validator_blocks_changed_geometry_without_source_vertex_map(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-changed-geometry-missing-source-map", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0] = (0.25, 0.0, 0.0)

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "source_vertex_map_missing")
        self.assertEqual("topology", blocker.category)
        self.assertEqual(4, blocker.expected)
        self.assertEqual(0, blocker.actual)
        self.assertEqual(0, blocker.lod_index)

    def test_export_validator_blocks_changed_geometry_with_invalid_source_vertex_map(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-changed-geometry-invalid-source-map", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False).submeshes[0]
        edited.vertices[0] = (0.25, 0.0, 0.0)
        edited.source_vertex_map[1] = -1

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "source_vertex_map_invalid")
        self.assertEqual("topology", blocker.category)
        self.assertEqual("non-negative source vertex ids", blocker.expected)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_lod_count_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-lod-count-changed", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        working.lod_levels = [working.submeshes, []]

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "lod_count_changed")
        self.assertEqual("topology", blocker.category)
        self.assertEqual(1, blocker.expected)
        self.assertEqual(2, blocker.actual)
        self.assertEqual(-1, blocker.lod_index)

    def test_export_validator_blocks_lod_submesh_count_changes_against_original_session_mesh(self) -> None:
        original = _quad_mesh(two_parts=True)
        original.lod_levels = [original.submeshes, [original.submeshes[0]]]
        edited = _quad_mesh(two_parts=True)
        edited.lod_levels = [edited.submeshes, []]

        report = validate_mesh_export(edited, original_mesh=original, available_textures=("a.dds", "b.dds"))

        blocker = next(issue for issue in report.blockers if issue.code == "lod_submesh_count_changed")
        self.assertEqual("topology", blocker.category)
        self.assertEqual(1, blocker.expected)
        self.assertEqual(0, blocker.actual)
        self.assertEqual(1, blocker.lod_index)

    def test_export_validator_reports_edit_operation_blockers_after_session_clone(self) -> None:
        mesh = _quad_mesh()
        setattr(
            mesh,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "topology_replacement",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-operation-blocker", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "blocked_edit_operation")
        self.assertEqual("operations", blocker.category)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_same_count_operation_without_source_map(self) -> None:
        mesh = _quad_mesh()
        setattr(
            mesh,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-operation-source-map-blocker", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "operation_source_map_missing")
        self.assertEqual("operations", blocker.category)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_untracked_channel_change_with_operation_list(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        setattr(
            mesh,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-operation-coverage-blocker", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].uvs[0] = (0.5, 0.5)

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "untracked_edit_channel")
        self.assertEqual("operations", blocker.category)
        self.assertEqual(0, blocker.submesh_index)
        self.assertIn("uv0", blocker.message)

    def test_export_validator_requires_operations_for_imported_obj_sidecar_session(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_imported_from_obj", True)
        setattr(mesh, "_cdmw_obj_sidecar_present", True)
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-imported-obj-missing-operations", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "missing_edit_operations")
        self.assertEqual("operations", blocker.category)

    def test_export_validator_allows_preserved_original_unnormalized_bone_weights(self) -> None:
        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0, 1)] * len(submesh.vertices)
        submesh.bone_weights = [(0.5, 0.25)] * len(submesh.vertices)
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-preserved-bone-weights", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",), skeleton_bone_count=2)

        self.assertTrue(report.ok)
        self.assertNotIn("unnormalized_bone_weights", {issue.code for issue in report.blockers})
        self.assertIn("preserved_unnormalized_bone_weights", {issue.code for issue in report.warnings})

    def test_export_validator_blocks_changed_preserved_skinning_data(self) -> None:
        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0,), (1,), (0, 1), (0,)]
        submesh.bone_weights = [(1.0,), (1.0,), (0.5, 0.5), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-changed-skinning-data", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].bone_weights[2] = (0.25, 0.75)

        report = service.validate_export(view.session_id, available_textures=("a.dds",), skeleton_bone_count=2)

        blocker = next(issue for issue in report.blockers if issue.code == "skinning_data_changed")
        self.assertEqual("skeleton", blocker.category)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_changed_unnormalized_bone_weights(self) -> None:
        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0, 1)] * len(submesh.vertices)
        submesh.bone_weights = [(0.5, 0.25)] * len(submesh.vertices)
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-changed-bone-weights", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].bone_weights[0] = (0.5, 0.1)

        report = service.validate_export(view.session_id, available_textures=("a.dds",), skeleton_bone_count=2)

        blockers = {issue.code for issue in report.blockers}
        self.assertFalse(report.ok)
        self.assertIn("unnormalized_bone_weights", blockers)

    def test_export_validator_blocks_pam_topology_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        mesh.format = "pam"
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-pam-topology", mode="edit")

        duplicate = service.apply_command(
            view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertTrue(duplicate.topology_changed)
        self.assertIn("unsupported_pam_topology_change", {issue.code for issue in report.blockers})
        self.assertIn("material_slot_count_mismatch", {issue.code for issue in report.warnings})


    def test_transform_uses_session_selection_and_undo_redo_keeps_original_mesh_clean(self) -> None:
        original = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(original, session_id="edit", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 3)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))
        result = service.apply_command(view.session_id, MeshEditCommand("transform", params={"translate": (0.0, 0.0, 1.0)}))

        self.assertTrue(result.ok)
        changed = dict(result.changed_vertices_by_submesh)[0]
        self.assertIsInstance(changed, dict)
        self.assertEqual(2, changed["changed_vertices_binary"]["count"])  # type: ignore[index]
        self.assertEqual((0.0, 0.0, 1.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual((0.0, 0.0, 0.0), original.submeshes[0].vertices[0])

        self.assertTrue(service.undo(view.session_id).ok)
        self.assertEqual((0.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertTrue(service.redo(view.session_id).ok)
        self.assertEqual((0.0, 0.0, 1.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_transform_records_undoable_position_edit_operation(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="edit-operation-history", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))
        result = service.apply_command(
            view.session_id,
            MeshEditCommand("transform", params={"translate": (0.0, 0.0, 1.0)}, label="Move"),
        )
        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertTrue(result.ok)
        operations = service._sessions[view.session_id].edit_operations
        operation_names = [operation["operation"] for operation in operations]  # type: ignore[index]
        self.assertIn("translate_vertices", operation_names)
        self.assertIn("replace_normals_same_count", operation_names)
        self.assertEqual(0, operations[0]["submesh_index"])  # type: ignore[index]
        self.assertNotIn("untracked_edit_channel", {issue.code for issue in report.blockers})
        history = service.session_view(view.session_id)
        self.assertEqual(("Select", "Move"), tuple(entry.label for entry in history.history_entries))
        self.assertEqual(2, history.history_cursor)

        self.assertTrue(service.undo(view.session_id).ok)
        self.assertEqual((), service._sessions[view.session_id].edit_operations)
        self.assertEqual(
            ("applied", "undone"),
            tuple(entry.state for entry in service.session_view(view.session_id).history_entries),
        )
        self.assertTrue(service.redo(view.session_id).ok)
        redone_operation_names = [operation["operation"] for operation in service._sessions[view.session_id].edit_operations]  # type: ignore[index]
        self.assertIn("translate_vertices", redone_operation_names)


    def test_select_prunes_indices_outside_current_mesh(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="select-prune", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (0, 99), 4: (0,)},
                    edges_by_submesh={0: ((0, 1), (0, 3), (1, 99)), 4: ((0, 1),)},
                    faces_by_submesh={0: (0, 9), 4: (0,)},
                    source_indices=(0, 4),
                ),
            ),
        )

        selection = service.session_view(view.session_id).selection
        self.assertEqual({0: {0}}, selection.vertex_map())
        self.assertEqual({0: {(0, 1)}}, selection.edge_map())
        self.assertEqual({0: {0}}, selection.face_map())
        self.assertEqual((0,), selection.source_indices)


    def test_undo_redo_restore_selection_context_snapshots(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="history-selection-context", mode="edit")
        original_selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=original_selection))
        duplicated = service.apply_command(view.session_id, MeshEditCommand("duplicate"))
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}, source_indices=(1,))),
        )
        undo = service.undo(view.session_id)
        after_undo = service.session_view(view.session_id)
        redo = service.redo(view.session_id)
        after_redo = service.session_view(view.session_id)

        self.assertTrue(duplicated.ok)
        self.assertTrue(duplicated.topology_changed)
        self.assertTrue(undo.ok)
        self.assertEqual({0: {0}}, after_undo.selection.face_map())
        self.assertEqual((), after_undo.selection.source_indices)
        self.assertTrue(redo.ok)
        self.assertEqual({1: {0}}, after_redo.selection.face_map())
        self.assertEqual((1,), after_redo.selection.source_indices)

    def test_undo_redo_restore_mode_before_command_mode_switch(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="history-mode-context", mode="object")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))
        duplicated = service.apply_command(view.session_id, MeshEditCommand("duplicate", mode="edit"))
        after_duplicate = service.session_view(view.session_id)
        undo = service.undo(view.session_id)
        after_undo = service.session_view(view.session_id)
        redo = service.redo(view.session_id)
        after_redo = service.session_view(view.session_id)

        self.assertTrue(duplicated.ok)
        self.assertEqual("edit", after_duplicate.mode)
        self.assertTrue(undo.ok)
        self.assertEqual("object", after_undo.mode)
        self.assertEqual({0: {0}}, after_undo.selection.face_map())
        self.assertTrue(redo.ok)
        self.assertEqual("edit", after_redo.mode)
        self.assertEqual({0: {0}}, after_redo.selection.face_map())


    def test_stale_edge_selection_does_not_partially_edit_valid_endpoint(self) -> None:
        stale_edge = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)})
        service = MeshService()
        transform_view = service.open_edit_session(_quad_mesh(), session_id="stale-edge-transform", mode="edit")

        moved = service.apply_command(
            transform_view.session_id,
            MeshEditCommand("transform", selection=stale_edge, params={"translate": (0.0, 0.0, 1.0)}),
        )

        transform_submesh = service.working_mesh(transform_view.session_id).submeshes[0]
        self.assertTrue(moved.ok)
        self.assertEqual((), moved.affected_submesh_indices)
        self.assertEqual((0.0, 0.0, 0.0), transform_submesh.vertices[0])
        self.assertEqual(0, service.session_view(transform_view.session_id).revision)

        uv_view = service.open_edit_session(_quad_mesh(), session_id="stale-edge-uv", mode="edit")
        uv = service.apply_command(
            uv_view.session_id,
            MeshEditCommand("uv_transform", selection=stale_edge, params={"offset": (0.25, 0.0)}),
        )

        uv_submesh = service.working_mesh(uv_view.session_id).submeshes[0]
        self.assertTrue(uv.ok)
        self.assertEqual((), uv.affected_submesh_indices)
        self.assertEqual((0.0, 0.0), uv_submesh.uvs[0])
        self.assertEqual(0, service.session_view(uv_view.session_id).revision)


    def test_brush_rejects_non_finite_numeric_params(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="brush-non-finite", mode="sculpt")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=selection,
                params={
                    "tool": "grab",
                    "center": (float("inf"), 0.0, 0.0),
                    "radius": float("inf"),
                    "strength": float("nan"),
                    "delta": (0.0, 0.0, float("inf")),
                    "amount": float("nan"),
                    "iterations": float("inf"),
                    "vertex_weights": {0: float("nan"), 1: float("inf")},
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), tuple(mesh.submeshes[0].vertices[:2]))


    def test_uv_transform_auto_uv_is_undoable_through_mesh_service(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        mesh = _quad_mesh()
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * len(mesh.submeshes[0].vertices)
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"auto-uv-undo-{uuid4().hex}", mode="edit")
        original_vertices = tuple(service.working_mesh(view.session_id).submeshes[0].vertices)
        original_uvs = tuple(service.working_mesh(view.session_id).submeshes[0].uvs)
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("auto_uv must use resident native editor session"),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "uv_transform",
                        selection=MeshEditSelection.from_maps(source_indices=(0,)),
                        params={"auto_uv": True, "allow_topology_change": True},
                        mode="edit",
                    ),
                )
                after_apply = service.working_mesh(view.session_id).submeshes[0]
                applied_vertices = tuple(after_apply.vertices)
                applied_uvs = tuple(after_apply.uvs)
                undo = service.undo(view.session_id)
                after_undo = service.working_mesh(view.session_id).submeshes[0]
                undo_vertices = tuple(after_undo.vertices)
                undo_uvs = tuple(after_undo.uvs)
                redo = service.redo(view.session_id)
                after_redo = service.working_mesh(view.session_id).submeshes[0]
                redo_vertices = tuple(after_redo.vertices)
                redo_uvs = tuple(after_redo.uvs)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertNotEqual(original_uvs, applied_uvs)
        self.assertTrue(undo.ok)
        self.assertEqual(original_vertices, undo_vertices)
        self.assertEqual(original_uvs, undo_uvs)
        self.assertTrue(redo.ok)
        self.assertEqual(applied_vertices, redo_vertices)
        self.assertEqual(applied_uvs, redo_uvs)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())


    def test_uv_transform_rejects_non_finite_vector_params(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-non-finite", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "uv_transform",
                selection=selection,
                params={
                    "offset": (float("inf"), 0.0),
                    "scale": (float("nan"), 1.0),
                    "pivot": (float("inf"), float("nan")),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)), tuple(mesh.submeshes[0].uvs))


    def test_transform_rejects_non_finite_vector_params(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="transform-non-finite", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={
                    "translate": (float("inf"), 0.0, 0.0),
                    "scale": (float("nan"), 1.0, 1.0),
                    "rotate": (0.0, 0.0, float("inf")),
                    "pivot": (float("nan"), 0.0, 0.0),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), tuple(mesh.submeshes[0].vertices[:2]))


    def test_all_named_v1_actions_return_results(self) -> None:
        actions = tuple(
            action
            for action in MESH_EDIT_ACTIONS
            if action not in {"triangulate_display", "quadrangulate_display"}
        )
        for action in actions:
            with self.subTest(action=action):
                service = MeshService()
                view = service.open_edit_session(_quad_mesh(two_parts=True), session_id=action, mode="edit")
                selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)}, source_indices=(0,))
                command = MeshEditCommand(action, selection=selection, mode="sculpt" if action == "set_mode" else None)
                if action == "material_copy":
                    command = MeshEditCommand(action, selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0})
                elif action in {"paste", "layer_delete"}:
                    service.apply_command(
                        view.session_id,
                        MeshEditCommand("copy", selection=selection, params={"target_mode": "vertex"}),
                    )
                    service.apply_command(view.session_id, MeshEditCommand("paste"))
                    if action == "layer_delete":
                        copied_layer = service.geometry_layer_state(view.session_id)["active_layer_id"]
                        command = MeshEditCommand("layer_delete", params={"layer_id": copied_layer})
                result = service.apply_command(view.session_id, command)
                self.assertIn(result.status, {"ok", "noop"})

if __name__ == "__main__":
    unittest.main()
