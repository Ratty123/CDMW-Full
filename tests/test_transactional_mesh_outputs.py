from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cdmw.core import atomic_file
from cdmw.core.atomic_file import atomic_binary_writer, atomic_publish_directory, atomic_publish_files
from cdmw.domain.mesh import MeshEditSelection
from cdmw.modding import mesh_native_core_temp_paths
from cdmw.modding import mesh_native_outputs
from cdmw.modding.mesh_glb_interchange import export_glb
from cdmw.modding.mesh_native_core import (
    dispose_native_mesh_history_delta,
    export_native_fbx,
    export_native_obj,
    native_mesh_core_available,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.ui.native_d3d11_preview_host import _remove_paths
from cdmw.services import mesh_service as mesh_service_module
from cdmw.workers.mesh_editor_workers import MeshEditablePackageExportWorker


def _mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="body",
        material="body",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        faces=[(0, 1, 2)],
    )
    return ParsedMesh(path="body.pac", format="pac", submeshes=[submesh], total_vertices=3, total_faces=1)


class TransactionalMeshOutputTests(unittest.TestCase):
    def test_interrupted_atomic_writer_preserves_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "mesh.glb"
            target.write_bytes(b"previous")

            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                with atomic_binary_writer(target) as handle:
                    handle.write(b"partial")
                    raise RuntimeError("interrupted")

            self.assertEqual(b"previous", target.read_bytes())
            self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))

    def test_multi_file_publish_rolls_back_every_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            staged_one = root / "staged-one"
            staged_two = root / "staged-two"
            target_one = root / "mesh.glb"
            target_two = root / "mesh.glb.meta.json"
            staged_one.write_bytes(b"new mesh")
            staged_two.write_bytes(b"new sidecar")
            target_one.write_bytes(b"old mesh")
            target_two.write_bytes(b"old sidecar")
            real_replace = atomic_file.os.replace

            def fail_second_publish(source: object, destination: object) -> None:
                if Path(source) == staged_two and Path(destination) == target_two:
                    raise OSError("injected publication failure")
                real_replace(source, destination)

            with mock.patch.object(atomic_file.os, "replace", side_effect=fail_second_publish):
                with self.assertRaisesRegex(OSError, "injected"):
                    atomic_publish_files({staged_one: target_one, staged_two: target_two})

            self.assertEqual(b"old mesh", target_one.read_bytes())
            self.assertEqual(b"old sidecar", target_two.read_bytes())
            self.assertEqual([], list(root.glob(".*.bak")))

    def test_directory_publish_failure_restores_previous_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            staged = root / "staged"
            target = root / "package"
            staged.mkdir()
            target.mkdir()
            (staged / "manifest.json").write_text("new", encoding="utf-8")
            (target / "manifest.json").write_text("old", encoding="utf-8")
            real_replace = atomic_file.os.replace

            def fail_publish(source: object, destination: object) -> None:
                if Path(source) == staged and Path(destination) == target:
                    raise OSError("injected directory publication failure")
                real_replace(source, destination)

            with mock.patch.object(atomic_file.os, "replace", side_effect=fail_publish):
                with self.assertRaisesRegex(OSError, "injected directory"):
                    atomic_publish_directory(staged, target)

            self.assertEqual("old", (target / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("new", (staged / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([], list(root.glob(".*.bak")))

    def test_glb_replace_failure_keeps_previous_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "mesh.glb"
            target.write_bytes(b"previous glb")
            real_replace = atomic_file.os.replace

            def fail_target_replace(source: object, destination: object) -> None:
                if Path(destination) == target:
                    raise OSError("replace denied")
                real_replace(source, destination)

            with mock.patch.object(atomic_file.os, "replace", side_effect=fail_target_replace):
                with self.assertRaisesRegex(OSError, "replace denied"):
                    export_glb(_mesh(), root)

            self.assertEqual(b"previous glb", target.read_bytes())
            self.assertEqual([], list(root.glob(f".{target.name}.*.tmp")))

    def test_failed_native_export_discards_staged_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "mesh.fbx"
            target.write_bytes(b"previous fbx")

            def fail_job(_binary: Path, _command: str, payload: object, **_kwargs: object) -> None:
                Path(str(payload["output_path"])).write_bytes(b"partial native fbx")  # type: ignore[index]
                return None

            with (
                mock.patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                mock.patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=fail_job),
            ):
                self.assertFalse(export_native_fbx(ParsedMesh(), target, base_name="mesh"))

            self.assertEqual(b"previous fbx", target.read_bytes())
            self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))

    def test_native_obj_export_publishes_final_manifest_identity(self) -> None:
        if not native_mesh_core_available():
            self.skipTest("native mesh core is unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            obj_path = root / "mesh.obj"
            manifest_path = root / "mesh.obj.meta.json"

            self.assertTrue(
                export_native_obj(
                    _mesh(),
                    obj_path,
                    base_name="mesh",
                    mtl_filename="mesh.mtl",
                    manifest_path=manifest_path,
                )
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(obj_path.name, manifest["export_path"])
            self.assertEqual([], list(root.glob(".*.tmp")))

    def test_native_obj_export_keeps_staging_names_compact_for_long_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            while len(str(root / "mesh.obj.meta.json")) < 220:
                root /= "long-package-segment"
            root.mkdir(parents=True)
            obj_path = root / "mesh.obj"
            manifest_path = root / "mesh.obj.meta.json"
            staged_paths: list[Path] = []

            def complete_job(_binary: Path, _command: str, payload: object, **_kwargs: object) -> dict[str, object]:
                job = dict(payload)  # type: ignore[arg-type]
                staged_obj = Path(str(job["output_path"]))
                staged_manifest = Path(str(job["manifest_output_path"]))
                staged_paths.extend((staged_obj, staged_manifest))
                staged_obj.write_text("obj", encoding="utf-8")
                staged_manifest.write_text("{}", encoding="utf-8")
                return {"status": "ok", "operation": "obj_export", "submesh_count": 1}

            with (
                mock.patch.object(mesh_native_outputs, "find_native_mesh_core_binary", return_value=Path("native.exe")),
                mock.patch.object(
                    mesh_native_outputs,
                    "_native_obj_submesh_payloads",
                    return_value=((_mesh().submeshes[0],), [{"index": 0, "session_id": "session"}]),
                ),
                mock.patch.object(mesh_native_outputs, "_run_native_mesh_core_job", side_effect=complete_job),
            ):
                self.assertTrue(
                    mesh_native_outputs.export_native_obj(
                        _mesh(),
                        obj_path,
                        base_name="mesh",
                        mtl_filename="mesh.mtl",
                        manifest_path=manifest_path,
                    )
                )

            self.assertEqual("obj", obj_path.read_text(encoding="utf-8"))
            self.assertEqual("{}", manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(2, len(staged_paths))
            for staged_path in staged_paths:
                self.assertEqual(root, staged_path.parent)
                self.assertNotIn(obj_path.name, staged_path.name)
                self.assertLess(len(str(staged_path)), len(str(manifest_path)) + 50)
            self.assertEqual([], list(root.glob(".*.tmp")))

    def test_history_delta_ack_removes_only_tracked_payload(self) -> None:
        tracked = Path(mesh_native_core_temp_paths.native_preview_delta_output_path("_history.bin"))
        tracked.write_bytes(b"delta")
        with tempfile.TemporaryDirectory() as temp_dir:
            external = Path(temp_dir) / "external.bin"
            external.write_bytes(b"external")

            self.assertTrue(dispose_native_mesh_history_delta({"path": str(tracked)}))
            self.assertFalse(tracked.exists())
            self.assertFalse(dispose_native_mesh_history_delta({"path": str(external)}))
            self.assertEqual(b"external", external.read_bytes())

    def test_history_snapshot_disposal_acknowledges_retained_binary(self) -> None:
        tracked = Path(mesh_native_core_temp_paths.native_preview_delta_output_path("_retained-history.bin"))
        tracked.write_bytes(b"history")
        delta = mesh_service_module._MeshVertexPositionDelta(
            submesh_index=0,
            vertex_indices=(0,),
            positions=(),
            before_positions_binary={"path": str(tracked), "count": 1, "components": 3, "type": "f64"},
        )
        snapshot = mesh_service_module._MeshHistorySnapshot(
            mesh=None,
            mode="edit",
            selection=MeshEditSelection(),
            vertex_position_deltas=(delta,),
        )

        mesh_service_module._dispose_history_snapshot(snapshot)

        self.assertFalse(tracked.exists())

    def test_native_preview_consumer_ack_unregisters_owned_payload(self) -> None:
        tracked = Path(mesh_native_core_temp_paths.native_preview_delta_output_path("_preview.bin"))
        tracked.write_bytes(b"preview")

        _remove_paths((tracked,))

        self.assertFalse(tracked.exists())
        self.assertFalse(mesh_native_core_temp_paths.release_native_preview_delta_path(tracked))

    def test_cancelled_editable_package_export_never_publishes_staging(self) -> None:
        service = mesh_service_module.MeshService()
        view = service.open_edit_session(_mesh(), session_id="cancelled-editable-export")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "package"
            output_dir.mkdir()
            sentinel = output_dir / "keep.txt"
            sentinel.write_text("existing", encoding="utf-8")
            worker = MeshEditablePackageExportWorker(1, service, view.session_id, output_dir)

            def fake_glb(_mesh_value: object, root: str, name: str, **_kwargs: object) -> list[str]:
                directory = Path(root)
                glb = directory / f"{name}.glb"
                sidecar = Path(f"{glb}.meta.json")
                glb.write_bytes(b"glb")
                sidecar.write_text(json.dumps({"source_asset_hash": "hash"}), encoding="utf-8")
                return [str(glb), str(sidecar)]

            def fake_obj(_mesh_value: object, root: str, name: str, **_kwargs: object) -> list[str]:
                directory = Path(root)
                obj = directory / f"{name}.obj"
                mtl = directory / f"{name}.mtl"
                sidecar = Path(f"{obj}.meta.json")
                obj.write_text("obj", encoding="utf-8")
                mtl.write_text("mtl", encoding="utf-8")
                sidecar.write_text("{}", encoding="utf-8")
                worker.stop()
                return [str(obj), str(mtl), str(sidecar)]

            with (
                mock.patch("cdmw.workers.mesh_editor_workers.export_glb", side_effect=fake_glb),
                mock.patch("cdmw.workers.mesh_editor_workers.export_obj", side_effect=fake_obj),
            ):
                worker.run()

            self.assertEqual("existing", sentinel.read_text(encoding="utf-8"))
            self.assertEqual([sentinel], list(output_dir.iterdir()))
            self.assertEqual([], list(output_dir.parent.glob(f".{output_dir.name}.export-*")))


if __name__ == "__main__":
    unittest.main()
