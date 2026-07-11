import base64
import json
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from cdmw.core.archive_modding import attach_scene_preview_textures, parsed_mesh_to_preview_model
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.scene_importer import (
    SCENE_COMPANION_SOURCE_EXTENSIONS,
    SCENE_IMPORT_EXTENSIONS,
    discover_scene_texture_files,
    discover_local_mesh_supplemental_files,
    import_scene_mesh,
    import_scene_mesh_with_report,
)
from cdmw.modding.static_mesh_replacer import suggest_static_submesh_mappings
from tests.scene_gltf_test_support import valid_image_bytes, write_valid_image


def _pad4(data: bytes) -> bytes:
    return data + (b"\x00" * ((4 - (len(data) % 4)) % 4))


def _huge_header_png(width: int = 20_000, height: int = 10_000) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def _triangle_payload(*, image_bytes: bytes = b"", image_mime: str = "image/png") -> tuple[bytes, dict]:
    chunks: list[bytes] = []
    buffer_views: list[dict] = []

    def add_view(data: bytes, target: int = 0) -> int:
        offset = sum(len(chunk) for chunk in chunks)
        padded = _pad4(data)
        chunks.append(padded)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    position_view = add_view(struct.pack("<9f", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0), 34962)
    normal_view = add_view(struct.pack("<9f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0), 34962)
    uv_view = add_view(struct.pack("<6f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0), 34962)
    index_view = add_view(struct.pack("<3H", 0, 1, 2), 34963)
    image_view = add_view(image_bytes) if image_bytes else -1
    accessors = [
        {"bufferView": position_view, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": normal_view, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": uv_view, "componentType": 5126, "count": 3, "type": "VEC2"},
        {"bufferView": index_view, "componentType": 5123, "count": 3, "type": "SCALAR"},
    ]
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": sum(len(chunk) for chunk in chunks)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "materials": [{"name": "Body"}],
        "meshes": [
            {
                "name": "Triangle",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                        "indices": 3,
                        "material": 0,
                    }
                ],
            }
        ],
        "nodes": [{"name": "Node", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    if image_view >= 0:
        document["materials"][0]["pbrMetallicRoughness"] = {"baseColorTexture": {"index": 0}}
        document["textures"] = [{"source": 0}]
        document["images"] = [{"bufferView": image_view, "mimeType": image_mime}]
    return b"".join(chunks), document


def _skinned_triangle_payload() -> tuple[bytes, dict]:
    chunks: list[bytes] = []
    buffer_views: list[dict] = []

    def add_view(data: bytes, target: int = 0) -> int:
        offset = sum(len(chunk) for chunk in chunks)
        padded = _pad4(data)
        chunks.append(padded)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    position_view = add_view(struct.pack("<9f", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0), 34962)
    normal_view = add_view(struct.pack("<9f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0), 34962)
    uv_view = add_view(struct.pack("<6f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0), 34962)
    index_view = add_view(struct.pack("<3H", 0, 1, 2), 34963)
    joint_view = add_view(struct.pack("<12H", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), 34962)
    weight_view = add_view(struct.pack("<12f", 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0), 34962)
    inverse_bind_view = add_view(
        struct.pack(
            "<16f",
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            -100.0, 0.0, 0.0, 1.0,
        ),
    )
    accessors = [
        {"bufferView": position_view, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": normal_view, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": uv_view, "componentType": 5126, "count": 3, "type": "VEC2"},
        {"bufferView": index_view, "componentType": 5123, "count": 3, "type": "SCALAR"},
        {"bufferView": joint_view, "componentType": 5123, "count": 3, "type": "VEC4"},
        {"bufferView": weight_view, "componentType": 5126, "count": 3, "type": "VEC4"},
        {"bufferView": inverse_bind_view, "componentType": 5126, "count": 1, "type": "MAT4"},
    ]
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": sum(len(chunk) for chunk in chunks)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "materials": [{"name": "Body"}],
        "meshes": [
            {
                "name": "SkinnedTriangle",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "NORMAL": 1,
                            "TEXCOORD_0": 2,
                            "JOINTS_0": 4,
                            "WEIGHTS_0": 5,
                        },
                        "indices": 3,
                        "material": 0,
                    }
                ],
            }
        ],
        "nodes": [
            {"name": "MeshNode", "mesh": 0, "skin": 0, "translation": [100.0, 0.0, 0.0]},
            {"name": "JointNode", "translation": [100.0, 5.0, 0.0]},
        ],
        "skins": [{"joints": [1], "inverseBindMatrices": 6}],
        "scenes": [{"nodes": [0, 1]}],
        "scene": 0,
    }
    return b"".join(chunks), document


def _write_glb(path: Path, document: dict, bin_chunk: bytes) -> None:
    json_chunk = _pad4(json.dumps(document, separators=(",", ":")).encode("utf-8"))
    bin_payload = _pad4(bin_chunk)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_payload)
    path.write_bytes(
        struct.pack("<III", 0x46546C67, 2, total_length)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(bin_payload), 0x004E4942)
        + bin_payload
    )


class GltfSceneImporterTests(unittest.TestCase):
    def test_minimal_glb_triangle_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_chunk, document = _triangle_payload()
            path = Path(tmp) / "triangle.glb"
            _write_glb(path, document, bin_chunk)

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)

            self.assertIn(".glb", SCENE_IMPORT_EXTENSIONS)
            self.assertEqual(result.mesh.format, "glb")
            self.assertEqual(result.mesh.total_vertices, 3)
            self.assertEqual(result.mesh.total_faces, 1)
            self.assertTrue(result.mesh.has_uvs)
            self.assertIsNone(preview_model.meshes[0].preview_texture_flip_vertical)

    def test_zip_containing_gltf_imports_via_safe_extract_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            document["buffers"][0]["uri"] = "triangle.bin"
            archive = root / "packed.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("scene/triangle.bin", bin_chunk)
                zip_file.writestr("scene/model.gltf", json.dumps(document))

            result = import_scene_mesh_with_report(archive)

            self.assertIn(".zip", SCENE_IMPORT_EXTENSIONS)
            self.assertEqual("gltf", result.mesh.format)
            self.assertEqual(3, result.mesh.total_vertices)
            self.assertEqual(1, result.mesh.total_faces)
            self.assertIn("Resolved ZIP archive packed.zip", " ".join(result.diagnostics))

    def test_gltf_external_buffer_and_texture_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            write_valid_image(root / "body_base.png")
            write_valid_image(root / "body_normal.png")
            write_valid_image(root / "body_metallic_roughness.png")
            write_valid_image(root / "body_emissive.png")
            document["buffers"][0]["uri"] = "triangle.bin"
            document["materials"][0]["pbrMetallicRoughness"] = {
                "baseColorTexture": {"index": 0},
                "metallicRoughnessTexture": {"index": 1},
            }
            document["materials"][0]["normalTexture"] = {"index": 2}
            document["materials"][0]["emissiveTexture"] = {"index": 3}
            document["materials"][0]["emissiveFactor"] = [0.2, 0.6, 1.0]
            document["materials"][0]["alphaMode"] = "MASK"
            document["materials"][0]["doubleSided"] = True
            document["materials"][0]["extensions"] = {
                "KHR_materials_emissive_strength": {"emissiveStrength": 4.5}
            }
            document["textures"] = [{"source": 0}, {"source": 1}, {"source": 2}, {"source": 3}]
            document["images"] = [
                {"uri": "body_base.png"},
                {"uri": "body_metallic_roughness.png"},
                {"uri": "body_normal.png"},
                {"uri": "body_emissive.png"},
            ]
            path = root / "triangle.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            discovered = discover_scene_texture_files(path, result.mesh)

            self.assertEqual(result.mesh.format, "gltf")
            self.assertIsNone(preview_model.meshes[0].preview_texture_flip_vertical)
            self.assertIn((root / "body_base.png").resolve(), result.discovered_texture_files)
            self.assertIn((root / "body_normal.png").resolve(), result.discovered_texture_files)
            self.assertIn((root / "body_metallic_roughness.png").resolve(), result.discovered_texture_files)
            self.assertIn((root / "body_emissive.png").resolve(), result.discovered_texture_files)
            self.assertIn((root / "body_base.png").resolve(), discovered)
            self.assertIn((root / "body_normal.png").resolve(), discovered)
            self.assertIn((root / "body_metallic_roughness.png").resolve(), discovered)
            self.assertIn((root / "body_emissive.png").resolve(), discovered)
            self.assertEqual((root / "body_base.png").resolve().as_posix(), result.mesh.submeshes[0].texture)
            self.assertEqual(1, len(result.material_bindings))
            binding_slots = {slot for slot, _path in result.material_bindings[0].texture_slots}
            self.assertIn("base", binding_slots)
            self.assertIn("normal", binding_slots)
            self.assertIn("material", binding_slots)
            self.assertIn("emissive", binding_slots)
            self.assertEqual("metallicRoughness", result.material_bindings[0].pbr_workflow)
            preview_inputs = tuple(getattr(preview_model.meshes[0], "preview_material_texture_inputs", ()) or ())
            self.assertIn("emissive", {item.slot_kind for item in preview_inputs})
            self.assertEqual("MASK", preview_model.meshes[0].preview_alpha_mode)
            self.assertTrue(preview_model.meshes[0].preview_double_sided)
            material_inputs = [item for item in preview_inputs if item.parameter_name == "_metallicRoughnessTexture"]
            self.assertTrue(material_inputs)
            self.assertEqual("metallic_roughness", material_inputs[0].semantic_subtype)
            emissive_inputs = [item for item in preview_inputs if item.slot_kind == "emissive"]
            self.assertEqual("SkinnedMeshEmissive_Ver2", emissive_inputs[0].shader_family)
            self.assertIn("_emissiveIntensity", {parameter.parameter_name for parameter in emissive_inputs[0].material_parameters})
            self.assertIsNotNone(result.external_audit)
            self.assertIn("base", result.external_audit.texture_slots)
            self.assertIn("normal", result.external_audit.texture_slots)
            self.assertEqual(1, len(result.external_audit.material_inventory))
            inventory = result.external_audit.material_inventory[0]
            self.assertEqual("Body", inventory.material_name)
            self.assertEqual("metallic_roughness", inventory.pbr_workflow)
            self.assertEqual("MASK", inventory.alpha_mode)
            self.assertTrue(inventory.double_sided)
            slots_by_kind = {slot.slot_kind: slot for slot in inventory.texture_slots}
            self.assertEqual("srgb", slots_by_kind["base"].color_space)
            self.assertEqual("linear", slots_by_kind["material"].color_space)
            self.assertEqual("srgb", slots_by_kind["emissive"].color_space)
            self.assertIn("emissive", {item.material_class for item in inventory.material_classes})

    def test_gltf_external_audit_records_material_class_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            for name in (
                "gold_base.png",
                "gold_metallicRoughness.png",
                "gold_emissive.png",
                "gold_transmission.png",
            ):
                write_valid_image(root / name)
            document["buffers"][0]["uri"] = "triangle.bin"
            document["materials"][0] = {
                "name": "Gold Crystal Emissive Metal",
                "alphaMode": "BLEND",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 0.72, 0.18, 0.55],
                    "baseColorTexture": {"index": 0},
                    "metallicRoughnessTexture": {"index": 1},
                    "metallicFactor": 1.0,
                    "roughnessFactor": 0.22,
                },
                "emissiveTexture": {"index": 2},
                "emissiveFactor": [1.0, 0.6, 0.1],
                "extensions": {
                    "KHR_materials_transmission": {
                        "transmissionFactor": 0.7,
                        "transmissionTexture": {"index": 3},
                    }
                },
            }
            document["textures"] = [{"source": index} for index in range(4)]
            document["images"] = [
                {"uri": "gold_base.png"},
                {"uri": "gold_metallicRoughness.png"},
                {"uri": "gold_emissive.png"},
                {"uri": "gold_transmission.png"},
            ]
            path = root / "gold_crystal.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)

            audit = result.external_audit
            self.assertIsNotNone(audit)
            assert audit is not None
            inventory = audit.material_inventory[0]
            scalar_hints = dict(inventory.scalar_hints)
            class_names = {item.material_class for item in inventory.material_classes}
            aggregate_classes = {item.material_class for item in audit.material_classes}
            transmission_slots = [slot for slot in inventory.texture_slots if slot.semantic_subtype == "transmission"]

            self.assertEqual("metallic_roughness", inventory.pbr_workflow)
            self.assertEqual("BLEND", inventory.alpha_mode)
            self.assertAlmostEqual(1.0, scalar_hints["metalness"])
            self.assertAlmostEqual(0.22, scalar_hints["roughness"])
            self.assertAlmostEqual(0.7, scalar_hints["transmission"])
            self.assertIn("gold", class_names)
            self.assertIn("metal", class_names)
            self.assertIn("emissive", class_names)
            self.assertIn("glass_crystal", class_names)
            self.assertIn("gold", aggregate_classes)
            self.assertTrue(transmission_slots)
            self.assertTrue(inventory.material_classes[0].evidence)

    def test_gltf_external_audit_does_not_treat_workflow_label_as_metal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            document["buffers"][0]["uri"] = "triangle.bin"
            document["materials"][0] = {
                "name": "GemOutside",
                "alphaMode": "BLEND",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 0.0, 0.0, 0.5],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.0,
                },
                "extensions": {
                    "KHR_materials_specular": {"specularFactor": 1.0},
                    "KHR_materials_transmission": {"transmissionFactor": 0.5},
                },
            }
            path = root / "red_gem.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)

            audit = result.external_audit
            self.assertIsNotNone(audit)
            assert audit is not None
            inventory = audit.material_inventory[0]
            class_names = {item.material_class for item in inventory.material_classes}
            self.assertEqual("metallic_roughness", inventory.pbr_workflow)
            self.assertIn("glass_crystal", class_names)
            self.assertNotIn("metal", class_names)

    def test_gltf_external_audit_uses_texture_channel_stats_for_material_classes(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            Image.new("RGBA", (2, 2), (222, 174, 42, 128)).save(root / "ornament_base.png")
            Image.new("RGBA", (2, 2), (255, 48, 235, 255)).save(root / "ornament_metallicRoughness.png")
            document["buffers"][0]["uri"] = "triangle.bin"
            document["materials"][0] = {
                "name": "Ornament",
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicRoughnessTexture": {"index": 1},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.5,
                },
            }
            document["textures"] = [{"source": 0}, {"source": 1}]
            document["images"] = [
                {"uri": "ornament_base.png"},
                {"uri": "ornament_metallicRoughness.png"},
            ]
            path = root / "ornament.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)

            audit = result.external_audit
            self.assertIsNotNone(audit)
            assert audit is not None
            inventory = audit.material_inventory[0]
            slots_by_kind = {slot.slot_kind: slot for slot in inventory.texture_slots}
            base_stats = dict(slots_by_kind["base"].channel_stats)
            material_stats = dict(slots_by_kind["material"].channel_stats)
            gold = next(item for item in inventory.material_classes if item.material_class == "gold")
            metal = next(item for item in inventory.material_classes if item.material_class == "metal")
            glass = next(item for item in inventory.material_classes if item.material_class == "glass_crystal")

            self.assertAlmostEqual(222 / 255.0, base_stats["r_mean"], places=3)
            self.assertAlmostEqual(128 / 255.0, base_stats["a_mean"], places=3)
            self.assertAlmostEqual(235 / 255.0, material_stats["b_mean"], places=3)
            self.assertTrue(any("base texture mean" in item for item in gold.evidence))
            self.assertTrue(any("B channel mean" in item for item in metal.evidence))
            self.assertTrue(any("source alpha channel" in item for item in glass.evidence))

    def test_gltf_external_audit_classifies_compact_tokens_and_color_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            document["buffers"][0]["uri"] = "triangle.bin"
            document["materials"] = [
                {
                    "name": "PaintedMetalPanel",
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.82, 0.12, 0.08, 1.0],
                        "metallicFactor": 0.75,
                        "roughnessFactor": 0.4,
                    },
                },
                {
                    "name": "CopperWire",
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.93, 0.43, 0.16, 1.0],
                        "metallicFactor": 1.0,
                        "roughnessFactor": 0.28,
                    },
                },
                {
                    "name": "FlagCloth",
                    "doubleSided": True,
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.08, 0.16, 0.26, 1.0],
                        "metallicFactor": 0.0,
                        "roughnessFactor": 0.86,
                    },
                },
                {
                    "name": "RoughBrownPanel",
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.34, 0.19, 0.08, 1.0],
                        "metallicFactor": 0.0,
                        "roughnessFactor": 0.9,
                    },
                },
                {
                    "name": "NeutralBlock",
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.46, 0.44, 0.41, 1.0],
                        "metallicFactor": 0.0,
                        "roughnessFactor": 0.82,
                    },
                },
                {
                    "name": "OrganicFaceSkin",
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.74, 0.45, 0.34, 1.0],
                        "metallicFactor": 0.0,
                        "roughnessFactor": 0.58,
                    },
                },
            ]
            primitive = document["meshes"][0]["primitives"][0]
            document["meshes"][0]["primitives"] = [
                dict(primitive, material=index)
                for index in range(len(document["materials"]))
            ]
            path = root / "materials.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)

            audit = result.external_audit
            self.assertIsNotNone(audit)
            assert audit is not None
            by_name = {item.material_name: {row.material_class for row in item.material_classes} for item in audit.material_inventory}
            painted = next(item for item in audit.material_inventory if item.material_name == "PaintedMetalPanel")
            flag = next(item for item in audit.material_inventory if item.material_name == "FlagCloth")

            self.assertIn("painted_metal", by_name["PaintedMetalPanel"])
            self.assertIn("metal", by_name["PaintedMetalPanel"])
            self.assertIn("copper", by_name["CopperWire"])
            self.assertIn("cloth", by_name["FlagCloth"])
            self.assertIn("leather", by_name["RoughBrownPanel"])
            self.assertIn("wood", by_name["RoughBrownPanel"])
            self.assertIn("stone", by_name["NeutralBlock"])
            self.assertIn("skin_organic", by_name["OrganicFaceSkin"])
            self.assertTrue(any("painted/coated token" in reason for item in painted.material_classes for reason in item.evidence))
            self.assertTrue(any("double-sided" in reason for item in flag.material_classes for reason in item.evidence))

    def test_gltf_external_audit_uses_vertex_colors_for_material_classes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            color_bytes = struct.pack(
                "<12f",
                0.90, 0.64, 0.16, 0.40,
                0.94, 0.70, 0.18, 0.55,
                0.92, 0.67, 0.20, 0.65,
            )
            color_offset = len(bin_chunk)
            bin_chunk += _pad4(color_bytes)
            color_view = len(document["bufferViews"])
            document["bufferViews"].append(
                {"buffer": 0, "byteOffset": color_offset, "byteLength": len(color_bytes), "target": 34962}
            )
            color_accessor = len(document["accessors"])
            document["accessors"].append(
                {"bufferView": color_view, "componentType": 5126, "count": 3, "type": "VEC4"}
            )
            document["buffers"][0]["uri"] = "triangle.bin"
            document["buffers"][0]["byteLength"] = len(bin_chunk)
            document["materials"][0] = {
                "name": "VertexTintedMetal",
                "pbrMetallicRoughness": {
                    "metallicFactor": 1.0,
                    "roughnessFactor": 0.32,
                },
            }
            document["meshes"][0]["primitives"][0]["attributes"]["COLOR_0"] = color_accessor
            (root / "triangle.bin").write_bytes(bin_chunk)
            path = root / "vertex_colors.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)

            audit = result.external_audit
            self.assertIsNotNone(audit)
            assert audit is not None
            inventory = audit.material_inventory[0]
            classes = {item.material_class: item for item in inventory.material_classes}

            self.assertEqual((0.92, 0.67, 0.18), inventory.vertex_color_factor)
            self.assertEqual((0.5333, 0.4), inventory.vertex_alpha)
            self.assertIn("gold", classes)
            self.assertIn("glass_crystal", classes)
            self.assertTrue(any("vertex color mean" in reason for reason in classes["gold"].evidence))
            self.assertTrue(any("vertex alpha" in reason for reason in classes["glass_crystal"].evidence))

    def test_gltf_material_extensions_webp_ao_factors_and_uv1_are_recorded(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            uv1_offset = len(bin_chunk)
            uv1_bytes = struct.pack("<6f", 0.2, 0.3, 0.8, 0.3, 0.2, 0.9)
            bin_chunk += _pad4(uv1_bytes)
            uv1_view = len(document["bufferViews"])
            document["bufferViews"].append({"buffer": 0, "byteOffset": uv1_offset, "byteLength": len(uv1_bytes), "target": 34962})
            uv1_accessor = len(document["accessors"])
            document["accessors"].append({"bufferView": uv1_view, "componentType": 5126, "count": 3, "type": "VEC2"})
            document["buffers"][0]["byteLength"] = len(bin_chunk)
            document["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_1"] = uv1_accessor
            (root / "triangle.bin").write_bytes(bin_chunk)
            base = root / "body_base.webp"
            base_image = QImage(2, 2, QImage.Format_RGBA8888)
            base_image.fill(QColor(128, 64, 255, 255))
            self.assertTrue(base_image.save(str(base), "WEBP"))
            for name in (
                "body_metallicRoughness.png",
                "body_normal.png",
                "body_ao.png",
                "body_emissive.png",
                "body_specular.png",
                "body_clearcoat.png",
                "body_sheen.png",
                "body_transmission.png",
            ):
                image = QImage(2, 2, QImage.Format_RGBA8888)
                image.fill(QColor(96, 128, 160, 255))
                self.assertTrue(image.save(str(root / name), "PNG"))
            document["buffers"][0]["uri"] = "triangle.bin"
            document["materials"][0] = {
                "name": "Layered",
                "alphaMode": "MASK",
                "alphaCutoff": 0.42,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.5, 0.25, 1.0, 1.0],
                    "baseColorTexture": {
                        "index": 0,
                        "texCoord": 1,
                        "extensions": {"KHR_texture_transform": {"scale": [1.0, 1.0]}},
                    },
                    "metallicRoughnessTexture": {"index": 1, "texCoord": 1},
                    "metallicFactor": 0.25,
                    "roughnessFactor": 0.5,
                },
                "normalTexture": {"index": 2, "texCoord": 1, "scale": 0.4},
                "occlusionTexture": {"index": 3, "texCoord": 1, "strength": 0.6},
                "emissiveTexture": {"index": 4, "texCoord": 1},
                "emissiveFactor": [0.1, 0.2, 0.3],
                "extensions": {
                    "KHR_materials_unlit": {},
                    "KHR_materials_specular": {
                        "specularFactor": 0.75,
                        "specularTexture": {"index": 5, "texCoord": 1},
                    },
                    "KHR_materials_clearcoat": {
                        "clearcoatFactor": 0.5,
                        "clearcoatTexture": {"index": 6, "texCoord": 1},
                    },
                    "KHR_materials_sheen": {
                        "sheenColorTexture": {"index": 7, "texCoord": 1},
                    },
                    "KHR_materials_transmission": {
                        "transmissionFactor": 0.2,
                        "transmissionTexture": {"index": 8, "texCoord": 1},
                    },
                },
            }
            document["textures"] = [{"source": index} for index in range(9)]
            document["images"] = [
                {"uri": "body_base.webp"},
                {"uri": "body_metallicRoughness.png"},
                {"uri": "body_normal.png"},
                {"uri": "body_ao.png"},
                {"uri": "body_emissive.png"},
                {"uri": "body_specular.png"},
                {"uri": "body_clearcoat.png"},
                {"uri": "body_sheen.png"},
                {"uri": "body_transmission.png"},
            ]
            path = root / "layered.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            mesh = preview_model.meshes[0]
            inputs = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
            slot_subtypes = {(item.slot_kind, item.semantic_subtype) for item in inputs}
            parameter_names = {
                parameter.parameter_name
                for item in inputs
                for parameter in tuple(getattr(item, "material_parameters", ()) or ())
            }

            self.assertIn((root / "body_base.webp").resolve(), result.discovered_texture_files)
            self.assertEqual("body_base.webp", Path(mesh.preview_texture_path).name)
            self.assertEqual((0.5, 0.25, 1.0), mesh.preview_texture_tint)
            self.assertEqual((), mesh.preview_texture_uv_scale)
            self.assertEqual(0.4, mesh.preview_normal_texture_strength)
            self.assertEqual(0.42, mesh.preview_native_material_overrides["alpha_threshold"])
            self.assertEqual("gltf_unlit", mesh.preview_native_material_overrides["material_shader_family"])
            self.assertIn(("occlusion", "ao"), slot_subtypes)
            self.assertIn(("specular", "specular"), slot_subtypes)
            self.assertIn(("specular", "clearcoat"), slot_subtypes)
            self.assertIn(("specular", "sheen"), slot_subtypes)
            self.assertIn(("material", "transmission"), slot_subtypes)
            self.assertIn("_metallicFactor", parameter_names)
            self.assertIn("_roughnessFactor", parameter_names)
            self.assertIn("_gltfTextureStrength_occlusion", parameter_names)
            self.assertNotIn("_gltfTexCoord_base", parameter_names)
            self.assertIn("occlusion", {slot for slot, _path in result.material_bindings[0].texture_slots})
            self.assertIn("unlit", result.material_bindings[0].pbr_workflow)
            inventory_slots = {slot.slot_kind: slot for slot in result.external_audit.material_inventory[0].texture_slots}
            self.assertEqual(0, inventory_slots["base"].texcoord)
            self.assertEqual((), inventory_slots["base"].uv_transform)
            self.assertNotIn("texcoord:1", inventory_slots["base"].evidence)
            self.assertNotIn("uv_transform", inventory_slots["base"].evidence)
            self.assertIn("TEXCOORD_1", " ".join(result.diagnostics))
            self.assertIn("KHR_materials_clearcoat", " ".join(result.diagnostics))

    def test_gltf_textureless_unlit_material_metadata_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            document["buffers"][0]["uri"] = "triangle.bin"
            (root / "triangle.bin").write_bytes(bin_chunk)
            document["materials"][0] = {
                "name": "FlatPaint",
                "alphaMode": "MASK",
                "alphaCutoff": 0.35,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.25, 0.5, 0.75, 1.0],
                    "roughnessFactor": 0.9,
                    "metallicFactor": 0.0,
                },
                "extensions": {"KHR_materials_unlit": {}},
            }
            path = root / "flat.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            mesh = preview_model.meshes[0]

            self.assertEqual("MASK", mesh.preview_alpha_mode)
            self.assertEqual((0.25, 0.5, 0.75), mesh.preview_texture_tint)
            self.assertEqual("gltf_unlit", mesh.preview_native_material_overrides["material_shader_family"])
            self.assertEqual(1.0, mesh.preview_native_material_overrides["roughness"])
            self.assertEqual(0.0, mesh.preview_native_material_overrides["specular"])
            self.assertEqual(0.35, mesh.preview_native_material_overrides["alpha_threshold"])

    def test_gltf_textureless_pbr_factors_become_native_material_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            document["buffers"][0]["uri"] = "triangle.bin"
            (root / "triangle.bin").write_bytes(bin_chunk)
            document["materials"][0] = {
                "name": "ScalarOnly",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.3, 0.4, 0.5, 1.0],
                    "roughnessFactor": 0.35,
                    "metallicFactor": 0.8,
                },
                "emissiveFactor": [0.2, 0.1, 0.0],
                "extensions": {
                    "KHR_materials_specular": {
                        "specularFactor": 0.5,
                        "specularColorFactor": [0.5, 1.0, 0.5],
                    }
                },
            }
            path = root / "scalar.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            mesh = preview_model.meshes[0]

            self.assertEqual((0.3, 0.4, 0.5), mesh.preview_texture_tint)
            self.assertAlmostEqual(0.35, mesh.preview_native_material_overrides["roughness"])
            self.assertAlmostEqual(0.8, mesh.preview_native_material_overrides["metalness"])
            self.assertAlmostEqual(0.39675, mesh.preview_native_material_overrides["specular"])
            self.assertEqual(1.0, mesh.preview_native_material_overrides["emissive_intensity"])
            self.assertEqual("#331a00", mesh.preview_native_material_overrides["emissive_color"])

    def test_obj_scene_preview_defaults_to_unflipped_texture_v(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "body.png").write_bytes(b"png")
            (root / "triangle.mtl").write_text("newmtl Body\nmap_Kd body.png\n", encoding="utf-8")
            path = root / "triangle.obj"
            path.write_text(
                "\n".join(
                    (
                        "mtllib triangle.mtl",
                        "o Triangle",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "vn 0 0 1",
                        "usemtl Body",
                        "f 1/1/1 2/2/1 3/3/1",
                        "",
                    )
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            attach_scene_preview_textures(preview_model, result, path)

            self.assertEqual("obj", result.mesh.format)
            self.assertTrue(result.mesh.has_uvs)
            self.assertIsNone(preview_model.meshes[0].preview_texture_flip_vertical)

    def test_obj_mtl_common_maps_become_preview_material_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (
                "body_base.png",
                "body_normal.png",
                "body_specular.png",
                "body_glossiness.png",
                "body_roughness.png",
                "body_metallic.png",
                "body_emissive.png",
                "body_opacity.png",
                "body_height.png",
            ):
                (root / name).write_bytes(b"png")
            (root / "triangle.mtl").write_text(
                "\n".join(
                    (
                        "newmtl Body",
                        "map_Kd body_base.png",
                        "norm body_normal.png",
                        "map_Ks body_specular.png",
                        "map_Ns body_glossiness.png",
                        "map_Pr body_roughness.png",
                        "map_Pm body_metallic.png",
                        "map_Ke body_emissive.png",
                        "map_d body_opacity.png",
                        "disp body_height.png",
                    )
                ),
                encoding="utf-8",
            )
            path = root / "triangle.obj"
            path.write_text(
                "\n".join(
                    (
                        "mtllib triangle.mtl",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "vn 0 0 1",
                        "usemtl Body",
                        "f 1/1/1 2/2/1 3/3/1",
                    )
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            mesh = preview_model.meshes[0]
            inputs = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
            slot_subtypes = {(item.slot_kind, item.semantic_subtype) for item in inputs}

            self.assertEqual("body_base.png", Path(mesh.preview_texture_path).name)
            self.assertEqual("body_normal.png", Path(mesh.preview_normal_texture_path).name)
            self.assertEqual("body_height.png", Path(mesh.preview_height_texture_path).name)
            self.assertIn(("specular", "specular"), slot_subtypes)
            self.assertIn(("glossiness", "glossiness"), slot_subtypes)
            self.assertIn(("roughness", "roughness"), slot_subtypes)
            self.assertIn(("metalness", "metallic"), slot_subtypes)
            self.assertIn(("emissive", "emissive"), slot_subtypes)
            self.assertIn(("opacity", "opacity"), slot_subtypes)

    def test_obj_mtl_slots_store_resolved_texture_paths_for_audit(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            texture = root / "body_base.png"
            Image.new("RGBA", (2, 2), (120, 80, 40, 255)).save(texture)
            (root / "triangle.mtl").write_text("newmtl Body\nmap_Kd body_base.png\n", encoding="utf-8")
            path = root / "triangle.obj"
            path.write_text(
                "\n".join(
                    (
                        "mtllib triangle.mtl",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "vn 0 0 1",
                        "usemtl Body",
                        "f 1/1/1 2/2/1 3/3/1",
                    )
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)

        resolved_texture = texture.resolve()
        mesh_slot_path = Path(result.mesh.submeshes[0].preview_texture_path)
        audit = result.external_audit
        self.assertIsNotNone(audit)
        assert audit is not None
        material_slot = audit.material_inventory[0].texture_slots[0]
        self.assertEqual(resolved_texture, mesh_slot_path)
        self.assertEqual(resolved_texture, Path(material_slot.texture_path))
        self.assertEqual((2, 2), material_slot.resolution)
        self.assertTrue(material_slot.channel_stats)

    def test_obj_mtl_huge_texture_keeps_resolution_without_channel_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "huge_base.png").write_bytes(_huge_header_png())
            (root / "triangle.mtl").write_text("newmtl Body\nmap_Kd huge_base.png\n", encoding="utf-8")
            path = root / "triangle.obj"
            path.write_text(
                "\n".join(
                    (
                        "mtllib triangle.mtl",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "vn 0 0 1",
                        "usemtl Body",
                        "f 1/1/1 2/2/1 3/3/1",
                    )
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)

        audit = result.external_audit
        self.assertIsNotNone(audit)
        assert audit is not None
        slot = audit.material_inventory[0].texture_slots[0]
        self.assertEqual((20_000, 10_000), slot.resolution)
        self.assertEqual((), slot.channel_stats)

    def test_obj_mtl_scalar_properties_become_preview_material_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "triangle.mtl").write_text(
                "\n".join(
                    (
                        "newmtl CrystalGem",
                        "Kd 0.8 0.1 0.05",
                        "Ks 0.2 0.2 0.2",
                        "Ke 1.0 0.0 0.0",
                        "Ns 500",
                        "Pr 0.25",
                        "Pm 0.0",
                        "d 0.45",
                        "Ni 1.45",
                        "illum 2",
                    )
                ),
                encoding="utf-8",
            )
            path = root / "triangle.obj"
            path.write_text(
                "\n".join(
                    (
                        "mtllib triangle.mtl",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "vn 0 0 1",
                        "usemtl CrystalGem",
                        "f 1/1/1 2/2/1 3/3/1",
                    )
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)
            submesh = result.mesh.submeshes[0]
            overrides = dict(getattr(submesh, "preview_native_material_overrides", {}) or {})

            self.assertEqual((0.8, 0.1, 0.05), submesh.preview_texture_tint)
            self.assertEqual("BLEND", submesh.preview_alpha_mode)
            self.assertAlmostEqual(0.45, submesh.preview_vertex_alpha_mean)
            self.assertAlmostEqual(0.25, overrides["roughness"])
            self.assertAlmostEqual(0.0, overrides["metalness"])
            self.assertAlmostEqual(0.2, overrides["specular"])
            self.assertEqual("#ff0000", overrides["emissive_color"])
            self.assertAlmostEqual(1.0, overrides["emissive_intensity"])

    def test_obj_base_texture_attaches_sibling_support_maps_by_filename_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (
                "blade_BaseColor.png",
                "blade_Normal.png",
                "blade_Roughness.png",
                "blade_Metallic.png",
                "blade_AO.png",
                "blade_Emissive.png",
                "blade_Height.png",
            ):
                (root / name).write_bytes(b"png")
            (root / "triangle.mtl").write_text("newmtl Blade\nmap_Kd blade_BaseColor.png\n", encoding="utf-8")
            path = root / "triangle.obj"
            path.write_text(
                "\n".join(
                    (
                        "mtllib triangle.mtl",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "vn 0 0 1",
                        "usemtl Blade",
                        "f 1/1/1 2/2/1 3/3/1",
                    )
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            mesh = preview_model.meshes[0]
            inputs = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
            slot_subtypes = {(item.slot_kind, item.semantic_subtype) for item in inputs}

            self.assertEqual("blade_BaseColor.png", Path(mesh.preview_texture_path).name)
            self.assertEqual("blade_Normal.png", Path(mesh.preview_normal_texture_path).name)
            self.assertEqual("blade_Height.png", Path(mesh.preview_height_texture_path).name)
            self.assertIn(("occlusion", "ao"), slot_subtypes)
            self.assertIn(("roughness", "roughness"), slot_subtypes)
            self.assertIn(("metalness", "metallic"), slot_subtypes)
            self.assertIn(("emissive", "emissive"), slot_subtypes)
            self.assertIn("filename fallback", " ".join(result.diagnostics))

    def test_dae_common_effect_textures_become_preview_material_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("base.png", "normal.png", "emissive.png", "specular.png", "opacity.png"):
                (root / name).write_bytes(b"png")
            path = root / "triangle.dae"
            path.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <library_images>
    <image id="baseImg"><init_from>base.png</init_from></image>
    <image id="normalImg"><init_from>normal.png</init_from></image>
    <image id="emissiveImg"><init_from>emissive.png</init_from></image>
    <image id="specularImg"><init_from>specular.png</init_from></image>
    <image id="opacityImg"><init_from>opacity.png</init_from></image>
  </library_images>
  <library_effects>
    <effect id="matFx"><profile_COMMON>
      <newparam sid="baseSurface"><surface type="2D"><init_from>baseImg</init_from></surface></newparam>
      <newparam sid="baseSampler"><sampler2D><source>baseSurface</source></sampler2D></newparam>
      <newparam sid="normalSurface"><surface type="2D"><init_from>normalImg</init_from></surface></newparam>
      <newparam sid="normalSampler"><sampler2D><source>normalSurface</source></sampler2D></newparam>
      <newparam sid="emissiveSurface"><surface type="2D"><init_from>emissiveImg</init_from></surface></newparam>
      <newparam sid="emissiveSampler"><sampler2D><source>emissiveSurface</source></sampler2D></newparam>
      <newparam sid="specularSurface"><surface type="2D"><init_from>specularImg</init_from></surface></newparam>
      <newparam sid="specularSampler"><sampler2D><source>specularSurface</source></sampler2D></newparam>
      <newparam sid="opacitySurface"><surface type="2D"><init_from>opacityImg</init_from></surface></newparam>
      <newparam sid="opacitySampler"><sampler2D><source>opacitySurface</source></sampler2D></newparam>
      <technique sid="common"><phong>
        <diffuse><texture texture="baseSampler" texcoord="UVSET0"/></diffuse>
        <emission><texture texture="emissiveSampler" texcoord="UVSET0"/></emission>
        <specular><texture texture="specularSampler" texcoord="UVSET0"/></specular>
        <transparent><texture texture="opacitySampler" texcoord="UVSET0"/></transparent>
      </phong></technique>
      <extra><technique profile="MAYA"><bump><texture texture="normalSampler" texcoord="UVSET0"/></bump></technique></extra>
    </profile_COMMON></effect>
  </library_effects>
  <library_materials><material id="Mat" name="Mat"><instance_effect url="#matFx"/></material></library_materials>
  <library_geometries><geometry id="geo" name="Triangle"><mesh>
    <source id="geo-pos"><float_array id="geo-pos-array" count="9">0 0 0 1 0 0 0 1 0</float_array><technique_common><accessor source="#geo-pos-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-norm"><float_array id="geo-norm-array" count="9">0 0 1 0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-norm-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-uv"><float_array id="geo-uv-array" count="6">0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-uv-array" count="3" stride="2"/></technique_common></source>
    <vertices id="geo-verts"><input semantic="POSITION" source="#geo-pos"/></vertices>
    <triangles material="Mat" count="1">
      <input semantic="VERTEX" source="#geo-verts" offset="0"/>
      <input semantic="NORMAL" source="#geo-norm" offset="1"/>
      <input semantic="TEXCOORD" source="#geo-uv" offset="2"/>
      <p>0 0 0 1 1 1 2 2 2</p>
    </triangles>
  </mesh></geometry></library_geometries>
  <library_visual_scenes><visual_scene id="Scene"><node id="Node"><instance_geometry url="#geo"><bind_material><technique_common><instance_material symbol="Mat" target="#Mat"/></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
""",
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            mesh = preview_model.meshes[0]
            inputs = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
            slot_subtypes = {(item.slot_kind, item.semantic_subtype) for item in inputs}

            self.assertEqual("dae", result.mesh.format)
            self.assertEqual("base.png", Path(mesh.preview_texture_path).name)
            self.assertEqual("normal.png", Path(mesh.preview_normal_texture_path).name)
            self.assertIn(("emissive", "emissive"), slot_subtypes)
            self.assertIn(("specular", "specular"), slot_subtypes)
            self.assertIn(("opacity", "opacity"), slot_subtypes)

    def test_dae_percent_encoded_image_refs_resolve_to_local_texture(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            texture_dir = root / "Textures With Spaces"
            texture_dir.mkdir()
            Image.new("RGBA", (2, 2), (220, 20, 20, 255)).save(texture_dir / "red gem.png")
            path = root / "triangle.dae"
            path.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <library_images><image id="baseImg"><init_from>Textures%20With%20Spaces/red%20gem.png</init_from></image></library_images>
  <library_effects><effect id="matFx"><profile_COMMON>
    <newparam sid="baseSurface"><surface type="2D"><init_from>baseImg</init_from></surface></newparam>
    <newparam sid="baseSampler"><sampler2D><source>baseSurface</source></sampler2D></newparam>
    <technique sid="common"><phong><diffuse><texture texture="baseSampler" texcoord="UVSET0"/></diffuse></phong></technique>
  </profile_COMMON></effect></library_effects>
  <library_materials><material id="RedGem" name="RedGem"><instance_effect url="#matFx"/></material></library_materials>
  <library_geometries><geometry id="geo" name="Triangle"><mesh>
    <source id="geo-pos"><float_array id="geo-pos-array" count="9">0 0 0 1 0 0 0 1 0</float_array><technique_common><accessor source="#geo-pos-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-norm"><float_array id="geo-norm-array" count="9">0 0 1 0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-norm-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-uv"><float_array id="geo-uv-array" count="6">0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-uv-array" count="3" stride="2"/></technique_common></source>
    <vertices id="geo-verts"><input semantic="POSITION" source="#geo-pos"/></vertices>
    <triangles material="RedGem" count="1">
      <input semantic="VERTEX" source="#geo-verts" offset="0"/>
      <input semantic="NORMAL" source="#geo-norm" offset="1"/>
      <input semantic="TEXCOORD" source="#geo-uv" offset="2"/>
      <p>0 0 0 1 1 1 2 2 2</p>
    </triangles>
  </mesh></geometry></library_geometries>
  <library_visual_scenes><visual_scene id="Scene"><node id="Node"><instance_geometry url="#geo"><bind_material><technique_common><instance_material symbol="RedGem" target="#RedGem"/></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
""",
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            mesh = preview_model.meshes[0]
            audit = result.external_audit

            self.assertEqual("red gem.png", Path(mesh.preview_texture_path).name)
            self.assertNotIn("%20", mesh.preview_texture_path)
            self.assertTrue(Path(mesh.preview_texture_path).is_file())
            self.assertIsNotNone(audit)
            assert audit is not None
            slot = audit.material_inventory[0].texture_slots[0]
            self.assertEqual((2, 2), slot.resolution)
            self.assertTrue(slot.channel_stats)
            self.assertNotIn("%20", slot.texture_path)

    def test_dae_scalar_effect_properties_become_preview_material_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "crystal_gem.dae"
            path.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <library_effects><effect id="crystalFx"><profile_COMMON>
    <technique sid="common"><phong>
      <emission><color>1 0 0 1</color></emission>
      <diffuse><color>0.8 0.1 0.05 1</color></diffuse>
      <specular><color>0.2 0.2 0.2 1</color></specular>
      <shininess><float>25</float></shininess>
      <transparent opaque="RGB_ZERO"><color>0.25 0.25 0.25 1</color></transparent>
      <transparency><float>0.5</float></transparency>
    </phong></technique>
  </profile_COMMON></effect></library_effects>
  <library_materials><material id="CrystalGem" name="CrystalGem"><instance_effect url="#crystalFx"/></material></library_materials>
  <library_geometries><geometry id="geo" name="Triangle"><mesh>
    <source id="geo-pos"><float_array id="geo-pos-array" count="9">0 0 0 1 0 0 0 1 0</float_array><technique_common><accessor source="#geo-pos-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-norm"><float_array id="geo-norm-array" count="9">0 0 1 0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-norm-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-uv"><float_array id="geo-uv-array" count="6">0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-uv-array" count="3" stride="2"/></technique_common></source>
    <vertices id="geo-verts"><input semantic="POSITION" source="#geo-pos"/></vertices>
    <triangles material="CrystalGem" count="1">
      <input semantic="VERTEX" source="#geo-verts" offset="0"/>
      <input semantic="NORMAL" source="#geo-norm" offset="1"/>
      <input semantic="TEXCOORD" source="#geo-uv" offset="2"/>
      <p>0 0 0 1 1 1 2 2 2</p>
    </triangles>
  </mesh></geometry></library_geometries>
  <library_visual_scenes><visual_scene id="Scene"><node id="Node"><instance_geometry url="#geo"><bind_material><technique_common><instance_material symbol="CrystalGem" target="#CrystalGem"/></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
""",
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)
            submesh = result.mesh.submeshes[0]
            overrides = dict(getattr(submesh, "preview_native_material_overrides", {}) or {})
            audit = result.external_audit
            self.assertIsNotNone(audit)
            assert audit is not None
            inventory = audit.material_inventory[0]
            scalar_hints = dict(inventory.scalar_hints)

            self.assertEqual("dae", result.mesh.format)
            self.assertEqual("CrystalGem", submesh.material)
            self.assertEqual((0.8, 0.1, 0.05), submesh.preview_texture_tint)
            self.assertEqual("BLEND", submesh.preview_alpha_mode)
            self.assertAlmostEqual(0.375, submesh.preview_vertex_alpha_mean)
            self.assertAlmostEqual(0.375, submesh.preview_vertex_alpha_min)
            self.assertAlmostEqual(0.75, overrides["roughness"])
            self.assertAlmostEqual(0.2, overrides["specular"])
            self.assertEqual("#ff0000", overrides["emissive_color"])
            self.assertAlmostEqual(1.0, overrides["emissive_intensity"])
            self.assertEqual("specular_glossiness", inventory.pbr_workflow)
            self.assertAlmostEqual(0.25, scalar_hints["glossiness"])
            self.assertAlmostEqual(0.2, scalar_hints["specular"])
            self.assertAlmostEqual(0.75, scalar_hints["roughness"])

    def test_dae_base_texture_attaches_sibling_support_maps_by_filename_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (
                "blade_BaseColor.png",
                "blade_Normal.png",
                "blade_Roughness.png",
                "blade_Metallic.png",
                "blade_AO.png",
                "blade_Emissive.png",
            ):
                (root / name).write_bytes(b"png")
            path = root / "triangle.dae"
            path.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <library_images><image id="baseImg"><init_from>blade_BaseColor.png</init_from></image></library_images>
  <library_effects><effect id="matFx"><profile_COMMON>
    <newparam sid="baseSurface"><surface type="2D"><init_from>baseImg</init_from></surface></newparam>
    <newparam sid="baseSampler"><sampler2D><source>baseSurface</source></sampler2D></newparam>
    <technique sid="common"><phong><diffuse><texture texture="baseSampler" texcoord="UVSET0"/></diffuse></phong></technique>
  </profile_COMMON></effect></library_effects>
  <library_materials><material id="Mat" name="Mat"><instance_effect url="#matFx"/></material></library_materials>
  <library_geometries><geometry id="geo" name="Triangle"><mesh>
    <source id="geo-pos"><float_array id="geo-pos-array" count="9">0 0 0 1 0 0 0 1 0</float_array><technique_common><accessor source="#geo-pos-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-norm"><float_array id="geo-norm-array" count="9">0 0 1 0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-norm-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-uv"><float_array id="geo-uv-array" count="6">0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-uv-array" count="3" stride="2"/></technique_common></source>
    <vertices id="geo-verts"><input semantic="POSITION" source="#geo-pos"/></vertices>
    <triangles material="Mat" count="1">
      <input semantic="VERTEX" source="#geo-verts" offset="0"/>
      <input semantic="NORMAL" source="#geo-norm" offset="1"/>
      <input semantic="TEXCOORD" source="#geo-uv" offset="2"/>
      <p>0 0 0 1 1 1 2 2 2</p>
    </triangles>
  </mesh></geometry></library_geometries>
  <library_visual_scenes><visual_scene id="Scene"><node id="Node"><instance_geometry url="#geo"><bind_material><technique_common><instance_material symbol="Mat" target="#Mat"/></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
""",
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            mesh = preview_model.meshes[0]
            inputs = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
            slot_subtypes = {(item.slot_kind, item.semantic_subtype) for item in inputs}

            self.assertEqual("blade_BaseColor.png", Path(mesh.preview_texture_path).name)
            self.assertEqual("blade_Normal.png", Path(mesh.preview_normal_texture_path).name)
            self.assertIn(("occlusion", "ao"), slot_subtypes)
            self.assertIn(("roughness", "roughness"), slot_subtypes)
            self.assertIn(("metalness", "metallic"), slot_subtypes)
            self.assertIn(("emissive", "emissive"), slot_subtypes)
            self.assertIn("filename fallback", " ".join(result.diagnostics))

    def test_browsable_external_formats_get_clear_no_dependency_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.usdz"
            path.write_bytes(b"PK\x03\x04")

            with self.assertRaisesRegex(ValueError, "browsable but not preview-importable"):
                import_scene_mesh_with_report(path)

    def test_gltf_specular_glossiness_diffuse_texture_is_base_texture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            write_valid_image(root / "blade_diffuse.jpeg")
            write_valid_image(root / "blade_normal.png")
            write_valid_image(root / "blade_specularGlossiness.png")
            document["buffers"][0]["uri"] = "triangle.bin"
            document["materials"][0] = {
                "name": "Blade",
                "extensions": {
                    "KHR_materials_pbrSpecularGlossiness": {
                        "diffuseFactor": [0.25, 0.5, 0.75, 1.0],
                        "diffuseTexture": {"index": 0},
                        "specularGlossinessTexture": {"index": 1},
                    }
                },
                "normalTexture": {"index": 2},
            }
            document["textures"] = [{"source": 0}, {"source": 1}, {"source": 2}]
            document["images"] = [
                {"uri": "blade_diffuse.jpeg"},
                {"uri": "blade_specularGlossiness.png"},
                {"uri": "blade_normal.png"},
            ]
            path = root / "triangle.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            resolved_count = attach_scene_preview_textures(preview_model, result, path)

            self.assertIn((root / "blade_diffuse.jpeg").resolve(), result.discovered_texture_files)
            self.assertIn((root / "blade_specularGlossiness.png").resolve(), result.discovered_texture_files)
            self.assertEqual((root / "blade_diffuse.jpeg").resolve().as_posix(), result.mesh.submeshes[0].texture)
            self.assertEqual((0.25, 0.5, 0.75), getattr(result.mesh.submeshes[0], "preview_color"))
            self.assertGreaterEqual(resolved_count, 3)
            self.assertEqual("blade_diffuse.jpeg", Path(preview_model.meshes[0].preview_texture_path).name)
            self.assertEqual("blade_normal.png", Path(preview_model.meshes[0].preview_normal_texture_path).name)
            self.assertEqual("blade_specularGlossiness.png", Path(preview_model.meshes[0].preview_material_texture_path).name)
            self.assertEqual("specular", preview_model.meshes[0].preview_material_texture_subtype)
            self.assertEqual("specularGlossiness", result.material_bindings[0].pbr_workflow)
            self.assertIn("specular_glossiness", {slot for slot, _path in result.material_bindings[0].texture_slots})
            self.assertIsNotNone(result.external_audit)
            inventory = result.external_audit.material_inventory[0]
            self.assertEqual("specular_glossiness", inventory.pbr_workflow)
            self.assertIn("specular_glossiness", {slot.semantic_subtype for slot in inventory.texture_slots})
            self.assertTrue(any("Specular-glossiness workflow" in warning for warning in inventory.warnings))

    def test_gltf_metallic_roughness_is_not_used_as_base_texture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            write_valid_image(root / "painted_base.png")
            write_valid_image(root / "shared_metallicRoughness.png")
            document["buffers"][0]["uri"] = "triangle.bin"
            document["materials"] = [
                {
                    "name": "Painted",
                    "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
                },
                {
                    "name": "BareMetal",
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.05, 0.05, 0.05, 1.0],
                        "metallicRoughnessTexture": {"index": 1},
                    },
                },
            ]
            document["meshes"][0]["primitives"].append(
                {
                    "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                    "indices": 3,
                    "material": 1,
                }
            )
            document["textures"] = [{"source": 0}, {"source": 1}]
            document["images"] = [
                {"uri": "painted_base.png"},
                {"uri": "shared_metallicRoughness.png"},
            ]
            path = root / "triangle.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)
            resolved_count = attach_scene_preview_textures(preview_model, result, path)

            self.assertEqual(2, len(result.mesh.submeshes))
            self.assertEqual((root / "painted_base.png").resolve().as_posix(), result.mesh.submeshes[0].texture)
            self.assertEqual("", result.mesh.submeshes[1].texture)
            self.assertEqual((0.05, 0.05, 0.05), getattr(result.mesh.submeshes[1], "preview_color"))
            self.assertIn("shared_metallicRoughness.png", getattr(result.mesh.submeshes[1], "preview_material_texture_path"))
            self.assertGreaterEqual(resolved_count, 2)
            self.assertEqual("painted_base.png", Path(preview_model.meshes[0].preview_texture_path).name)
            self.assertEqual("", preview_model.meshes[1].preview_texture_path)
            self.assertEqual("shared_metallicRoughness.png", Path(preview_model.meshes[1].preview_material_texture_path).name)
            self.assertEqual("metallic_roughness", preview_model.meshes[1].preview_material_texture_subtype)

    def test_external_model_audit_classifies_sword_and_flags_axem_character(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "Serpent-Sword.bin").write_bytes(bin_chunk)
            write_valid_image(root / "Serpent_Sword_baseColor.png")
            write_valid_image(root / "Serpent_Sword_normal.png")
            document["buffers"][0]["uri"] = "Serpent-Sword.bin"
            document["materials"][0]["name"] = "Blade"
            document["materials"][0]["pbrMetallicRoughness"] = {"baseColorTexture": {"index": 0}}
            document["materials"][0]["normalTexture"] = {"index": 1}
            document["textures"] = [{"source": 0}, {"source": 1}]
            document["images"] = [{"uri": "Serpent_Sword_baseColor.png"}, {"uri": "Serpent_Sword_normal.png"}]
            sword_path = root / "Serpent-Sword.gltf"
            sword_path.write_text(json.dumps(document), encoding="utf-8")

            sword = import_scene_mesh_with_report(sword_path)

            self.assertIsNotNone(sword.external_audit)
            self.assertEqual("sword", sword.external_audit.verified_category)
            self.assertGreaterEqual(sword.external_audit.confidence, 0.35)
            self.assertFalse(sword.external_audit.false_positive)

            axem_document = json.loads(json.dumps(document))
            axem_document["materials"][0]["name"] = "Character Body Skin Arm"
            axem_path = root / "Axem-Green-character.gltf"
            axem_path.write_text(json.dumps(axem_document), encoding="utf-8")

            axem = import_scene_mesh_with_report(axem_path)

            self.assertIsNotNone(axem.external_audit)
            self.assertTrue(axem.external_audit.false_positive)
            self.assertTrue(axem.external_audit.mixed_model)

    def test_gltf_data_uri_buffer_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_chunk, document = _triangle_payload()
            document["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(bin_chunk).decode("ascii")
            path = Path(tmp) / "triangle.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            mesh = import_scene_mesh(path)

            self.assertEqual(mesh.total_faces, 1)
            self.assertEqual(mesh.submeshes[0].material, "Body")

    def test_gltf_node_transform_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_chunk, document = _triangle_payload()
            document["buffers"][0]["uri"] = "triangle.bin"
            document["nodes"][0]["translation"] = [1.0, 2.0, 3.0]
            root = Path(tmp)
            (root / "triangle.bin").write_bytes(bin_chunk)
            path = root / "triangle.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            mesh = import_scene_mesh(path)

            self.assertEqual(mesh.bbox_min, (1.0, 2.0, 3.0))
            self.assertEqual(mesh.bbox_max, (2.0, 3.0, 3.0))

    def test_gltf_skin_weights_are_baked_to_static_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _skinned_triangle_payload()
            document["buffers"][0]["uri"] = "skinned.bin"
            (root / "skinned.bin").write_bytes(bin_chunk)
            path = root / "skinned.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")

            result = import_scene_mesh_with_report(path)
            mesh = result.mesh

            self.assertEqual(mesh.total_vertices, 3)
            self.assertEqual(mesh.bbox_min, (0.0, 5.0, 0.0))
            self.assertEqual(mesh.bbox_max, (1.0, 6.0, 0.0))
            self.assertFalse(mesh.has_bones)
            self.assertIn("Baked glTF skin weights into static geometry", " ".join(result.diagnostics))

    def test_glb_embedded_image_is_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png_bytes = valid_image_bytes()
            bin_chunk, document = _triangle_payload(image_bytes=png_bytes)
            path = Path(tmp) / "embedded.glb"
            _write_glb(path, document, bin_chunk)

            result = import_scene_mesh_with_report(path)

            self.assertEqual(len(result.extracted_embedded_files), 1)
            self.assertTrue(result.extracted_embedded_files[0].is_file())
            self.assertEqual(result.extracted_embedded_files[0].read_bytes(), png_bytes)

    def test_glb_embedded_webp_image_is_extracted_and_bound(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            webp_path = root / "source.webp"
            image = QImage(2, 2, QImage.Format_RGBA8888)
            image.fill(QColor(12, 34, 56, 255))
            self.assertTrue(image.save(str(webp_path), "WEBP"))
            webp_bytes = webp_path.read_bytes()
            bin_chunk, document = _triangle_payload(image_bytes=webp_bytes, image_mime="image/webp")
            path = root / "embedded_webp.glb"
            _write_glb(path, document, bin_chunk)

            result = import_scene_mesh_with_report(path)
            preview_model = parsed_mesh_to_preview_model(result.mesh)

            self.assertEqual(1, len(result.extracted_embedded_files))
            self.assertEqual(".webp", result.extracted_embedded_files[0].suffix.lower())
            self.assertTrue(result.extracted_embedded_files[0].is_file())
            self.assertEqual(result.extracted_embedded_files[0].read_bytes(), webp_bytes)
            self.assertEqual(result.extracted_embedded_files[0].resolve().as_posix(), result.mesh.submeshes[0].texture)
            self.assertEqual(result.extracted_embedded_files[0].resolve().as_posix(), preview_model.meshes[0].preview_texture_path)

    def test_compressed_gltf_is_rejected_with_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compressed.gltf"
            path.write_text(
                json.dumps({"asset": {"version": "2.0"}, "extensionsUsed": ["KHR_draco_mesh_compression"]}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Export an uncompressed GLB/glTF"):
                import_scene_mesh_with_report(path)

    def test_static_mapping_accepts_imported_gltf_mesh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_chunk, document = _triangle_payload()
            document["buffers"][0]["uri"] = "triangle.bin"
            root = Path(tmp)
            (root / "triangle.bin").write_bytes(bin_chunk)
            path = root / "triangle.gltf"
            path.write_text(json.dumps(document), encoding="utf-8")
            replacement = import_scene_mesh(path)
            original = ParsedMesh(
                path="original.pam",
                format="pam",
                submeshes=[SubMesh(name="Body", material="Body", vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[(0, 1, 2)])],
                total_vertices=3,
                total_faces=1,
                has_uvs=False,
            )

            mappings = suggest_static_submesh_mappings(original, replacement)

            self.assertEqual(len(mappings), 1)
            self.assertEqual(mappings[0].source_submesh_indices, [0])

    def test_local_archive_mesh_package_discovers_sidecar_and_collapsed_texture_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ModName" / "files" / "character"
            root.mkdir(parents=True)
            mesh_path = root / "cd_test_helmet.pac"
            mesh_path.write_bytes(b"not parsed in this discovery test")
            sidecar_path = root / "cd_test_helmet.pac_xml"
            texture_path = root / "iron_red_base.dds"
            material_path = root / "cd_test_helmet_mat.dds"
            sidecar_path.write_text(
                '<SkinnedMeshMaterialWrapper _subMeshName="helmet">'
                '<MaterialParameterTexture _name="_baseColorTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/iron_red_base.dds"/>'
                "</MaterialParameterTexture>"
                "</SkinnedMeshMaterialWrapper>",
                encoding="utf-16",
            )
            texture_path.write_bytes(b"DDS ")
            material_path.write_bytes(b"DDS ")
            mesh = ParsedMesh(
                path=str(mesh_path),
                format="pac",
                submeshes=[SubMesh(name="helmet", material="cd_test_helmet", texture="cd_test_helmet")],
                total_vertices=0,
                total_faces=0,
            )

            discovered = discover_local_mesh_supplemental_files(mesh_path, mesh)

            self.assertIn(".pac", SCENE_IMPORT_EXTENSIONS)
            self.assertIn(sidecar_path.resolve(), discovered)
            self.assertIn(texture_path.resolve(), discovered)
            self.assertIn(material_path.resolve(), discovered)

    def test_local_archive_mesh_package_discovers_crimson_companion_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ModName" / "files" / "character" / "model"
            prefab_root = Path(tmp) / "ModName" / "files" / "character" / "bin__" / "prefab"
            root.mkdir(parents=True)
            prefab_root.mkdir(parents=True)
            mesh_path = root / "cd_test_sword.pac"
            mesh_path.write_bytes(b"not parsed in this discovery test")
            meshinfo_path = root / "cd_test_sword.meshinfo"
            material_path = root / "cd_test_sword.material"
            prefab_path = prefab_root / "cd_test_sword.prefab"
            animation_meta = root / "cd_test_sword.paa_metabin"
            skeleton_path = root / "cd_test_sword.pab"
            for path in (meshinfo_path, material_path, prefab_path, animation_meta, skeleton_path):
                path.write_bytes(b"\x04\x00\x00\x00test")

            discovered = discover_local_mesh_supplemental_files(mesh_path)

            self.assertIn(".pab", SCENE_COMPANION_SOURCE_EXTENSIONS)
            self.assertIn(".prefab", SCENE_COMPANION_SOURCE_EXTENSIONS)
            self.assertIn(meshinfo_path.resolve(), discovered)
            self.assertIn(material_path.resolve(), discovered)
            self.assertIn(prefab_path.resolve(), discovered)
            self.assertIn(animation_meta.resolve(), discovered)
            self.assertIn(skeleton_path.resolve(), discovered)


if __name__ == "__main__":
    unittest.main()
