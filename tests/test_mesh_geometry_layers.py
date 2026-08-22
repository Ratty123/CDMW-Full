from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service import MeshService


def _layer_mesh(*, two_parts: bool = False) -> ParsedMesh:
    def submesh(name: str, material: str, offset: float) -> SubMesh:
        return SubMesh(
            name=name,
            material=material,
            texture=f"{material}.dds",
            vertices=[
                (offset + 0.0, 0.0, 0.0),
                (offset + 1.0, 0.0, 0.0),
                (offset + 0.0, 1.0, 0.0),
                (offset + 1.0, 1.0, 0.0),
            ],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
            normals=[(0.0, 0.0, 1.0)] * 4,
            faces=[(0, 1, 2), (1, 3, 2)],
            vertex_count=4,
            face_count=2,
        )

    submeshes = [submesh("base-a", "mat-a", 0.0)]
    if two_parts:
        submeshes.append(submesh("base-b", "mat-b", 3.0))
    return ParsedMesh(
        path="layer-test.pac",
        format="pac",
        submeshes=submeshes,
        total_vertices=4 * len(submeshes),
        total_faces=2 * len(submeshes),
        has_uvs=True,
    )


def _persistent_layer_mesh(root: Path, *, source_hash: str = "a" * 64) -> tuple[ParsedMesh, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    obj_path = root / "editable.obj"
    obj_path.write_text("# synthetic Mesh Editor layer test\n", encoding="utf-8")
    project_path = root / "mesh_layers" / "mesh_layer_project.json"
    manifest_path = root / "modify_original_workspace.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "cdmw_modify_original_workspace_v1",
                "workspace_mode": "internal_app_session",
                "source_asset_sha256": source_hash,
                "editable_obj": str(obj_path),
                "mesh_layer_project": "",
                "created_at": 1.0,
            }
        ),
        encoding="utf-8",
    )
    mesh = _layer_mesh()
    mesh.path = str(obj_path)
    setattr(mesh, "_cdmw_mesh_asset_source_hash", source_hash)
    setattr(mesh, "_cdmw_mesh_layer_project_path", str(project_path))
    setattr(mesh, "_cdmw_modify_original_workspace_manifest_path", str(manifest_path))
    setattr(mesh, "_cdmw_modify_original_workspace_mode", "internal_app_session")
    return mesh, project_path, manifest_path


def _apply_fake_affine(submeshes, *, position_matrices_by_index, **_kwargs):
    for index, matrix in position_matrices_by_index.items():
        submesh = submeshes[index]
        submesh.vertices = [
            (
                matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
                matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
                matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
            )
            for x, y, z in submesh.vertices
        ]
    return set(position_matrices_by_index)


class MeshGeometryLayerServiceTests(unittest.TestCase):
    def test_copy_paste_is_one_layer_history_action_with_selection(self) -> None:
        service = MeshService()
        session_id = f"layer-copy-{uuid4().hex}"
        service.open_edit_session(_layer_mesh(), session_id=session_id, mode="edit")
        service.apply_command(
            session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"operation": "replace"},
            ),
        )

        copied = service.apply_command(
            session_id,
            MeshEditCommand("copy", params={"target_mode": "face"}, mode="edit"),
        )
        self.assertTrue(copied.ok)
        self.assertTrue(service.geometry_layer_state(session_id)["clipboard_ready"])

        pasted = service.apply_command(session_id, MeshEditCommand("paste", mode="edit"))
        self.assertTrue(pasted.ok)
        self.assertEqual(1, pasted.submesh_count_delta)
        layers = service.geometry_layer_state(session_id)
        self.assertEqual(["Base mesh", "Selection copy 1"], [item["name"] for item in layers["layers"]])
        self.assertEqual("selection-copy-1", layers["active_layer_id"])
        self.assertEqual({1: {0}}, service.session_view(session_id).selection.face_map())

        undone = service.undo(session_id)
        self.assertTrue(undone.ok)
        self.assertEqual(1, service.session_view(session_id).submesh_count)
        self.assertEqual(["Base mesh"], [item["name"] for item in service.geometry_layer_state(session_id)["layers"]])
        self.assertEqual({0: {0}}, service.session_view(session_id).selection.face_map())

        redone = service.redo(session_id)
        self.assertTrue(redone.ok)
        self.assertEqual(2, service.session_view(session_id).submesh_count)
        self.assertEqual("selection-copy-1", service.geometry_layer_state(session_id)["active_layer_id"])
        self.assertEqual({1: {0}}, service.session_view(session_id).selection.face_map())

    def test_vertex_copy_requires_complete_faces(self) -> None:
        service = MeshService()
        session_id = f"layer-incomplete-{uuid4().hex}"
        service.open_edit_session(_layer_mesh(), session_id=session_id, mode="edit")
        service.apply_command(
            session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}),
                params={"operation": "replace"},
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "No complete faces selected to copy"):
            service.apply_command(
                session_id,
                MeshEditCommand("copy", params={"target_mode": "vertex"}, mode="edit"),
            )

    def test_multi_material_selection_stays_fragmented_under_one_layer(self) -> None:
        service = MeshService()
        session_id = f"layer-multi-{uuid4().hex}"
        service.open_edit_session(_layer_mesh(two_parts=True), session_id=session_id, mode="edit")
        service.apply_command(
            session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,), 1: (1,)}),
                params={"operation": "replace"},
            ),
        )
        service.apply_command(
            session_id,
            MeshEditCommand("copy", params={"target_mode": "face"}, mode="edit"),
        )
        pasted = service.apply_command(session_id, MeshEditCommand("paste", mode="edit"))
        self.assertEqual(2, pasted.submesh_count_delta)
        state = service.geometry_layer_state(session_id)
        self.assertEqual((2, 3), tuple(state["layers"][1]["submesh_indices"]))
        mesh = service.working_mesh(session_id)
        self.assertEqual(["mat-a", "mat-b"], [mesh.submeshes[index].material for index in (2, 3)])

    def test_layer_project_round_trip_restores_geometry_but_not_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cdmw-layer-project-") as temp_dir:
            root = Path(temp_dir)
            mesh, project_path, manifest_path = _persistent_layer_mesh(root)
            service = MeshService()
            session_id = f"layer-save-{uuid4().hex}"
            service.open_edit_session(mesh, session_id=session_id, mode="edit")
            with patch(
                "cdmw.services.mesh_service_object_transform.apply_native_mesh_affine_transform_submeshes",
                side_effect=_apply_fake_affine,
            ):
                service.set_object_transform(
                    session_id,
                    location=(5.0, 0.0, 0.0),
                    rotation_degrees=(0.0, 20.0, 0.0),
                    scale=(1.25, 1.25, 1.25),
                )
            saved_object_transform = service.session_view(session_id).object_transform
            service.apply_command(
                session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                    params={"operation": "replace"},
                ),
            )
            service.copy_selection(session_id, target="face")
            service.paste_selection(session_id)
            service.rename_geometry_layer(session_id, "selection-copy-1", "Experiment A")
            service.retry_mesh_layer_autosave(session_id)

            descriptor = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual("mesh_layer_project_v1", descriptor["format"])
            self.assertTrue((project_path.parent / descriptor["current_generation"] / "generation.json").is_file())
            promoted = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("persistent_app_draft", promoted["workspace_mode"])
            service.close_edit_session(session_id)

            resumed_mesh, _project_path, _manifest_path = _persistent_layer_mesh(root)
            resumed = MeshService()
            view = resumed.open_edit_session(
                resumed_mesh,
                session_id=f"layer-resume-{uuid4().hex}",
                mode="edit",
            )
            state = resumed.geometry_layer_state(view.session_id)
            self.assertEqual(["Base mesh", "Experiment A"], [item["name"] for item in state["layers"]])
            self.assertEqual(2, view.submesh_count)
            self.assertTrue(view.selection.is_empty())
            self.assertEqual(0, view.undo_count)
            self.assertEqual(0, view.redo_count)
            self.assertEqual(saved_object_transform, view.object_transform)

    def test_corrupt_current_generation_recovers_previous_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cdmw-layer-recovery-") as temp_dir:
            root = Path(temp_dir)
            mesh, project_path, _manifest_path = _persistent_layer_mesh(root)
            service = MeshService()
            session_id = f"layer-recovery-save-{uuid4().hex}"
            service.open_edit_session(mesh, session_id=session_id, mode="edit")
            service.apply_command(
                session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                    params={"operation": "replace"},
                ),
            )
            service.copy_selection(session_id, target="face")
            service.paste_selection(session_id)
            service.retry_mesh_layer_autosave(session_id)
            service.rename_geometry_layer(session_id, "selection-copy-1", "Newest name")
            service.retry_mesh_layer_autosave(session_id)
            descriptor = json.loads(project_path.read_text(encoding="utf-8"))
            current_manifest = project_path.parent / descriptor["current_generation"] / "generation.json"
            current_manifest.write_text("corrupt", encoding="utf-8")
            service.close_edit_session(session_id, force_without_saving=True)

            resumed_mesh, _project_path, _manifest_path = _persistent_layer_mesh(root)
            resumed = MeshService()
            view = resumed.open_edit_session(
                resumed_mesh,
                session_id=f"layer-recovery-open-{uuid4().hex}",
                mode="edit",
            )
            state = resumed.geometry_layer_state(view.session_id)
            self.assertEqual(descriptor["previous_generation"], state["loaded_generation"])
            self.assertEqual("Selection copy 1", state["layers"][1]["name"])

    def test_incompatible_project_fingerprint_is_rejected_without_deleting_draft(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cdmw-layer-fingerprint-") as temp_dir:
            root = Path(temp_dir)
            mesh, project_path, _manifest_path = _persistent_layer_mesh(root)
            service = MeshService()
            session_id = f"layer-fingerprint-save-{uuid4().hex}"
            service.open_edit_session(mesh, session_id=session_id, mode="edit")
            service.apply_command(
                session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                    params={"operation": "replace"},
                ),
            )
            service.retry_mesh_layer_autosave(session_id)
            before = project_path.read_bytes()
            service.close_edit_session(session_id)

            incompatible, _project_path, _manifest_path = _persistent_layer_mesh(
                root,
                source_hash="b" * 64,
            )
            with self.assertRaisesRegex(ValueError, "fingerprint does not match"):
                MeshService().open_edit_session(
                    incompatible,
                    session_id=f"layer-fingerprint-open-{uuid4().hex}",
                    mode="edit",
                )
            self.assertEqual(before, project_path.read_bytes())

    def test_hidden_copied_layer_is_excluded_from_export_but_remains_saved(self) -> None:
        service = MeshService()
        session_id = f"layer-visible-{uuid4().hex}"
        service.open_edit_session(_layer_mesh(), session_id=session_id, mode="edit")
        service.apply_command(
            session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"operation": "replace"},
            ),
        )
        service.copy_selection(session_id, target="face")
        service.paste_selection(session_id)
        state = service.set_geometry_layer_visibility(session_id, "selection-copy-1", False)
        self.assertEqual("base", state["active_layer_id"])
        self.assertTrue(service.session_view(session_id).selection.is_empty())
        self.assertEqual(2, service.session_view(session_id).submesh_count)
        exported = service.capture_export_snapshot(session_id)
        self.assertEqual(1, len(exported.mesh.submeshes))

    def test_geometry_undo_keeps_layer_name_visibility_order_and_activation(self) -> None:
        service = MeshService()
        session_id = f"layer-metadata-history-{uuid4().hex}"
        service.open_edit_session(_layer_mesh(), session_id=session_id, mode="edit")
        service.apply_command(
            session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"operation": "replace"},
            ),
        )
        service.copy_selection(session_id, target="face")
        service.paste_selection(session_id)
        service.paste_selection(session_id)
        service.activate_geometry_layer(session_id, "selection-copy-1")

        duplicated = service.apply_command(
            session_id,
            MeshEditCommand(
                "duplicate",
                selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}),
                mode="edit",
            ),
        )
        self.assertTrue(duplicated.ok)
        self.assertEqual((1, 3), tuple(service.geometry_layer_state(session_id)["layers"][1]["submesh_indices"]))

        service.rename_geometry_layer(session_id, "selection-copy-1", "Working variant")
        service.set_geometry_layer_visibility(session_id, "selection-copy-2", False)
        service.move_geometry_layer(session_id, "selection-copy-1", 1)
        expected_metadata = [
            (item["layer_id"], item["name"], item["visible"])
            for item in service.geometry_layer_state(session_id)["layers"]
        ]

        service.undo(session_id)
        undone = service.geometry_layer_state(session_id)
        self.assertEqual(expected_metadata, [
            (item["layer_id"], item["name"], item["visible"])
            for item in undone["layers"]
        ])
        self.assertEqual("selection-copy-1", undone["active_layer_id"])
        self.assertEqual((1,), tuple(next(
            item["submesh_indices"]
            for item in undone["layers"]
            if item["layer_id"] == "selection-copy-1"
        )))

        service.redo(session_id)
        redone = service.geometry_layer_state(session_id)
        self.assertEqual(expected_metadata, [
            (item["layer_id"], item["name"], item["visible"])
            for item in redone["layers"]
        ])
        self.assertEqual("selection-copy-1", redone["active_layer_id"])
        self.assertEqual((1, 3), tuple(next(
            item["submesh_indices"]
            for item in redone["layers"]
            if item["layer_id"] == "selection-copy-1"
        )))


if __name__ == "__main__":
    unittest.main()
