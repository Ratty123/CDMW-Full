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

        def fake_native(_mesh, fbx_path, _base, _scale, *, skeleton=None, bone_palette=None):
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


def _skinned_export_mesh() -> ParsedMesh:
    """Three vertices, each riding a different influence slot."""

    submesh = SubMesh(
        name="Body",
        material="BodyMat",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        bone_indices=[(0,), (1,), (0, 1)],
        bone_weights=[(1.0,), (1.0,), (0.5, 0.5)],
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(
        path="character/skinned.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
        has_bones=True,
    )


def _two_bone_skeleton() -> Skeleton:
    return Skeleton(
        path="character/skinned.pab",
        bones=[
            Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0),
                 bind_matrix=(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)),
            Bone(index=1, name="Child", parent_index=0, position=(0.0, 2.0, 0.0),
                 bind_matrix=(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 2, 0, 1)),
        ],
        bone_count=2,
    )


class FbxSkinRowTests(unittest.TestCase):
    """The slot-to-bone mapping that stands between a PAC and a usable rig."""

    def test_palette_maps_slots_onto_skeleton_bones(self) -> None:
        from cdmw.modding.mesh_native_core import _fbx_skin_rows

        submesh = _skinned_export_mesh().submeshes[0]
        indices, weights = _fbx_skin_rows(submesh, (17, 42))

        self.assertEqual(indices, [(17,), (42,), (17, 42)])
        self.assertEqual(weights, [(1.0,), (1.0,), (0.5, 0.5)])

    def test_missing_palette_takes_slots_as_bone_indices(self) -> None:
        from cdmw.modding.mesh_native_core import _fbx_skin_rows

        submesh = _skinned_export_mesh().submeshes[0]
        indices, _weights = _fbx_skin_rows(submesh, None)

        self.assertEqual(indices, [(0,), (1,), (0, 1)])

    def test_unresolved_palette_refuses_to_bind(self) -> None:
        """A rigid mesh names its bone nowhere, so guessing one is not allowed."""

        from cdmw.modding.mesh_native_core import _fbx_skin_rows

        self.assertIsNone(_fbx_skin_rows(_skinned_export_mesh().submeshes[0], ()))

    def test_a_slot_outside_the_palette_refuses_to_bind(self) -> None:
        from cdmw.modding.mesh_native_core import _fbx_skin_rows

        self.assertIsNone(_fbx_skin_rows(_skinned_export_mesh().submeshes[0], (17,)))

    def test_rows_are_normalized_against_u8_quantization(self) -> None:
        from cdmw.modding.mesh_native_core import _fbx_skin_rows

        submesh = _skinned_export_mesh().submeshes[0]
        # A row as the file stores it: six u8 weights summing to 253, not 255.
        submesh.bone_indices = [(0,), (1,), (0, 1)]
        submesh.bone_weights = [(1.0,), (1.0,), (127 / 255.0, 126 / 255.0)]

        _indices, weights = _fbx_skin_rows(submesh, (0, 1))

        self.assertAlmostEqual(sum(weights[2]), 1.0, places=12)


class FbxSkinExportTests(unittest.TestCase):
    """The native writer must bind the mesh, not merely ship a loose armature."""

    def setUp(self) -> None:
        from cdmw.modding.mesh_native_core import find_native_mesh_core_binary

        if find_native_mesh_core_binary() is None:
            self.skipTest("cdmw_mesh_core is not built")

    def test_skinned_export_writes_deformer_and_cluster_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fbx_path = Path(export_fbx_with_skeleton(
                _skinned_export_mesh(), _two_bone_skeleton(), temp_dir,
                name="skinned", bone_palette=(0, 1),
            ))
            payload = fbx_path.read_bytes()

        for node in (b"Deformer", b"Skin", b"Cluster", b"Indexes", b"Weights", b"TransformLink", b"LimbNode"):
            self.assertIn(node, payload, f"{node!r} missing from the skinned FBX")

    def test_unresolved_palette_exports_an_armature_without_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fbx_path = Path(export_fbx_with_skeleton(
                _skinned_export_mesh(), _two_bone_skeleton(), temp_dir,
                name="rigid", bone_palette=(),
            ))
            payload = fbx_path.read_bytes()

        self.assertIn(b"LimbNode", payload)
        self.assertNotIn(b"Cluster", payload)
        self.assertNotIn(b"TransformLink", payload)

    def test_mesh_without_a_skeleton_stays_unbound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fbx_path = Path(export_fbx(_skinned_export_mesh(), temp_dir, name="plain"))
            payload = fbx_path.read_bytes()

        self.assertNotIn(b"Cluster", payload)
        self.assertNotIn(b"LimbNode", payload)


class FbxUnitScaleTests(unittest.TestCase):
    """A game unit is a metre, and the file has to say so.

    UnitScaleFactor states how many centimetres one unit is, and an importer
    divides by it -- Blender's global_scale is UnitScaleFactor/100. Declaring 1
    claimed centimetres for metre-scale geometry, so every export arrived at a
    hundredth of its size.
    """

    def _unit_scale_factors(self, payload: bytes) -> list[float]:
        import re
        import struct

        found = []
        for match in re.finditer(re.escape(b"UnitScaleFactor"), payload):
            window = payload[match.end():match.end() + 80]
            offset = 0
            while offset < len(window):
                kind = window[offset:offset + 1]
                if kind == b"S":
                    length = struct.unpack_from("<I", window, offset + 1)[0]
                    offset += 5 + length
                elif kind == b"D":
                    found.append(struct.unpack_from("<d", window, offset + 1)[0])
                    break
                else:
                    break
        return found

    def test_native_export_declares_metres(self) -> None:
        from cdmw.modding.mesh_native_core import find_native_mesh_core_binary

        if find_native_mesh_core_binary() is None:
            self.skipTest("cdmw_mesh_core is not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = Path(export_fbx(_export_mesh(), temp_dir, name="units")).read_bytes()

        self.assertEqual(self._unit_scale_factors(payload), [100.0, 100.0])

    def test_python_fallback_declares_the_same_unit(self) -> None:
        """The fallback writes its own GlobalSettings, so it can drift from the native one."""

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_native = _FakeNativeFbxGeometry(temp_dir)
            with (
                mock.patch("cdmw.modding.mesh_exporter._export_fbx_native", return_value=False),
                mock.patch("cdmw.modding.mesh_exporter._fbx_geometry_native", return_value=fake_native),
            ):
                payload = Path(export_fbx(_export_mesh(), temp_dir, name="units_fallback")).read_bytes()

        self.assertEqual(self._unit_scale_factors(payload), [100.0, 100.0])

    def test_skeleton_fallback_declares_the_same_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_native = _FakeNativeFbxGeometry(temp_dir)
            with (
                mock.patch("cdmw.modding.mesh_exporter._export_fbx_native", return_value=False),
                mock.patch("cdmw.modding.mesh_exporter._fbx_geometry_native", return_value=fake_native),
            ):
                payload = Path(export_fbx_with_skeleton(
                    _skinned_export_mesh(), _two_bone_skeleton(), temp_dir, name="units_skel"
                )).read_bytes()

        self.assertEqual(self._unit_scale_factors(payload), [100.0, 100.0])


class FbxBonePayloadTests(unittest.TestCase):
    """Bind matrices decide whether the mesh arrives at rest or pre-deformed."""

    def test_bone_payload_carries_a_local_transform_and_a_global_bind(self) -> None:
        from cdmw.modding.mesh_native_core import _native_fbx_bone_payloads

        payloads = _native_fbx_bone_payloads(_two_bone_skeleton())

        self.assertEqual(len(payloads), 2)
        child = payloads[1]
        # The bind matrix is global; the position it reports is local to the parent.
        self.assertEqual(child["bind_matrix"][12:15], [0.0, 2.0, 0.0])
        for value, expected in zip(child["position"], (0.0, 2.0, 0.0)):
            self.assertAlmostEqual(value, expected, places=9)

    def test_bone_payload_drops_scale_from_the_bind_basis(self) -> None:
        """A rest-pose bone cannot hold scale, so it is removed predictably."""

        from cdmw.modding.mesh_native_core import _native_fbx_bone_payloads

        scaled = Skeleton(
            path="character/scaled.pab",
            bones=[Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0),
                        bind_matrix=(3, 0, 0, 0, 0, 3, 0, 0, 0, 0, 3, 0, 1, 2, 3, 1))],
            bone_count=1,
        )
        bind = _native_fbx_bone_payloads(scaled)[0]["bind_matrix"]

        for row in range(3):
            length = sum(bind[row * 4 + column] ** 2 for column in range(3)) ** 0.5
            self.assertAlmostEqual(length, 1.0, places=9)
        self.assertEqual(bind[12:15], [1.0, 2.0, 3.0])


if __name__ == "__main__":
    unittest.main()
