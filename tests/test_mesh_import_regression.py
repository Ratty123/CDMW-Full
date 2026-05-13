from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from cdmw.modding.mesh_importer import (
    _build_pac_in_place,
    _choose_pac_donor_indices,
    _merge_partial_pac_import,
    _pack_pac_normal,
    import_obj,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


class MeshImportRegressionTests(unittest.TestCase):
    @staticmethod
    def _submesh(name: str, vertices: int = 4, faces: int = 2) -> SubMesh:
        return SubMesh(
            name=name,
            material=f"{name}_mat",
            texture=f"{name}.dds",
            vertices=[(0.0, 0.0, 0.0)] * vertices,
            uvs=[(0.0, 0.0)] * vertices,
            normals=[(0.0, 1.0, 0.0)] * vertices,
            faces=[(0, 1, 2)] * faces,
            bone_indices=[(0,)] * vertices,
            bone_weights=[(1.0,)] * vertices,
            source_vertex_offsets=list(range(vertices)),
            source_vertex_map=list(range(vertices)),
            source_index_count=faces * 3,
            vertex_count=vertices,
            face_count=faces,
        )

    @staticmethod
    def _mesh(*submeshes: SubMesh) -> ParsedMesh:
        return ParsedMesh(
            path="character/test.pac",
            format="pac",
            submeshes=list(submeshes),
            total_vertices=sum(len(submesh.vertices) for submesh in submeshes),
            total_faces=sum(len(submesh.faces) for submesh in submeshes),
            has_uvs=any(bool(submesh.uvs) for submesh in submeshes),
            has_bones=any(bool(submesh.bone_indices) for submesh in submeshes),
        )

    def test_named_partial_pac_import_empties_unmentioned_original_submeshes(self) -> None:
        original = self._mesh(
            self._submesh("helmet_shell"),
            self._submesh("helmet_wing"),
            self._submesh("helmet_inside"),
        )
        imported = self._mesh(self._submesh("helmet_wing", vertices=5, faces=3))

        merged = _merge_partial_pac_import(original, imported)

        self.assertEqual([submesh.name for submesh in merged.submeshes], ["helmet_shell", "helmet_wing", "helmet_inside"])
        self.assertEqual(len(merged.submeshes[0].vertices), 0)
        self.assertEqual(len(merged.submeshes[0].faces), 0)
        self.assertEqual(merged.submeshes[0].uvs, [])
        self.assertEqual(merged.submeshes[0].normals, [])
        self.assertEqual(merged.submeshes[0].bone_indices, [])
        self.assertEqual(merged.submeshes[0].bone_weights, [])
        self.assertEqual(merged.submeshes[0].source_vertex_offsets, [])
        self.assertEqual(merged.submeshes[0].source_vertex_map, [])
        self.assertGreater(len(merged.submeshes[1].vertices), 0)
        self.assertEqual(len(merged.submeshes[2].vertices), 0)
        self.assertEqual(merged.total_vertices, len(merged.submeshes[1].vertices))
        self.assertEqual(merged.total_faces, len(merged.submeshes[1].faces))

    def test_unnamed_partial_pac_import_is_still_rejected(self) -> None:
        original = self._mesh(self._submesh("a"), self._submesh("b"), self._submesh("c"))
        imported = self._mesh(self._submesh(""), self._submesh(""))

        with self.assertRaises(ValueError):
            _merge_partial_pac_import(original, imported)

    def test_obj_roundtrip_vertex_split_preserves_source_vertex_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "split.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "usemtl Mat",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 1 1 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 1 1",
                        "vt 0.25 0.75",
                        "vt 0 1",
                        "vn 0 0 1",
                        "f 1/1/1 2/2/1 3/3/1",
                        "f 1/4/1 3/3/1 4/5/1",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "source_path": "character/model/example.pac",
                        "source_format": "pac",
                        "submeshes": [
                            {
                                "index": 0,
                                "name": "Part",
                                "material": "Mat",
                                "texture": "part.dds",
                                "vertex_count": 4,
                                "face_count": 2,
                                "source_vertex_map": [10, 11, 12, 13],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))
            submesh = mesh.submeshes[0]

            self.assertEqual(len(submesh.vertices), 5)
            self.assertEqual(submesh.source_vertex_map, [10, 11, 12, 13, 10])

    def test_obj_import_preserves_explicit_vertex_normals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "normals.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "o Part",
                        "usemtl Mat",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "vn 0.7071 0 0.7071",
                        "vn 0 0.7071 0.7071",
                        "vn -0.7071 0 0.7071",
                        "f 1/1/1 2/2/2 3/3/3",
                    ]
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))

        normals = mesh.submeshes[0].normals
        self.assertEqual(len(normals), 3)
        self.assertAlmostEqual(normals[0][0], 0.7071, places=4)
        self.assertAlmostEqual(normals[1][1], 0.7071, places=4)
        self.assertAlmostEqual(normals[2][0], -0.7071, places=4)

    def test_pac_donor_mapping_prefers_roundtrip_source_map_for_skinning_records(self) -> None:
        original = SubMesh(
            vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 0.0)],
        )
        imported = SubMesh(
            vertices=[(99.0, 99.0, 99.0), (0.0, 0.0, 0.0)],
            source_vertex_map=[2, 1],
        )

        self.assertEqual(_choose_pac_donor_indices(original, imported), [2, 1])

    def test_pac_in_place_rebuild_writes_imported_normals(self) -> None:
        data = bytearray(128)
        record_offset = 80
        struct.pack_into("<I", data, record_offset + 16, 0xC0000000)
        original_sm = SubMesh(
            vertices=[(0.0, 0.0, 0.0)],
            source_vertex_offsets=[record_offset],
            source_vertex_stride=32,
            source_descriptor_offset=0,
        )
        imported_sm = SubMesh(
            vertices=[(1.0, 2.0, 3.0)],
            normals=[(0.0, 0.0, 1.0)],
        )
        original_mesh = ParsedMesh(path="character/test.pac", format="pac", submeshes=[original_sm])
        imported_mesh = ParsedMesh(path="character/test.pac", format="pac", submeshes=[imported_sm])

        rebuilt = _build_pac_in_place(original_mesh, imported_mesh, bytes(data))

        packed_normal = struct.unpack_from("<I", rebuilt, record_offset + 16)[0]
        self.assertEqual(packed_normal, _pack_pac_normal((0.0, 0.0, 1.0), 0xC0000000))
        self.assertEqual(packed_normal & 0xC0000000, 0xC0000000)

    def test_pac_in_place_rebuild_can_clean_donor_shading_records(self) -> None:
        data = bytearray(128)
        record_offset = 80
        struct.pack_into("<H", data, record_offset + 6, 0xFFFF)
        struct.pack_into("<I", data, record_offset + 16, 0xC0000000)
        data[record_offset + 20 : record_offset + 28] = b"\x11" * 8
        original_sm = SubMesh(
            vertices=[(0.0, 0.0, 0.0)],
            source_vertex_offsets=[record_offset],
            source_vertex_stride=32,
            source_descriptor_offset=0,
        )
        imported_sm = SubMesh(
            vertices=[(1.0, 2.0, 3.0)],
            normals=[(0.0, 0.0, 1.0)],
        )
        original_mesh = ParsedMesh(path="character/test.pac", format="pac", submeshes=[original_sm])
        imported_mesh = ParsedMesh(path="character/test.pac", format="pac", submeshes=[imported_sm])
        setattr(imported_mesh, "clean_donor_shading_records", True)

        rebuilt = _build_pac_in_place(original_mesh, imported_mesh, bytes(data))

        self.assertEqual(struct.unpack_from("<H", rebuilt, record_offset + 6)[0], 0)
        self.assertEqual(rebuilt[record_offset + 20 : record_offset + 28], b"\x00" * 8)
        packed_normal = struct.unpack_from("<I", rebuilt, record_offset + 16)[0]
        self.assertEqual(packed_normal, _pack_pac_normal((0.0, 0.0, 1.0), 0))
        self.assertEqual(packed_normal & 0xC0000000, 0)


if __name__ == "__main__":
    unittest.main()
