import base64
import json
import struct
import tempfile
import unittest
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


def _pad4(data: bytes) -> bytes:
    return data + (b"\x00" * ((4 - (len(data) % 4)) % 4))


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
            self.assertIs(False, preview_model.meshes[0].preview_texture_flip_vertical)

    def test_gltf_external_buffer_and_texture_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            (root / "body_base.png").write_bytes(b"png")
            (root / "body_normal.png").write_bytes(b"png")
            (root / "body_metallic_roughness.png").write_bytes(b"png")
            (root / "body_emissive.png").write_bytes(b"png")
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
            self.assertIs(False, preview_model.meshes[0].preview_texture_flip_vertical)
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
            self.assertIs(False, preview_model.meshes[0].preview_texture_flip_vertical)

    def test_gltf_specular_glossiness_diffuse_texture_is_base_texture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            (root / "blade_diffuse.jpeg").write_bytes(b"jpeg")
            (root / "blade_normal.png").write_bytes(b"png")
            (root / "blade_specularGlossiness.png").write_bytes(b"png")
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

    def test_gltf_metallic_roughness_is_not_used_as_base_texture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_chunk, document = _triangle_payload()
            (root / "triangle.bin").write_bytes(bin_chunk)
            (root / "painted_base.png").write_bytes(b"png")
            (root / "shared_metallicRoughness.png").write_bytes(b"png")
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
            (root / "Serpent_Sword_baseColor.png").write_bytes(b"png")
            (root / "Serpent_Sword_normal.png").write_bytes(b"png")
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
            png_bytes = b"\x89PNG\r\n\x1a\nfake"
            bin_chunk, document = _triangle_payload(image_bytes=png_bytes)
            path = Path(tmp) / "embedded.glb"
            _write_glb(path, document, bin_chunk)

            result = import_scene_mesh_with_report(path)

            self.assertEqual(len(result.extracted_embedded_files), 1)
            self.assertTrue(result.extracted_embedded_files[0].is_file())
            self.assertEqual(result.extracted_embedded_files[0].read_bytes(), png_bytes)

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
            for path in (meshinfo_path, material_path, prefab_path, animation_meta):
                path.write_bytes(b"\x04\x00\x00\x00test")

            discovered = discover_local_mesh_supplemental_files(mesh_path)

            self.assertIn(".prefab", SCENE_COMPANION_SOURCE_EXTENSIONS)
            self.assertIn(meshinfo_path.resolve(), discovered)
            self.assertIn(material_path.resolve(), discovered)
            self.assertIn(prefab_path.resolve(), discovered)
            self.assertIn(animation_meta.resolve(), discovered)


if __name__ == "__main__":
    unittest.main()
