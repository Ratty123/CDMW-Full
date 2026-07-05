from __future__ import annotations

from array import array
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cdmw.modding import mesh_exporter
from cdmw.modding.mesh_exporter import export_fbx, export_fbx_with_skeleton
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.skeleton_parser import Bone, Skeleton


def _write_array(path: Path, typecode: str, values: list[float] | list[int]) -> dict:
    data = array(typecode, values)
    with path.open("wb") as handle:
        data.tofile(handle)
    return {"path": str(path), "count": len(values), "components": 1, "type": "f64" if typecode == "d" else "i32"}


class _FakeNativeFbxGeometry:
    def __init__(self, temp_dir: str):
        self.closed = False
        self._temp_dir = tempfile.TemporaryDirectory(dir=temp_dir)
        root = Path(self._temp_dir.name)
        self._items = {
            0: {
                "vertices": mesh_exporter._FbxBinaryArray(
                    _write_array(root / "vertices.bin", "d", [0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0, 0.0]),
                    "d",
                ),
                "indices": mesh_exporter._FbxBinaryArray(_write_array(root / "indices.bin", "i", [0, 1, -3]), "i"),
                "normals": mesh_exporter._FbxBinaryArray(
                    _write_array(root / "normals.bin", "d", [0.0, 0.0, 1.0] * 3),
                    "d",
                ),
                "uvs": mesh_exporter._FbxBinaryArray(
                    _write_array(root / "uvs.bin", "d", [0.0, 1.0, 1.0, 1.0, 0.0, 0.0]),
                    "d",
                ),
            }
        }

    def item(self, index: int):
        return self._items.get(index)

    def close(self) -> None:
        self.closed = True
        self._temp_dir.cleanup()


def _export_mesh() -> ParsedMesh:
    vertex_count = 3
    submesh = SubMesh(
        name="part",
        material="part",
        vertices=[(float(index), 0.0, 0.0) for index in range(vertex_count)],
        uvs=[(0.0, 0.0)] * vertex_count,
        normals=[(0.0, 0.0, 1.0)] * vertex_count,
        faces=[(0, 1, 2)],
        vertex_count=vertex_count,
        face_count=1,
    )
    return ParsedMesh(path="character/part.pac", format="pac", submeshes=[submesh], total_vertices=vertex_count, total_faces=1, has_uvs=True)


class FbxExporterTests(unittest.TestCase):
    def test_plain_fbx_export_uses_native_writer_before_python_node_writer(self) -> None:
        mesh = ParsedMesh(
            path="character/native.pac",
            format="pac",
            submeshes=[SubMesh(name="Body", material="BodyMat", vertices=[(0.0, 0.0, 0.0)], faces=[])],
            total_vertices=1,
            total_faces=0,
        )

        def fake_native(_mesh, fbx_path, _base, _scale):
            Path(fbx_path).write_bytes(b"native fbx")
            return True

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                mock.patch("cdmw.modding.mesh_exporter._export_fbx_native", side_effect=fake_native) as native,
                mock.patch("cdmw.modding.mesh_exporter._fbx_geometry_native") as geometry,
            ):
                fbx_path = Path(export_fbx(mesh, temp_dir, name="native"))

            self.assertEqual(b"native fbx", fbx_path.read_bytes())
            native.assert_called_once()
            geometry.assert_not_called()

    def test_plain_fbx_export_uses_native_geometry_arrays(self) -> None:
        mesh = ParsedMesh(
            path="character/native.pac",
            format="pac",
            submeshes=[
                SubMesh(
                    name="Body",
                    material="BodyMat",
                    vertices=[(9.0, 9.0, 9.0), (10.0, 9.0, 9.0), (9.0, 10.0, 9.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    faces=[(0, 1, 2)],
                )
            ],
            total_vertices=3,
            total_faces=1,
            has_uvs=True,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_native = _FakeNativeFbxGeometry(temp_dir)
            with (
                mock.patch("cdmw.modding.mesh_exporter._export_fbx_native", return_value=False),
                mock.patch("cdmw.modding.mesh_exporter._fbx_geometry_native", return_value=fake_native) as native,
            ):
                fbx_path = Path(export_fbx(mesh, temp_dir, name="native"))
                payload = fbx_path.read_bytes()

        self.assertTrue(fake_native.closed)
        native.assert_called_once()
        self.assertIn(b"Kaydara FBX Binary", payload)
        self.assertIn(b"LayerElementUV", payload)

    def test_fbx_export_blocks_python_geometry_fallback_when_native_available(self) -> None:
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        clear_native_mesh_core_fallback_counts()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with (
                    mock.patch("cdmw.modding.mesh_exporter._export_fbx_native", return_value=False),
                    mock.patch("cdmw.modding.mesh_exporter._fbx_geometry_native", return_value=None),
                    mock.patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True),
                ):
                    with self.assertRaisesRegex(RuntimeError, "Python export fallback was blocked"):
                        export_fbx(_export_mesh(), temp_dir, name="native_failed")
            self.assertEqual(1, native_mesh_core_fallback_counts()["export.fbx.blocked"])
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_skeleton_fbx_export_uses_native_writer_before_python_node_writer(self) -> None:
        mesh = ParsedMesh(
            path="character/native.pac",
            format="pac",
            submeshes=[SubMesh(name="Body", material="BodyMat", vertices=[(0.0, 0.0, 0.0)], faces=[])],
            total_vertices=1,
            total_faces=0,
        )
        skeleton = Skeleton(path="character/native.pab", bones=[Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0))])

        def fake_native(_mesh, fbx_path, _base, _scale, *, skeleton=None):
            self.assertIsNotNone(skeleton)
            Path(fbx_path).write_bytes(b"native skeleton fbx")
            return True

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                mock.patch("cdmw.modding.mesh_exporter._export_fbx_native", side_effect=fake_native) as native,
                mock.patch("cdmw.modding.mesh_exporter._fbx_geometry_native") as geometry,
            ):
                fbx_path = Path(export_fbx_with_skeleton(mesh, skeleton, temp_dir, name="native_skeleton"))

            self.assertEqual(b"native skeleton fbx", fbx_path.read_bytes())
            native.assert_called_once()
            geometry.assert_not_called()

    def test_skeleton_fbx_export_blocks_python_geometry_fallback_when_native_available(self) -> None:
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        skeleton = Skeleton(path="character/large.pab", bones=[Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0))])
        clear_native_mesh_core_fallback_counts()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with (
                    mock.patch("cdmw.modding.mesh_exporter._export_fbx_native", return_value=False),
                    mock.patch("cdmw.modding.mesh_exporter._fbx_geometry_native", return_value=None),
                    mock.patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True),
                ):
                    with self.assertRaisesRegex(RuntimeError, "Python export fallback was blocked"):
                        export_fbx_with_skeleton(_export_mesh(), skeleton, temp_dir, name="native_failed")
            self.assertEqual(1, native_mesh_core_fallback_counts()["export.fbx_skeleton.blocked"])
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_skeleton_fbx_export_keeps_uv_layer_and_bone_sizes(self) -> None:
        mesh = ParsedMesh(
            path="character/test.pac",
            format="pac",
            submeshes=[
                SubMesh(
                    name="Body",
                    material="BodyMat",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    faces=[(0, 1, 2)],
                )
            ],
            total_vertices=3,
            total_faces=1,
            has_uvs=True,
        )
        skeleton = Skeleton(
            path="character/test.pab",
            bones=[
                Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0)),
                Bone(index=1, name="Child", parent_index=0, position=(0.0, 2.0, 0.0)),
            ],
            bone_count=2,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            fbx_path = Path(export_fbx_with_skeleton(mesh, skeleton, temp_dir, name="skinned"))
            payload = fbx_path.read_bytes()

        self.assertIn(b"LayerElementUV", payload)
        self.assertIn(b"UVMap", payload)
        self.assertIn(b"Size", payload)


if __name__ == "__main__":
    unittest.main()
