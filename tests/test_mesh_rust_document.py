from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import struct
import unittest

from cdmw.services import mesh_rust_document as codec


def _fixture_document():
    part = {
        "name": "Precision seam Ω", "material": "Material", "layout": "pac_slot_u10x6",
        "source_range": {"offset": 0xFFFFFFFFFFFFFFFF, "length": 0}, "vertex_stride": 40,
        "positions": [
            [-0.0, 1.0 + 2.0 ** -24, 1.0 + 3.0 * 2.0 ** -24],
            [2.0 ** -149, 2.0 ** -150, -(2.0 ** -150)],
            [float.fromhex("0x0.0000000000001p-1022"), 1.23456789012345, float.fromhex("0x1.fffffep+127")],
        ],
        "normals": [[-0.0, 0.0, 1.0]],
        "uvs": [[0.0, 1.0], [1.0 / 3.0, 0.25], [0.5, 0.75], [1.0, 0.0]],
        "indices": [0, 1, 2],
        "source_vertex_indices": [-1, 0, 2147483647, -2147483648],
        "shader_masks": [[0.2, 0.5, 0.8], [1.0 + 2.0 ** -25, -5e-324, 0.0], [1.0, 1.0, 0.0]],
    }
    other = {
        "name": "Other LOD", "material": "", "layout": "cdmw_session",
        "source_range": {"offset": 0, "length": 0}, "vertex_stride": 0,
        "positions": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        "normals": [], "uvs": [], "indices": [0, 1, 2], "source_vertex_indices": [], "shader_masks": [],
    }
    return {
        "format": "pac", "source_sha256": "A" * 64,
        "parser": "cdmw_rust_mesh_authoring_package_v1", "lod_count_reported": 3,
        "lods": [{"level": 0, "submeshes": [part]}, {"level": 2, "submeshes": [other]}],
        "warnings": ["Synthetic protocol fixture"], "structural_fingerprint": "",
    }


def _parts(document):
    return [part for lod in document["lods"] for part in lod["submeshes"]]


def _unpack(data):
    magic, version, flags, size = codec.BINARY_MESH_DOCUMENT_HEADER.unpack_from(data)
    start = codec.BINARY_MESH_DOCUMENT_HEADER.size
    return (magic, version, flags), json.loads(data[start:start + size]), data[start + size:]


def _repack(header, metadata, raw):
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return codec.BINARY_MESH_DOCUMENT_HEADER.pack(*header, len(encoded)) + encoded + raw


class BinaryMeshDocumentTests(unittest.TestCase):
    def test_round_trip_preserves_float64_channels_and_native_optional_lengths(self):
        document = _fixture_document()
        encoded = codec.encode_mesh_document(document)
        decoded = codec.decode_mesh_document(encoded, expected_count=2)
        expected = copy.deepcopy(document)
        expected["structural_fingerprint"] = decoded["structural_fingerprint"]
        self.assertEqual(expected, decoded)
        self.assertEqual(encoded, codec.encode_mesh_document(decoded))
        for before, after in zip(_parts(document), _parts(decoded)):
            for name in ("positions", "normals", "uvs", "shader_masks"):
                before_bits = [struct.pack("<d", value) for row in before[name] for value in row]
                after_bits = [struct.pack("<d", value) for row in after[name] for value in row]
                self.assertEqual(before_bits, after_bits, name)
        self.assertLess(math.copysign(1.0, decoded["lods"][0]["submeshes"][0]["positions"][0][0]), 0.0)

    def test_shared_python_rust_fixture_is_exact_current_encoding(self):
        fixture = Path(__file__).resolve().parents[1] / "tools/rust_mesh_lab/apps/cdmw_mesh_lab/tests/fixtures/mesh-document-binary-v1.json"
        data = json.loads(fixture.read_text(encoding="utf-8"))
        binary = bytes.fromhex(data["binary_hex"])
        self.assertEqual(binary, codec.encode_mesh_document(data["input_document"]))
        self.assertEqual(data["expected_document"], codec.decode_mesh_document(binary, expected_count=2))

    def test_header_versions_lengths_and_trailing_bytes_fail_closed(self):
        data = codec.encode_mesh_document(_fixture_document())
        header, metadata, raw = _unpack(data)
        variants = [
            b"CDMWMSH2" + data[8:],
            _repack((header[0], 2, 0), metadata, raw),
            _repack((header[0], 1, 1), metadata, raw),
            data[:15], data[:-1], data + b"\0",
            codec.BINARY_MESH_DOCUMENT_HEADER.pack(header[0], 1, 0, 16 * 1024 * 1024 + 1) + data[16:],
        ]
        for index, invalid in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(codec.BinaryMeshDocumentError):
                codec.decode_mesh_document(invalid)
        with self.assertRaisesRegex(codec.BinaryMeshDocumentError, "element count"):
            codec.decode_mesh_document(data, expected_count=3)

    def test_deeply_nested_metadata_is_rejected_as_a_document_error(self):
        depth = 32_768
        metadata = b'{"nested":' + b'[' * depth + b'0' + b']' * depth + b'}'
        payload = codec.BINARY_MESH_DOCUMENT_HEADER.pack(
            codec.BINARY_MESH_DOCUMENT_MAGIC, 1, 0, len(metadata),
        ) + metadata
        with self.assertRaisesRegex(codec.BinaryMeshDocumentError, "not valid UTF-8 JSON"):
            codec.decode_mesh_document(payload)

    def test_descriptor_overflow_overlap_gaps_types_and_unknown_fields_fail_closed(self):
        encoded = codec.encode_mesh_document(_fixture_document())
        header, metadata, raw = _unpack(encoded)
        mutations = (
            lambda meta: meta.update(schema="cdmw_mesh_document_binary_v2"),
            lambda meta: meta.update(unrecognized=True),
            lambda meta: meta["lods"][0].update(unrecognized=True),
            lambda meta: _parts(meta)[0].update(unrecognized=True),
            lambda meta: _parts(meta)[0]["positions"].update(unrecognized=True),
            lambda meta: _parts(meta)[0]["positions"].update(count=0xFFFFFFFFFFFFFFFF),
            lambda meta: _parts(meta)[0]["positions"].update(count=-1),
            lambda meta: _parts(meta)[0]["positions"].update(count=True),
            lambda meta: _parts(meta)[0]["positions"].update(offset=1),
            lambda meta: _parts(meta)[0]["normals"].update(offset=0),
            lambda meta: _parts(meta)[0]["indices"].update(dtype="i32_le"),
            lambda meta: _parts(meta)[0]["positions"].update(components=2),
            lambda meta: _parts(meta)[0]["positions"].update(byte_length=1),
        )
        for index, mutate in enumerate(mutations):
            changed = copy.deepcopy(metadata)
            mutate(changed)
            with self.subTest(index=index), self.assertRaises(codec.BinaryMeshDocumentError):
                codec.decode_mesh_document(_repack(header, changed, raw))

    def test_duplicate_metadata_fields_and_changed_fingerprint_are_rejected(self):
        data = codec.encode_mesh_document(_fixture_document())
        header, metadata, raw = _unpack(data)
        text = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        duplicate = ("{\"schema\":\"cdmw_mesh_document_binary_v1\"," + text[1:]).encode("utf-8")
        with self.assertRaises(codec.BinaryMeshDocumentError):
            codec.decode_mesh_document(codec.BINARY_MESH_DOCUMENT_HEADER.pack(*header, len(duplicate)) + duplicate + raw)
        metadata["structural_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(codec.BinaryMeshDocumentError, "fingerprint does not match"):
            codec.decode_mesh_document(_repack(header, metadata, raw))

    def test_native_numeric_limits_are_checked_without_integer_wrapping(self):
        for field, row, value in (
            ("positions", 0, [float("nan"), 0.0, 0.0]),
            ("positions", 0, [float("inf"), 0.0, 0.0]),
            ("positions", 0, [float.fromhex("0x1.ffffffp+127"), 0.0, 0.0]),
            ("normals", 0, [0.0, 0.0, float("inf")]),
            ("uvs", 0, [0.0, float("nan")]),
            ("indices", 0, -1), ("indices", 0, 0x100000000), ("indices", 0, 3),
            ("source_vertex_indices", 0, -2147483649),
            ("source_vertex_indices", 0, 2147483648),
            ("shader_masks", 0, [0.2, 0.5, 1.1]),
            ("shader_masks", 0, [False, False, True]),
        ):
            document = _fixture_document()
            _parts(document)[0][field][row] = value
            with self.subTest(field=field, value=value), self.assertRaises(codec.BinaryMeshDocumentError):
                codec.encode_mesh_document(document)

    def test_decoding_rechecks_shader_values_even_with_unchanged_geometry_fingerprint(self):
        data = codec.encode_mesh_document(_fixture_document())
        header, metadata, raw = _unpack(data)
        for value in (float("nan"), float("inf"), 1.1):
            changed = bytearray(raw)
            offset = _parts(metadata)[0]["shader_masks"]["offset"]
            struct.pack_into("<d", changed, offset, value)
            with self.subTest(value=value), self.assertRaises(codec.BinaryMeshDocumentError):
                codec.decode_mesh_document(_repack(header, metadata, changed))

    def test_size_and_native_vertex_bounds_precede_array_allocation(self):
        class CountOnly:
            def __len__(self):
                return 10_000_001

            def __iter__(self):
                raise AssertionError("Oversized rows must never be decoded")

        document = _fixture_document()
        _parts(document)[0]["positions"] = CountOnly()
        _parts(document)[0]["shader_masks"] = []
        with self.assertRaisesRegex(codec.BinaryMeshDocumentError, "vertex count"):
            codec.encode_mesh_document(document)
        with self.assertRaisesRegex(codec.BinaryMeshDocumentError, "session limit"):
            codec.encode_mesh_document(_fixture_document(), max_payload_bytes=64)

    def test_fingerprint_tracks_positions_indices_and_lod_structure(self):
        original = _fixture_document()
        before = codec.decode_mesh_document(codec.encode_mesh_document(original))["structural_fingerprint"]
        for mutate in (
            lambda doc: _parts(doc)[0]["positions"][0].__setitem__(0, 0.5),
            lambda doc: _parts(doc)[0].update(indices=[2, 1, 0]),
            lambda doc: doc["lods"][1].update(level=3),
        ):
            changed = copy.deepcopy(original)
            mutate(changed)
            after = codec.decode_mesh_document(codec.encode_mesh_document(changed))["structural_fingerprint"]
            self.assertNotEqual(before, after)
        _parts(original)[0]["normals"][0][0] = 0.25
        after = codec.decode_mesh_document(codec.encode_mesh_document(original))["structural_fingerprint"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
