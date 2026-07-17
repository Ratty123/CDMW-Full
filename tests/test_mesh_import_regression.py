from __future__ import annotations

import json
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cdmw.domain.mesh.export_validation import validate_mesh_export
from cdmw.modding.mesh_builder_common import _choose_static_donor_indices
from cdmw.modding.mesh_importer import (
    _build_pac_in_place,
    _choose_pac_donor_indices,
    _merge_partial_pac_import,
    _pack_pac_normal,
    build_mesh,
    import_obj,
)
from cdmw.modding.mesh_obj_importer import validate_obj_sidecar_source_identity
from cdmw.modding.mesh_parser import (
    PacDescriptor,
    ParsedMesh,
    SubMesh,
    _validated_pac_descriptor_prefix,
    parse_pac,
)


class MeshImportRegressionTests(unittest.TestCase):
    def test_pac_descriptor_validation_drops_only_exact_trailing_false_match(self) -> None:
        real_descriptors = [
            PacDescriptor(
                name="PartA",
                material="PartA",
                bbox_min=(0.0, 0.0, 0.0),
                bbox_extent=(1.0, 1.0, 1.0),
                vertex_counts=[2, 1, 0, 0],
                index_counts=[3, 3, 0, 0],
            ),
            PacDescriptor(
                name="PartB",
                material="PartB",
                bbox_min=(0.0, 0.0, 0.0),
                bbox_extent=(1.0, 1.0, 1.0),
                vertex_counts=[3, 2, 1, 1],
                index_counts=[6, 3, 3, 3],
            ),
        ]
        false_match = PacDescriptor(
            name="unknown_false_match",
            material="unknown_false_match",
            bbox_min=(0.0, 0.0, 0.0),
            bbox_extent=(1.0, 1.0, 1.0),
            vertex_counts=[1280, 256, 0, 0],
            index_counts=[16_778_752, 2048, 0, 0],
        )
        sections = [
            {"index": 4, "size": 218},
            {"index": 3, "size": 132},
            {"index": 2, "size": 46},
            {"index": 1, "size": 46},
        ]

        validated = _validated_pac_descriptor_prefix(
            [*real_descriptors, false_match],
            sections,
            filename="character/example.pac",
        )

        self.assertEqual(real_descriptors, validated)
        self.assertEqual(
            [*real_descriptors, false_match],
            _validated_pac_descriptor_prefix(
                [*real_descriptors, false_match],
                [{**section, "size": section["size"] + 1} for section in sections],
            ),
        )

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

    def test_parse_compact_skinnedmesh_box_pac_recovers_debug_geometry(self) -> None:
        data = bytearray(0x700)
        data[:4] = b"PAR "
        data[0x2A : 0x2A + len(b"SkinnedMesh_Box")] = b"SkinnedMesh_Box"
        data[0x6A4 : 0x6A4 + len(bytes.fromhex("ff240000000000010002"))] = bytes.fromhex("ff240000000000010002")

        mesh = parse_pac(bytes(data), "character/skinnedmesh_box.pac")

        self.assertEqual("pac", mesh.format)
        self.assertEqual(1, len(mesh.submeshes))
        self.assertEqual(24, mesh.total_vertices)
        self.assertEqual(12, mesh.total_faces)
        self.assertTrue(mesh.has_bones)
        self.assertEqual((-2.0, -2.0, -2.0), mesh.bbox_min)
        self.assertEqual((2.0, 2.0, 2.0), mesh.bbox_max)
        submesh = mesh.submeshes[0]
        self.assertEqual("SkinnedMesh_Box", submesh.name)
        self.assertEqual(list(range(24)), submesh.source_vertex_map)
        self.assertEqual(24, len(submesh.source_vertex_offsets))
        self.assertEqual(68, submesh.source_vertex_stride)
        self.assertEqual(36, submesh.source_index_count)
        self.assertEqual(24, len(submesh.bone_indices))
        self.assertEqual(24, len(submesh.bone_weights))

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
        source_bytes = b"original pac bytes"
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
                        "source_asset_hash": hashlib.sha256(source_bytes).hexdigest(),
                        "source_asset_size": len(source_bytes),
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
            self.assertEqual(hashlib.sha256(source_bytes).hexdigest(), getattr(mesh, "_cdmw_sidecar_source_asset_hash"))
            self.assertEqual(len(source_bytes), getattr(mesh, "_cdmw_sidecar_source_asset_size"))
            validate_obj_sidecar_source_identity(mesh, source_bytes)

            with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                build_mesh(mesh, b"altered! pac bytes")

    def test_obj_sidecar_rebuild_rejects_topology_change_without_rule(self) -> None:
        source_bytes = b"original pac bytes"
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "changed_topology.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "usemtl Mat",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "v 1 1 0",
                        "f 1 2 3",
                        "f 2 4 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "source_path": "character/model/example.pac",
                        "source_format": "pac",
                        "source_asset_hash": hashlib.sha256(source_bytes).hexdigest(),
                        "source_asset_size": len(source_bytes),
                        "import_rules": {"allow_topology_change": False},
                        "submeshes": [
                            {
                                "index": 0,
                                "name": "Part",
                                "vertex_count": 3,
                                "face_count": 1,
                                "source_vertex_map": [0, 1, 2],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))

            with self.assertRaisesRegex(ValueError, "OBJ sidecar topology changed"):
                build_mesh(mesh, source_bytes)

    def test_obj_import_rejects_unsupported_sidecar_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "bad_schema.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps({"format": "mesh_roundtrip_manifest_v2", "schema_version": 99}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Unsupported OBJ sidecar schema version"):
                import_obj(str(obj_path))

    def test_obj_import_rejects_sidecar_lods_without_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "missing_stable_id.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "lods": [{"lod_index": 0, "submeshes": [{"submesh_index": 0}]}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "missing stable_id"):
                import_obj(str(obj_path))

    def test_obj_import_rejects_skinned_sidecar_without_bone_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "missing_bone_layout.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "import_rules": {"preserve_bone_weights": True},
                        "skeleton_info": {"skinned": True},
                        "lods": [
                            {
                                "lod_index": 0,
                                "submeshes": [
                                    {
                                        "stable_id": "lod0_submesh0",
                                        "original_vertex_count": 3,
                                        "original_index_count": 3,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "bone metadata"):
                import_obj(str(obj_path))

    def test_obj_import_rejects_skinned_sidecar_without_source_vertex_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "missing_skin_source_map.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "import_rules": {"preserve_bone_weights": True},
                        "skeleton_info": {"skinned": True},
                        "lods": [
                            {
                                "lod_index": 0,
                                "submeshes": [
                                    {
                                        "stable_id": "lod0_submesh0",
                                        "original_vertex_count": 3,
                                        "original_index_count": 3,
                                        "bone_layout": {
                                            "has_bones": True,
                                            "vertex_count": 3,
                                            "max_influences": 1,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "source vertex map"):
                import_obj(str(obj_path))

    def test_obj_import_rejects_lod_sidecar_without_source_index_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "missing_source_index_map.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "lods": [
                            {
                                "lod_index": 0,
                                "submeshes": [
                                    {
                                        "stable_id": "lod0_submesh0",
                                        "original_vertex_count": 3,
                                        "original_index_count": 3,
                                        "source_vertex_map": [0, 1, 2],
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "source index map"):
                import_obj(str(obj_path))

    def test_obj_import_preserves_raw_index_count_when_obj_uses_triangle_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "strip_topology.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "source_path": "character/model/example.pac",
                        "source_format": "pac",
                        "submeshes": [
                            {
                                "index": 0,
                                "name": "Part",
                                "vertex_count": 3,
                                "face_count": 1,
                            }
                        ],
                        "lods": [
                            {
                                "lod_index": 0,
                                "submeshes": [
                                    {
                                        "stable_id": "lod0_submesh0",
                                        "original_vertex_count": 3,
                                        "original_index_count": 6,
                                        "exported_index_count": 3,
                                        "source_vertex_map": [0, 1, 2],
                                        "source_index_map": [0, 1, 2, 3, 4, 5],
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))

            self.assertEqual(1, len(mesh.submeshes[0].faces))
            self.assertEqual(6, mesh.submeshes[0].source_index_count)

    def test_obj_import_accepts_skinned_sidecar_with_bone_layout_and_source_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "with_bone_layout.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "import_rules": {"preserve_bone_weights": True},
                        "skeleton_info": {"skinned": True},
                        "lods": [
                            {
                                "lod_index": 0,
                                "submeshes": [
                                    {
                                        "stable_id": "lod0_submesh0",
                                        "original_vertex_count": 3,
                                        "original_index_count": 3,
                                        "bone_layout": {
                                            "has_bones": True,
                                            "vertex_count": 3,
                                            "max_influences": 1,
                                        },
                                        "source_vertex_map": [0, 1, 2],
                                        "source_index_map": [0, 1, 2],
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))

            self.assertTrue(getattr(mesh, "_cdmw_obj_sidecar_present"))

    def test_obj_import_accepts_mixed_skinned_sidecar_with_unweighted_bone_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "mixed_skinning.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example_weapon.pac",
                        "# source_format: pac",
                        "o StaticBlade",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                        "o WeightedGuard",
                        "v 0 0 1",
                        "v 1 0 1",
                        "v 0 1 1",
                        "f 4 5 6",
                    ]
                ),
                encoding="utf-8",
            )
            sidecar_submeshes = [
                {
                    "index": 0,
                    "name": "StaticBlade",
                    "material": "StaticBlade",
                    "texture": "",
                    "vertex_count": 3,
                    "face_count": 1,
                    "original_vertex_count": 3,
                    "original_index_count": 3,
                    "source_vertex_map": [0, 1, 2],
                    "source_index_map": [0, 1, 2],
                },
                {
                    "index": 1,
                    "name": "WeightedGuard",
                    "material": "WeightedGuard",
                    "texture": "",
                    "vertex_count": 3,
                    "face_count": 1,
                    "original_vertex_count": 3,
                    "original_index_count": 3,
                    "source_vertex_map": [0, 1, 2],
                    "source_index_map": [0, 1, 2],
                },
            ]
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "source_path": "character/model/example_weapon.pac",
                        "source_format": "pac",
                        "import_rules": {"preserve_bone_weights": True},
                        "skeleton_info": {"skinned": True},
                        "submeshes": sidecar_submeshes,
                        "lods": [
                            {
                                "lod_index": 0,
                                "submeshes": [
                                    {
                                        "stable_id": "lod0_submesh0",
                                        "original_vertex_count": 3,
                                        "original_index_count": 3,
                                        "source_vertex_map": [0, 1, 2],
                                        "source_index_map": [0, 1, 2],
                                        "bone_layout": {
                                            "has_bones": True,
                                            "vertex_count": 3,
                                            "max_influences": 0,
                                        },
                                    },
                                    {
                                        "stable_id": "lod0_submesh1",
                                        "original_vertex_count": 3,
                                        "original_index_count": 3,
                                        "source_vertex_map": [0, 1, 2],
                                        "source_index_map": [0, 1, 2],
                                        "bone_layout": {
                                            "has_bones": True,
                                            "vertex_count": 3,
                                            "max_influences": 1,
                                        },
                                    },
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))

            self.assertTrue(getattr(mesh, "_cdmw_obj_sidecar_present"))
            self.assertEqual(2, len(mesh.submeshes))

    def test_obj_import_accepts_legacy_sword_sidecar_with_only_empty_bone_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "sword.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: weapon/model/sword.pac",
                        "# source_format: pac",
                        "o Blade",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "source_path": "weapon/model/sword.pac",
                        "source_format": "pac",
                        "import_rules": {"preserve_bone_weights": True},
                        "skeleton_info": {"skinned": True},
                        "lods": [
                            {
                                "lod_index": 0,
                                "submeshes": [
                                    {
                                        "stable_id": "lod0_submesh0",
                                        "original_vertex_count": 3,
                                        "original_index_count": 3,
                                        "source_vertex_map": [0, 1, 2],
                                        "source_index_map": [0, 1, 2],
                                        "bone_layout": {
                                            "has_bones": False,
                                            "vertex_count": 3,
                                            "max_influences": 0,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))

            self.assertTrue(getattr(mesh, "_cdmw_obj_sidecar_present"))
            self.assertFalse(mesh.has_bones)

    def test_obj_import_warns_when_sidecar_material_or_texture_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "changed_material.obj"
            mtl_path = Path(temp_dir) / "changed_material.mtl"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "mtllib changed_material.mtl",
                        "o Part",
                        "usemtl NewMat",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            mtl_path.write_text("newmtl NewMat\nmap_Kd textures/new.dds\n", encoding="utf-8")
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "source_path": "character/model/example.pac",
                        "source_format": "pac",
                        "submeshes": [
                            {
                                "index": 0,
                                "name": "Part",
                                "material": "OldMat",
                                "texture": "textures/old.dds",
                                "vertex_count": 3,
                                "face_count": 1,
                                "source_vertex_map": [0, 1, 2],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))
            warning_codes = {warning["code"] for warning in getattr(mesh, "_cdmw_sidecar_warnings", ())}
            report = validate_mesh_export(mesh, available_textures=("textures/old.dds",))

            self.assertIn("sidecar_material_name_changed", warning_codes)
            self.assertIn("sidecar_texture_path_changed", warning_codes)
            self.assertIn("sidecar_material_name_changed", {issue.code for issue in report.warnings})
            self.assertIn("sidecar_texture_path_changed", {issue.code for issue in report.warnings})
            self.assertIn("sidecar_material_name_changed_blocks_rebuild", {issue.code for issue in report.blockers})
            self.assertIn("sidecar_texture_path_changed_blocks_rebuild", {issue.code for issue in report.blockers})
            with self.assertRaisesRegex(ValueError, "sidecar metadata drift blocked rebuild"):
                build_mesh(mesh, b"original pac bytes")

    def test_obj_import_accepts_sidecar_texture_id_when_mtl_adds_dds_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "same_texture.obj"
            mtl_path = Path(temp_dir) / "same_texture.mtl"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "mtllib same_texture.mtl",
                        "o Part",
                        "usemtl Mat",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            mtl_path.write_text("newmtl Mat\nmap_Kd textures/body.dds\n", encoding="utf-8")
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "source_path": "character/model/example.pac",
                        "source_format": "pac",
                        "submeshes": [
                            {
                                "index": 0,
                                "name": "Part",
                                "material": "Mat",
                                "texture": "textures/body",
                                "vertex_count": 3,
                                "face_count": 1,
                                "source_vertex_map": [0, 1, 2],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))

            warning_codes = {warning["code"] for warning in getattr(mesh, "_cdmw_sidecar_warnings", ())}
            self.assertNotIn("sidecar_texture_path_changed", warning_codes)

    def test_obj_import_records_same_count_edit_operations_from_sidecar_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "same_count.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "usemtl Mat",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "vn 0 0 1",
                        "f 1/1/1 2/2/1 3/3/1",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "source_path": "character/model/example.pac",
                        "source_format": "pac",
                        "allowed_edit_operations": [
                            "replace_positions_same_count",
                            "replace_normals_same_count",
                            "replace_uv0_same_count",
                        ],
                        "submeshes": [
                            {
                                "index": 0,
                                "name": "Part",
                                "material": "Mat",
                                "texture": "part.dds",
                                "vertex_count": 3,
                                "face_count": 1,
                                "source_vertex_map": [0, 1, 2],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))
            operations = tuple(getattr(mesh, "_cdmw_edit_operations", ()))
            report = validate_mesh_export(mesh, available_textures=("part.dds",))

            self.assertEqual(
                [
                    "replace_positions_same_count",
                    "replace_normals_same_count",
                    "replace_uv0_same_count",
                ],
                [operation["operation"] for operation in operations],
            )
            self.assertNotIn("disallowed_edit_operation", {issue.code for issue in report.blockers})

    def test_obj_import_rejects_same_count_operation_disallowed_by_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "disallowed_operation.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "source_path": "character/model/example.pac",
                        "source_format": "pac",
                        "allowed_edit_operations": ["replace_normals_same_count"],
                        "submeshes": [
                            {
                                "index": 0,
                                "name": "Part",
                                "vertex_count": 3,
                                "face_count": 1,
                                "source_vertex_map": [0, 1, 2],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "not allowed by sidecar rules"):
                import_obj(str(obj_path))

    def test_obj_sidecar_rebuild_requires_explicit_edit_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "missing_operations.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o Part",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                    ]
                ),
                encoding="utf-8",
            )
            Path(f"{obj_path}.meta.json").write_text(
                json.dumps(
                    {
                        "format": "mesh_roundtrip_manifest_v2",
                        "schema_version": 1,
                        "source_path": "character/model/example.pac",
                        "source_format": "pac",
                        "submeshes": [{"index": 0, "name": "Part", "source_vertex_map": [0, 1, 2]}],
                    }
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))
            report = validate_mesh_export(mesh, available_textures=())

            self.assertFalse(hasattr(mesh, "_cdmw_edit_operations"))
            self.assertIn("missing_edit_operations", {issue.code for issue in report.blockers})
            with self.assertRaisesRegex(ValueError, "requires explicit Mesh Editor v2 edit operations"):
                build_mesh(mesh, b"original pac bytes")

    def test_multi_submesh_obj_rebuild_requires_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "multi.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "# source_path: character/model/example.pac",
                        "# source_format: pac",
                        "o A",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "f 1 2 3",
                        "o B",
                        "v 0 0 1",
                        "v 1 0 1",
                        "v 0 1 1",
                        "f 4 5 6",
                    ]
                ),
                encoding="utf-8",
            )

            mesh = import_obj(str(obj_path))

            self.assertEqual(2, len(mesh.submeshes))
            with self.assertRaisesRegex(ValueError, "sidecar is required"):
                build_mesh(mesh, b"original pac bytes")

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
            source_vertex_map_authority="target_donor_record",
        )
        self.assertEqual(_choose_pac_donor_indices(original, imported), [2, 1])

    def test_static_donor_mapping_uses_native_alignment_before_python_fallback(self) -> None:
        original = SubMesh(
            vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 0.0)],
        )
        imported = SubMesh(vertices=[(99.0, 99.0, 99.0), (1.0, 1.0, 1.0)])

        with (
            mock.patch("cdmw.modding.mesh_native_core.build_native_static_donor_indices", return_value=[2, 0]) as native,
            mock.patch(
                "cdmw.modding.mesh_builder_common._align_static_vertex_sequences",
                side_effect=AssertionError("python donor alignment fallback should not run"),
            ),
        ):
            self.assertEqual(_choose_static_donor_indices(original, imported), [2, 0])

        native.assert_called_once_with(original, imported)

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
