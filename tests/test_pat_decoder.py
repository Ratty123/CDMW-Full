from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from cdmw.core.pat_decoder import build_pat_model_preview, decode_pat, export_pat_to_obj, validate_pat


def _vertex(x: int, y: int, z: int, u: float, v: float) -> bytes:
    payload = bytearray(struct.pack("<3H", x, y, z) + b"\x00" * 26)
    struct.pack_into("<2e", payload, 12, u, v)
    return bytes(payload)


def _sample_pat() -> bytes:
    header = bytearray()
    header.extend(b"PAR ")
    header.extend(b"\x04\x04\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09")
    header.extend(struct.pack("<3f", 0.0, 0.0, 0.0))
    header.extend(struct.pack("<3f", 1.0, 2.0, 3.0))
    header.extend(struct.pack("<I", 1))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 4))
    vertices = b"".join(
        [
            _vertex(0, 0, 0, 0.0, 0.0),
            _vertex(65535, 0, 0, 1.0, 0.0),
            _vertex(65535, 65535, 0, 1.0, 1.0),
            _vertex(0, 65535, 0, 0.0, 1.0),
        ]
    )
    index_table = struct.pack("<2I", 0, 6)
    indices = struct.pack("<6H", 0, 1, 2, 0, 2, 3)
    draw_table = struct.pack("<2I", 0, 1)
    draw_records = struct.pack("<4I", 0, 2, 0, 6)
    tail = (
        b"\x0f\x00\x00\x00leaf_sample_mat"
        b"\x15\x00\x00\x00leaf_sample_color.tga"
        b"\x16\x00\x00\x00leaf_sample_normal.tga"
    )
    return bytes(header) + vertices + index_table + indices + draw_table + draw_records + tail


class PatDecoderTests(unittest.TestCase):
    def test_decode_pat_reads_positions_indices_draws_and_materials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "sample.pat"
            path.write_bytes(_sample_pat())

            mesh = decode_pat(path)

            self.assertEqual(mesh.bbox_min, (0.0, 0.0, 0.0))
            self.assertEqual(mesh.bbox_max, (1.0, 2.0, 3.0))
            self.assertEqual(mesh.lod_vertex_counts, (4,))
            self.assertEqual(mesh.lod_index_counts, (6,))
            self.assertEqual(mesh.lod_draw_counts, (1,))
            self.assertEqual(mesh.vertices[2], (1.0, 2.0, 0.0))
            self.assertEqual(mesh.texture_coordinates[2], (1.0, 1.0))
            self.assertEqual(mesh.indices, (0, 1, 2, 0, 2, 3))
            self.assertEqual(mesh.draws[0].material_id, 0)
            self.assertEqual(mesh.draws[0].flags, 2)
            self.assertEqual(mesh.draws[0].index_count, 6)
            self.assertEqual(mesh.materials[0].name, "leaf_sample_mat")
            self.assertIn("leaf_sample_color.tga", mesh.materials[0].textures)

    def test_export_pat_to_obj_writes_lod_group_and_material(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "sample.pat"
            path.write_bytes(_sample_pat())
            obj_path, mtl_path = export_pat_to_obj(path, root / "out")

            obj_text = obj_path.read_text(encoding="utf-8")
            mtl_text = mtl_path.read_text(encoding="utf-8")

            self.assertIn("g lod00_draw00_mat000_flags002", obj_text)
            self.assertIn("vt 1.000000 1.000000", obj_text)
            self.assertIn("f 1/1 2/2 3/3", obj_text)
            self.assertIn("f 1/1 3/3 4/4", obj_text)
            self.assertIn("newmtl leaf_sample_mat_000", mtl_text)
            self.assertIn("# Source textures: leaf_sample_color.tga, leaf_sample_normal.tga", mtl_text)

    def test_build_pat_model_preview_uses_lod_draws_and_texture_hint(self) -> None:
        preview = build_pat_model_preview(_sample_pat(), "tree/sample.pat")

        self.assertEqual(preview.format, "pat")
        self.assertEqual(preview.lod_index, 0)
        self.assertEqual(preview.lod_count, 1)
        self.assertEqual(preview.mesh_count, 1)
        self.assertEqual(preview.face_count, 2)
        self.assertEqual(preview.meshes[0].material_name, "leaf_sample_mat")
        self.assertEqual(preview.meshes[0].texture_name, "leaf_sample_color.dds")
        self.assertEqual(preview.meshes[0].texture_coordinates[2], (1.0, 1.0))
        self.assertEqual(preview.meshes[0].preview_alpha_mode, "cutout")
        self.assertEqual(len(preview.meshes[0].normals), len(preview.meshes[0].positions))

    def test_validate_pat_flags_xar_stub(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stub.pat"
            path.write_bytes(b"XAR \x04\x04\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09")

            result = validate_pat(path)

            self.assertFalse(result.ok)
            self.assertIn("unsupported magic", result.reason)


if __name__ == "__main__":
    unittest.main()
