from __future__ import annotations

import contextlib
import io
import json
import subprocess
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from PIL import Image

from cdmw.core.external_model_audit import (
    build_external_model_audit_catalogue,
    write_external_model_audit_catalogue,
)
from cdmw.core.external_model_audit_check import check_external_model_audit_report
from cdmw.core.model_catalogue import scan_local_model_files, zip_importable_member_refs
from cdmw.modding.mesh_native_core import find_native_mesh_core_binary
from tools.audit_external_model_catalogue import main as audit_catalogue_main
from tools.check_external_model_audit import main as check_external_model_audit_main


def _pad4(data: bytes) -> bytes:
    return data + (b"\x00" * ((4 - (len(data) % 4)) % 4))


def _write_png(path: Path, color: tuple[int, int, int, int]) -> None:
    Image.new("RGBA", (2, 2), color).save(path)


def _write_huge_header_png(path: Path, *, width: int = 20_000, height: int = 10_000) -> None:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b""))


def _write_dds(path: Path, *, width: int = 4, height: int = 4) -> None:
    header = bytearray(124)
    struct.pack_into("<I", header, 0, 124)
    struct.pack_into("<I", header, 4, 0x0002100F)
    struct.pack_into("<I", header, 8, height)
    struct.pack_into("<I", header, 12, width)
    struct.pack_into("<I", header, 20, 1)
    struct.pack_into("<I", header, 24, 1)
    struct.pack_into("<I", header, 72, 32)
    struct.pack_into("<I", header, 76, 0x4)
    header[80:84] = b"DXT1"
    path.write_bytes(b"DDS " + bytes(header) + b"\x00" * 128)


def _write_triangle_gltf(path: Path, *, missing_normal: bool = False) -> None:
    root = path.parent
    chunks: list[bytes] = []
    buffer_views: list[dict[str, object]] = []

    def add_view(data: bytes, target: int = 0) -> int:
        offset = sum(len(chunk) for chunk in chunks)
        chunks.append(_pad4(data))
        view: dict[str, object] = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    position_view = add_view(struct.pack("<9f", 0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 1.0, 0.0), 34962)
    normal_view = add_view(struct.pack("<9f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0), 34962)
    uv_view = add_view(struct.pack("<6f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0), 34962)
    index_view = add_view(struct.pack("<3H", 0, 1, 2), 34963)
    bin_chunk = b"".join(chunks)
    (root / "gold.bin").write_bytes(bin_chunk)
    _write_png(root / "gold_base.png", (220, 170, 40, 255))
    _write_png(root / "gold_metallicRoughness.png", (20, 60, 240, 255))
    if not missing_normal:
        _write_png(root / "gold_normal.png", (128, 128, 255, 255))

    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "gold.bin", "byteLength": len(bin_chunk)}],
        "bufferViews": buffer_views,
        "accessors": [
            {"bufferView": position_view, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": normal_view, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": uv_view, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": index_view, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "materials": [
            {
                "name": "Gold Metal",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 0.72, 0.18, 1.0],
                    "baseColorTexture": {"index": 0},
                    "metallicRoughnessTexture": {"index": 1},
                    "metallicFactor": 1.0,
                    "roughnessFactor": 0.2,
                },
                "normalTexture": {"index": 2},
            }
        ],
        "textures": [{"source": 0}, {"source": 1}, {"source": 2}],
        "images": [
            {"uri": "gold_base.png"},
            {"uri": "gold_metallicRoughness.png"},
            {"uri": "missing_normal.png" if missing_normal else "gold_normal.png"},
        ],
        "meshes": [
            {
                "name": "GoldBlade",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                        "indices": 3,
                        "material": 0,
                    }
                ],
            }
        ],
        "nodes": [{"name": "BladeNode", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _write_triangle_dae_with_base_texture(path: Path, image_reference: str) -> None:
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <library_images><image id="baseImg"><init_from>{image_reference}</init_from></image></library_images>
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


def _write_triangle_dae_with_diffuse_color(path: Path, material_name: str = "Color_I22") -> None:
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <library_effects><effect id="matFx"><profile_COMMON>
    <technique sid="common"><phong><diffuse><color>0.6 0.42 0.18 1</color></diffuse></phong></technique>
  </profile_COMMON></effect></library_effects>
  <library_materials><material id="{material_name}" name="{material_name}"><instance_effect url="#matFx"/></material></library_materials>
  <library_geometries><geometry id="geo" name="Triangle"><mesh>
    <source id="geo-pos"><float_array id="geo-pos-array" count="9">0 0 0 1 0 0 0 1 0</float_array><technique_common><accessor source="#geo-pos-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-norm"><float_array id="geo-norm-array" count="9">0 0 1 0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-norm-array" count="3" stride="3"/></technique_common></source>
    <source id="geo-uv"><float_array id="geo-uv-array" count="6">0 0 1 0 0 1</float_array><technique_common><accessor source="#geo-uv-array" count="3" stride="2"/></technique_common></source>
    <vertices id="geo-verts"><input semantic="POSITION" source="#geo-pos"/></vertices>
    <triangles material="{material_name}" count="1">
      <input semantic="VERTEX" source="#geo-verts" offset="0"/>
      <input semantic="NORMAL" source="#geo-norm" offset="1"/>
      <input semantic="TEXCOORD" source="#geo-uv" offset="2"/>
      <p>0 0 0 1 1 1 2 2 2</p>
    </triangles>
  </mesh></geometry></library_geometries>
  <library_visual_scenes><visual_scene id="Scene"><node id="Node"><instance_geometry url="#geo"><bind_material><technique_common><instance_material symbol="{material_name}" target="#{material_name}"/></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
""",
        encoding="utf-8",
    )


def _write_spec_gloss_gltf(path: Path) -> None:
    root = path.parent
    chunks: list[bytes] = []
    buffer_views: list[dict[str, object]] = []

    def add_view(data: bytes, target: int = 0) -> int:
        offset = sum(len(chunk) for chunk in chunks)
        chunks.append(_pad4(data))
        view: dict[str, object] = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    position_view = add_view(struct.pack("<9f", 0.0, 0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 1.0, 0.0), 34962)
    normal_view = add_view(struct.pack("<9f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0), 34962)
    uv_view = add_view(struct.pack("<6f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0), 34962)
    index_view = add_view(struct.pack("<3H", 0, 1, 2), 34963)
    bin_chunk = b"".join(chunks)
    (root / "blade.bin").write_bytes(bin_chunk)
    _write_png(root / "blade_diffuse.png", (170, 120, 60, 255))
    _write_png(root / "blade_specularGlossiness.png", (200, 180, 160, 220))
    document = {
        "asset": {"version": "2.0"},
        "extensionsUsed": ["KHR_materials_pbrSpecularGlossiness"],
        "buffers": [{"uri": "blade.bin", "byteLength": len(bin_chunk)}],
        "bufferViews": buffer_views,
        "accessors": [
            {"bufferView": position_view, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": normal_view, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": uv_view, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": index_view, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "materials": [
            {
                "name": "SpecGloss Blade",
                "extensions": {
                    "KHR_materials_pbrSpecularGlossiness": {
                        "diffuseTexture": {"index": 0},
                        "specularGlossinessTexture": {"index": 1},
                        "specularFactor": [0.8, 0.7, 0.6],
                        "glossinessFactor": 0.75,
                    }
                },
            }
        ],
        "textures": [{"source": 0}, {"source": 1}],
        "images": [{"uri": "blade_diffuse.png"}, {"uri": "blade_specularGlossiness.png"}],
        "meshes": [
            {
                "name": "SpecGlossBlade",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                        "indices": 3,
                        "material": 0,
                    }
                ],
            }
        ],
        "nodes": [{"name": "BladeNode", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    path.write_text(json.dumps(document), encoding="utf-8")


class ExternalModelAuditCatalogueTests(unittest.TestCase):
    def _require_native_mesh_core(self) -> None:
        """Skip when `cdmw_mesh_core` is not built.

        Auditing an importable model bakes its UVs and generates MikkTSpace
        tangents, which is a native operation with no Python fallback. Without
        the core every model comes back `failed` with a tangent warning, so the
        catalogue under assertion is empty rather than wrong.
        """

        if find_native_mesh_core_binary() is None:
            self.skipTest("cdmw_mesh_core is not built")

    def test_catalogue_reports_material_inventory_missing_refs_and_unsupported_fbx(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_triangle_gltf(root / "gold_sword.gltf", missing_normal=True)
            (root / "legacy.fbx").write_bytes(b"fbx")
            _write_png(root / "legacy_gold_metal_base.png", (230, 180, 40, 255))
            (root / "legacy_normal.ktx2").write_bytes(b"\xabKTX 20\xbb\r\n\x1a\n")

            report = build_external_model_audit_catalogue([root])

        summary = report["summary"]
        rows = {Path(str(row["path"])).name: row for row in report["models"]}
        gltf_row = rows["gold_sword.gltf"]
        fbx_row = rows["legacy.fbx"]
        inventory = gltf_row["material_inventory"][0]
        fbx_inventory = fbx_row["material_inventory"][0]
        slots = {slot["slot_kind"]: slot for slot in inventory["texture_slots"]}
        fbx_slots = {slot["slot_kind"]: slot for slot in fbx_inventory["texture_slots"]}
        classes = {item["material_class"] for item in inventory["material_classes"]}
        fbx_classes = {item["material_class"] for item in fbx_inventory["material_classes"]}
        channel_diagnostics = {item["code"] for item in inventory["channel_diagnostics"]}
        fbx_channel_diagnostics = {item["code"] for item in fbx_inventory["channel_diagnostics"]}

        self.assertEqual(2, summary["total_models"])
        self.assertEqual(1, summary["audited_models"])
        self.assertEqual(1, summary["unsupported_models"])
        self.assertEqual(1, summary["missing_texture_refs"])
        self.assertEqual(2, summary["source_channel_profile_rows"])
        self.assertEqual(1, summary["material_section_rows"])
        self.assertEqual(3, summary["section_vertex_count"])
        self.assertEqual(1, summary["section_face_count"])
        self.assertEqual(0, summary["sections_missing_uvs"])
        self.assertEqual(0, summary["sections_missing_normals"])
        self.assertEqual(2, summary["source_detected_channel_counts"]["base_color"])
        self.assertEqual(2, summary["source_detected_channel_counts"]["normal"])
        self.assertEqual(1, summary["source_detected_channel_counts"]["roughness"])
        self.assertEqual(1, summary["source_detected_channel_counts"]["metalness"])
        self.assertEqual(2, summary["source_missing_channel_counts"]["emissive"])
        self.assertEqual(1, summary["source_missing_channel_counts"]["roughness"])
        self.assertEqual(1, summary["source_missing_channel_counts"]["metalness"])
        self.assertEqual(2, summary["source_channel_diagnostic_counts"]["source_missing_emissive"])
        self.assertEqual(1, summary["source_channel_diagnostic_counts"]["source_missing_roughness_metalness"])
        self.assertEqual("audited", gltf_row["audit_status"])
        self.assertEqual("browsable_unsupported", fbx_row["audit_status"])
        self.assertFalse(fbx_row["import_supported"])
        self.assertEqual(0, inventory["material_index"])
        self.assertEqual("Gold Metal", inventory["material_name"])
        self.assertEqual("metallic_roughness", inventory["pbr_workflow"])
        self.assertEqual(1.0, inventory["scalar_hints"]["metalness"])
        self.assertEqual(1, inventory["section_count"])
        section = inventory["sections"][0]
        self.assertEqual(0, section["section_index"])
        self.assertEqual("BladeNode", section["section_name"])
        self.assertEqual("Gold Metal", section["material_name"])
        self.assertEqual(3, section["vertex_count"])
        self.assertEqual(1, section["face_count"])
        self.assertTrue(section["has_uvs"])
        self.assertTrue(section["has_normals"])
        self.assertTrue(section["has_tangents"])
        self.assertFalse(section["has_skinning"])
        self.assertEqual((0,), section["texture_texcoord_sets"])
        self.assertEqual((0.0, 0.0, 0.0), section["bounds_min"])
        self.assertEqual((5.0, 1.0, 0.0), section["bounds_max"])
        self.assertIn("base_color", inventory["detected_channels"])
        self.assertIn("roughness", inventory["detected_channels"])
        self.assertIn("metalness", inventory["detected_channels"])
        self.assertIn("emissive", inventory["missing_channels"])
        self.assertIn("source_missing_emissive", channel_diagnostics)
        self.assertIn("base", slots)
        self.assertIn("material", slots)
        self.assertIn("normal", slots)
        self.assertIn("missing_normal.png", gltf_row["missing_texture_refs"][0])
        self.assertIn("gold", classes)
        self.assertIn("metal", classes)
        self.assertEqual(-1, fbx_inventory["material_index"])
        self.assertEqual("legacy", fbx_inventory["material_name"])
        self.assertEqual("filename_only", fbx_slots["base"]["confidence"])
        self.assertEqual((2, 2), fbx_slots["base"]["resolution"])
        self.assertIn("base_color", fbx_inventory["detected_channels"])
        self.assertIn("normal", fbx_inventory["detected_channels"])
        self.assertIn("roughness", fbx_inventory["missing_channels"])
        self.assertIn("metalness", fbx_inventory["missing_channels"])
        self.assertIn("source_missing_roughness_metalness", fbx_channel_diagnostics)
        self.assertTrue(fbx_slots["normal"]["diagnostic_only"])
        self.assertEqual("filename_only_diagnostic", fbx_slots["normal"]["confidence"])
        self.assertIn("diagnostic_only_texture_format", fbx_slots["normal"]["evidence"])
        self.assertIn("gold", fbx_classes)
        self.assertIn("metal", fbx_classes)
        self.assertIn("base", {item["slot_guess"] for item in fbx_row["companion_textures"]})
        ktx_row = next(item for item in fbx_row["companion_textures"] if item["extension"] == ".ktx2")
        self.assertEqual("normal", ktx_row["slot_guess"])
        self.assertTrue(ktx_row["diagnostic_only"])
        self.assertTrue(fbx_row["warnings"])

    def test_catalogue_treats_spec_gloss_as_derived_material_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_spec_gloss_gltf(root / "spec_gloss_blade.gltf")

            report = build_external_model_audit_catalogue([root])

        inventory = report["models"][0]["material_inventory"][0]
        profile = inventory["channel_profile"]
        diagnostic_codes = {row["code"] for row in inventory["channel_diagnostics"]}
        self.assertEqual("specular_glossiness", inventory["pbr_workflow"])
        self.assertIn("specular", inventory["detected_channels"])
        self.assertIn("glossiness", inventory["detected_channels"])
        self.assertIn("roughness", inventory["detected_channels"])
        self.assertIn("metalness", inventory["detected_channels"])
        self.assertEqual(("metalness", "roughness"), profile["derived_channels"])
        self.assertNotIn("roughness", inventory["missing_channels"])
        self.assertNotIn("metalness", inventory["missing_channels"])
        self.assertIn("source_spec_gloss_derived_material_channels", diagnostic_codes)
        self.assertNotIn("source_missing_roughness_metalness", diagnostic_codes)
        self.assertEqual(1, report["summary"]["source_detected_channel_counts"]["roughness"])
        self.assertEqual(1, report["summary"]["source_detected_channel_counts"]["metalness"])

    def test_catalogue_flags_suspicious_source_texture_slot_routing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "misrouted_blade.gltf"
            _write_triangle_gltf(path)
            _write_png(root / "blade_specularGlossiness.png", (210, 190, 170, 225))
            _write_png(root / "blade_base.png", (180, 50, 30, 255))
            document = json.loads(path.read_text(encoding="utf-8"))
            document["materials"][0] = {
                "name": "Misrouted Blade",
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.7,
                },
                "emissiveTexture": {"index": 1},
                "emissiveFactor": [1.0, 1.0, 1.0],
            }
            document["textures"] = [{"source": 0}, {"source": 1}]
            document["images"] = [
                {"uri": "blade_specularGlossiness.png"},
                {"uri": "blade_base.png"},
            ]
            path.write_text(json.dumps(document), encoding="utf-8")

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        inventory = report["models"][0]["material_inventory"][0]
        diagnostic_codes = {row["code"] for row in inventory["channel_diagnostics"]}
        check_diagnostics = check["counts"]["source_channel_diagnostics"]

        self.assertIn("source_spec_gloss_texture_bound_as_base", diagnostic_codes)
        self.assertIn("source_base_texture_bound_as_emissive", diagnostic_codes)
        self.assertEqual(1, report["summary"]["source_channel_diagnostic_counts"]["source_spec_gloss_texture_bound_as_base"])
        self.assertEqual(1, report["summary"]["source_channel_diagnostic_counts"]["source_base_texture_bound_as_emissive"])
        self.assertEqual(1, check_diagnostics["source_spec_gloss_texture_bound_as_base"])
        self.assertEqual(1, check_diagnostics["source_base_texture_bound_as_emissive"])
        self.assertEqual(2, check["counts"]["source_texture_route_mismatches"])
        self.assertIn("source_texture_route_mismatch", check["risk_flags"])
        self.assertIn("source_texture_route_mismatch", check["allowed_risk_flags"])
        self.assertNotIn("source_texture_route_mismatch", check["review_risk_flags"])

    def test_catalogue_treats_pbr_scalars_as_roughness_metalness_evidence(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "scalar_blade.gltf"
            _write_triangle_gltf(path)
            for name in ("gold_base.png", "gold_metallicRoughness.png", "gold_normal.png"):
                try:
                    (root / name).unlink()
                except FileNotFoundError:
                    pass
            document = json.loads(path.read_text(encoding="utf-8"))
            document["materials"][0] = {
                "name": "Scalar Bronze",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.75, 0.45, 0.2, 1.0],
                    "metallicFactor": 0.8,
                    "roughnessFactor": 0.35,
                },
            }
            document.pop("textures", None)
            document.pop("images", None)
            path.write_text(json.dumps(document), encoding="utf-8")

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        inventory = report["models"][0]["material_inventory"][0]
        self.assertIn("roughness_scalar", inventory["detected_channels"])
        self.assertIn("metalness_scalar", inventory["detected_channels"])
        self.assertNotIn("roughness", inventory["missing_channels"])
        self.assertNotIn("metalness", inventory["missing_channels"])
        self.assertEqual(0, report["summary"]["materials_missing_roughness_metalness_diagnostics"])
        self.assertEqual(1, check["counts"]["materials_without_texture_slots"])
        self.assertEqual(0, check["counts"]["materials_missing_texture_facts"])
        self.assertNotIn("missing_texture_slot_facts", check["risk_flags"])

    def test_catalogue_marks_color_only_dae_as_legacy_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_triangle_dae_with_diffuse_color(root / "legacy_color.dae")

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        inventory = report["models"][0]["material_inventory"][0]
        diagnostic_codes = {row["code"] for row in inventory["channel_diagnostics"]}
        self.assertEqual("legacy_fixed_function", inventory["pbr_workflow"])
        self.assertIn("base_color_scalar", inventory["detected_channels"])
        self.assertIn("source_legacy_fixed_function_workflow", diagnostic_codes)
        self.assertEqual(1, report["summary"]["pbr_workflow_counts"]["legacy_fixed_function"])
        self.assertEqual(0, check["counts"]["materials_missing_workflow"])
        self.assertNotIn("missing_pbr_workflow", check["risk_flags"])

    def test_catalogue_treats_alpha_warning_as_alpha_diagnostic_evidence(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "transparent_blade.gltf"
            _write_triangle_gltf(path)
            document = json.loads(path.read_text(encoding="utf-8"))
            document["materials"][0]["alphaMode"] = "BLEND"
            path.write_text(json.dumps(document), encoding="utf-8")

            report = build_external_model_audit_catalogue([root])

        self.assertEqual(
            1,
            report["summary"]["source_channel_diagnostic_counts"]["source_alpha_without_opacity_texture"],
        )
        self.assertEqual(0, report["summary"]["materials_missing_alpha_diagnostics"])

    def test_catalogue_records_glass_class_alpha_intent_without_opacity_evidence(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "translucent_glass_panel.gltf"
            _write_triangle_gltf(path)
            document = json.loads(path.read_text(encoding="utf-8"))
            document["materials"][0]["name"] = "Translucent_Glass_Panel"
            path.write_text(json.dumps(document), encoding="utf-8")

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        inventory = report["models"][0]["material_inventory"][0]
        diagnostic_codes = {row["code"] for row in inventory["channel_diagnostics"]}
        classes = {row["material_class"] for row in inventory["material_classes"]}
        self.assertIn("glass_crystal", classes)
        self.assertIn("source_alpha_intent_without_opacity_evidence", diagnostic_codes)
        self.assertEqual(0, report["summary"]["materials_missing_alpha_diagnostics"])
        self.assertNotIn("missing_alpha_diagnostics", check["risk_flags"])

    def test_catalogue_reads_obj_mtl_scalar_material_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "crystal_gem.mtl").write_text(
                "\n".join(
                    (
                        "newmtl CrystalGem",
                        "Kd 0.8 0.1 0.05",
                        "Ke 1.0 0.0 0.0",
                        "Pr 0.25",
                        "Pm 0.0",
                        "d 0.45",
                    )
                ),
                encoding="utf-8",
            )
            (root / "crystal_gem.obj").write_text(
                "\n".join(
                    (
                        "mtllib crystal_gem.mtl",
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

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        inventory = report["models"][0]["material_inventory"][0]
        classes = {item["material_class"] for item in inventory["material_classes"]}
        diagnostic_codes = {row["code"] for row in inventory["channel_diagnostics"]}
        self.assertEqual("audited", report["models"][0]["audit_status"])
        self.assertEqual("CrystalGem", inventory["material_name"])
        self.assertEqual("metallic_roughness", inventory["pbr_workflow"])
        self.assertEqual((0.8, 0.1, 0.05), tuple(inventory["color_factor"]))
        self.assertEqual((0.45, 0.45), tuple(inventory["vertex_alpha"]))
        self.assertIn("base_color_scalar", inventory["detected_channels"])
        self.assertIn("roughness_scalar", inventory["detected_channels"])
        self.assertIn("metalness_scalar", inventory["detected_channels"])
        self.assertIn("emissive_scalar", inventory["detected_channels"])
        self.assertIn("opacity_scalar", inventory["detected_channels"])
        self.assertNotIn("roughness", inventory["missing_channels"])
        self.assertNotIn("metalness", inventory["missing_channels"])
        self.assertNotIn("emissive", inventory["missing_channels"])
        self.assertIn("source_vertex_alpha_opacity", diagnostic_codes)
        self.assertIn("glass_crystal", classes)
        self.assertNotIn("missing_alpha_diagnostics", check["risk_flags"])
        self.assertNotIn("missing_emissive_diagnostics", check["risk_flags"])
        self.assertEqual(0, report["summary"]["materials_missing_roughness_metalness_diagnostics"])

    def test_catalogue_reads_dae_effect_scalar_material_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "crystal_gem.dae").write_text(
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

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        inventory = report["models"][0]["material_inventory"][0]
        profile = inventory["channel_profile"]
        classes = {item["material_class"] for item in inventory["material_classes"]}
        diagnostic_codes = {row["code"] for row in inventory["channel_diagnostics"]}
        self.assertEqual("audited", report["models"][0]["audit_status"])
        self.assertEqual("CrystalGem", inventory["material_name"])
        self.assertEqual("specular_glossiness", inventory["pbr_workflow"])
        self.assertEqual((0.8, 0.1, 0.05), tuple(inventory["color_factor"]))
        self.assertEqual((0.375, 0.375), tuple(inventory["vertex_alpha"]))
        self.assertIn("base_color_scalar", inventory["detected_channels"])
        self.assertIn("specular_scalar", inventory["detected_channels"])
        self.assertIn("glossiness_scalar", inventory["detected_channels"])
        self.assertIn("roughness_scalar", inventory["detected_channels"])
        self.assertIn("metalness", inventory["detected_channels"])
        self.assertIn("emissive_scalar", inventory["detected_channels"])
        self.assertIn("opacity_scalar", inventory["detected_channels"])
        self.assertEqual(("metalness", "roughness"), profile["derived_channels"])
        self.assertNotIn("roughness", inventory["missing_channels"])
        self.assertNotIn("metalness", inventory["missing_channels"])
        self.assertNotIn("emissive", inventory["missing_channels"])
        self.assertIn("source_spec_gloss_derived_material_channels", diagnostic_codes)
        self.assertIn("source_vertex_alpha_opacity", diagnostic_codes)
        self.assertIn("glass_crystal", classes)
        self.assertNotIn("missing_alpha_diagnostics", check["risk_flags"])
        self.assertNotIn("missing_emissive_diagnostics", check["risk_flags"])
        self.assertEqual(0, report["summary"]["materials_missing_roughness_metalness_diagnostics"])

    def test_catalogue_treats_base_texture_alpha_as_opacity_evidence(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_triangle_gltf(root / "transparent_base.gltf")
            _write_png(root / "gold_base.png", (220, 170, 40, 96))

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        inventory = report["models"][0]["material_inventory"][0]
        diagnostic_codes = {row["code"] for row in inventory["channel_diagnostics"]}
        self.assertIn("opacity", inventory["detected_channels"])
        self.assertIn("source_alpha_from_texture_channel", diagnostic_codes)
        self.assertEqual(1, report["summary"]["source_channel_diagnostic_counts"]["source_alpha_from_texture_channel"])
        self.assertEqual(0, report["summary"]["materials_missing_alpha_diagnostics"])
        self.assertNotIn("missing_alpha_diagnostics", check["risk_flags"])

    def test_catalogue_treats_roughness_alpha_as_technical_channel_not_transparency(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_triangle_gltf(root / "packed_roughness.gltf")
            _write_png(root / "gold_metallicRoughness.png", (20, 60, 240, 64))

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        inventory = report["models"][0]["material_inventory"][0]
        diagnostic_codes = {row["code"] for row in inventory["channel_diagnostics"]}
        self.assertNotIn("opacity", inventory["detected_channels"])
        self.assertIn("source_packed_a_channel_technical", diagnostic_codes)
        self.assertEqual(1, report["summary"]["source_channel_diagnostic_counts"]["source_packed_a_channel_technical"])
        self.assertEqual(0, report["summary"]["materials_missing_alpha_diagnostics"])
        self.assertNotIn("missing_alpha_diagnostics", check["risk_flags"])

    def test_catalogue_report_can_be_written_as_json(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_triangle_gltf(root / "gold_sword.gltf")
            report = build_external_model_audit_catalogue([root])
            output = write_external_model_audit_catalogue(report, root / "audit.json")

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual("external_model_audit_catalogue", payload["tool"])
        self.assertEqual(1, payload["summary"]["audited_models"])

    def test_cli_writes_audit_json_for_explicit_root(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_triangle_gltf(root / "gold_sword.gltf")
            out_json = root / "audit.json"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = audit_catalogue_main(
                    ["--root", str(root), "--out-json", str(out_json), "--max-files", "5"]
                )

            payload = json.loads(out_json.read_text(encoding="utf-8"))
            printed = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertEqual("external_model_audit_catalogue", payload["tool"])
        self.assertEqual(1, payload["summary"]["audited_models"])
        self.assertEqual(str(out_json), printed["output"])
        self.assertEqual(1, printed["summary"]["source_channel_profile_rows"])

    def test_catalogue_summary_counts_texture_facts_alpha_and_emissive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "glass_panel.fbx").write_bytes(b"fbx")
            _write_png(root / "glass_panel_base.png", (80, 120, 160, 255))
            _write_png(root / "glass_panel_opacity.png", (255, 255, 255, 128))
            _write_png(root / "glass_panel_emissive.png", (20, 80, 255, 255))
            (root / "glass_panel_normal.ktx2").write_bytes(b"\xabKTX 20\xbb\r\n\x1a\n")

            report = build_external_model_audit_catalogue([root])

        summary = report["summary"]
        self.assertEqual(3, summary["texture_format_counts"]["png"])
        self.assertEqual(1, summary["texture_format_counts"]["ktx2"])
        self.assertEqual(2, summary["texture_color_space_counts"]["srgb"])
        self.assertEqual(2, summary["texture_color_space_counts"]["linear"])
        self.assertEqual(3, summary["textures_with_resolution"])
        self.assertEqual(1, summary["textures_missing_resolution"])
        self.assertEqual(3, summary["textures_with_channel_stats"])
        self.assertEqual(1, summary["textures_missing_channel_stats"])
        self.assertEqual(1, summary["diagnostic_only_texture_slots"])
        self.assertEqual(1, summary["alpha_materials"])
        self.assertEqual(1, summary["emissive_materials"])

    def test_catalogue_reads_companion_dds_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "steel_panel.fbx").write_bytes(b"fbx")
            _write_dds(root / "steel_panel_base.dds", width=16, height=8)

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        row = report["models"][0]
        slot = row["material_inventory"][0]["texture_slots"][0]
        stats = dict(slot["channel_stats"])
        self.assertEqual("dds", slot["image_format"])
        self.assertEqual((16, 8), slot["resolution"])
        self.assertEqual(0.0, stats["r_mean"])
        self.assertEqual(1.0, stats["a_mean"])
        self.assertEqual(1, report["summary"]["textures_with_resolution"])
        self.assertEqual(0, report["summary"]["textures_missing_resolution"])
        self.assertEqual(1, report["summary"]["textures_with_channel_stats"])
        self.assertEqual(0, report["summary"]["textures_missing_channel_stats"])
        self.assertNotIn("texture_missing_channel_stats", check["risk_flags"])

    def test_catalogue_keeps_huge_texture_resolution_without_channel_stats_decode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "huge_banner.fbx").write_bytes(b"fbx")
            _write_huge_header_png(root / "huge_banner_base.png")

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        slot = report["models"][0]["material_inventory"][0]["texture_slots"][0]
        self.assertEqual((20_000, 10_000), tuple(slot["resolution"]))
        self.assertEqual((), tuple(slot["channel_stats"]))
        self.assertEqual(1, report["summary"]["textures_with_resolution"])
        self.assertEqual(0, report["summary"]["textures_missing_resolution"])
        self.assertEqual(1, report["summary"]["textures_missing_channel_stats"])
        self.assertNotIn("texture_missing_resolution", check["risk_flags"])
        self.assertIn("texture_missing_channel_stats", check["risk_flags"])

    def test_catalogue_reports_ambiguous_texture_role_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "ambiguous_panel.fbx").write_bytes(b"fbx")
            _write_png(root / "ambiguous_panel_base.png", (80, 120, 160, 255))
            _write_png(root / "ambiguous_panel_diffuse.png", (90, 130, 170, 255))
            _write_png(root / "ambiguous_panel_normal.png", (128, 128, 255, 255))

            report = build_external_model_audit_catalogue([root])

        row = report["models"][0]
        self.assertEqual(1, report["summary"]["ambiguous_texture_refs"])
        self.assertEqual(1, len(row["ambiguous_texture_refs"]))
        self.assertIn("ambiguous_panel:base:", row["ambiguous_texture_refs"][0])
        self.assertIn("ambiguous_panel_base.png", row["ambiguous_texture_refs"][0])
        self.assertIn("ambiguous_panel_diffuse.png", row["ambiguous_texture_refs"][0])
        self.assertTrue(any("ambiguous texture role" in warning for warning in row["warnings"]))

    def test_unsupported_companion_classifier_uses_shared_material_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "crystal_lens.fbx").write_bytes(b"fbx")
            _write_png(root / "crystal_lens_opacity.png", (255, 255, 255, 128))
            (root / "organic_face_skin.fbx").write_bytes(b"fbx")
            _write_png(root / "organic_face_skin_base.png", (180, 120, 100, 255))

            report = build_external_model_audit_catalogue([root])

        classes_by_name = {
            Path(row["path"]).name: {
                item["material_class"]
                for material in row["material_inventory"]
                for item in material["material_classes"]
            }
            for row in report["models"]
        }
        self.assertIn("glass_crystal", classes_by_name["crystal_lens.fbx"])
        self.assertIn("skin_organic", classes_by_name["organic_face_skin.fbx"])
        self.assertNotIn("glass", report["summary"]["material_class_counts"])
        self.assertNotIn("skin", report["summary"]["material_class_counts"])

    def test_unsupported_companion_classifier_uses_texture_channel_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "plain_asset.fbx").write_bytes(b"fbx")
            _write_png(root / "plain_asset_base.png", (220, 170, 40, 128))
            _write_png(root / "plain_asset_metallicRoughness.png", (10, 80, 240, 255))

            report = build_external_model_audit_catalogue([root])

        row = report["models"][0]
        inventory = row["material_inventory"][0]
        classes = {item["material_class"]: item for item in inventory["material_classes"]}
        self.assertEqual("browsable_unsupported", row["audit_status"])
        self.assertIn("gold", classes)
        self.assertIn("metal", classes)
        self.assertIn("glass_crystal", classes)
        self.assertTrue(any("metallic yellow color" in reason for reason in classes["gold"]["evidence"]))
        self.assertTrue(any("B channel mean" in reason for reason in classes["metal"]["evidence"]))
        self.assertTrue(any("source alpha channel" in reason for reason in classes["glass_crystal"]["evidence"]))

    def test_unsupported_companion_classifier_uses_painted_and_rough_texture_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "painted steel panel.fbx").write_bytes(b"fbx")
            _write_png(root / "painted steel panel_base.png", (190, 40, 30, 255))
            _write_png(root / "painted steel panel_metallicRoughness.png", (20, 120, 230, 255))
            (root / "rough_brown_panel.fbx").write_bytes(b"fbx")
            _write_png(root / "rough_brown_panel_base.png", (90, 48, 20, 255))
            _write_png(root / "rough_brown_panel_roughness.png", (220, 220, 220, 255))
            (root / "neutral_block.fbx").write_bytes(b"fbx")
            _write_png(root / "neutral_block_base.png", (120, 116, 110, 255))
            _write_png(root / "neutral_block_roughness.png", (210, 210, 210, 255))

            report = build_external_model_audit_catalogue([root])

        by_name = {
            Path(row["path"]).name: {
                item["material_class"]: item
                for material in row["material_inventory"]
                for item in material["material_classes"]
            }
            for row in report["models"]
        }
        painted = by_name["painted steel panel.fbx"]
        brown = by_name["rough_brown_panel.fbx"]
        neutral = by_name["neutral_block.fbx"]
        self.assertIn("painted_metal", painted)
        self.assertIn("metal", painted)
        self.assertIn("leather", brown)
        self.assertIn("wood", brown)
        self.assertIn("stone", neutral)
        self.assertTrue(any("painted/coated token" in reason for reason in painted["painted_metal"]["evidence"]))
        self.assertTrue(any("warm brown color" in reason for reason in brown["wood"]["evidence"]))
        self.assertTrue(any("rough neutral color" in reason for reason in neutral["stone"]["evidence"]))

    def test_catalogue_infers_ascii_fbx_material_textures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_png(root / "gold_blade_base.png", (230, 180, 40, 255))
            _write_png(root / "gold_blade_normal.png", (128, 128, 255, 255))
            (root / "gold_blade.fbx").write_text(
                """
; FBX 7.4.0 project file
Objects:  {
    Material: 100, "Material::GoldBlade", "" {
    }
    Texture: 200, "Texture::Gold_BaseColor", "" {
        FileName: "gold_blade_base.png"
        RelativeFilename: "gold_blade_base.png"
    }
    Texture: 201, "Texture::Gold_Normal", "" {
        FileName: "gold_blade_normal.png"
        RelativeFilename: "gold_blade_normal.png"
    }
}
Connections:  {
    C: "OP",200,100,"DiffuseColor"
    C: "OP",201,100,"NormalMap"
}
""",
                encoding="utf-8",
            )

            report = build_external_model_audit_catalogue([root])

        row = report["models"][0]
        inventory = row["material_inventory"][0]
        slots = {slot["slot_kind"]: slot for slot in inventory["texture_slots"]}
        classes = {item["material_class"] for item in inventory["material_classes"]}
        self.assertEqual("browsable_material_inferred", row["audit_status"])
        self.assertFalse(row["import_supported"])
        self.assertEqual(1, report["summary"]["metadata_inferred_models"])
        self.assertEqual("GoldBlade", inventory["material_name"])
        self.assertEqual("fbx_ascii_connection", slots["base"]["confidence"])
        self.assertEqual((2, 2), slots["base"]["resolution"])
        self.assertEqual("fbx_ascii", slots["normal"]["source"])
        self.assertIn("gold", classes)
        self.assertIn("metal", classes)

    def test_catalogue_reads_ascii_fbx_material_scalar_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "crystal_gem.fbx").write_text(
                """
; FBX 7.4.0 project file
Objects:  {
    Material: 100, "Material::CrystalGem", "" {
        Properties70:  {
            P: "DiffuseColor", "Color", "", "A",0.8,0.1,0.05
            P: "SpecularColor", "Color", "", "A",0.2,0.2,0.2
            P: "Roughness", "Number", "", "A",0.35
            P: "Metalness", "Number", "", "A",0.0
            P: "EmissiveColor", "Color", "", "A",1,0,0
            P: "EmissiveFactor", "Number", "", "A",0.8
            P: "Opacity", "Number", "", "A",0.45
        }
    }
}
""",
                encoding="utf-8",
            )

            report = build_external_model_audit_catalogue([root])
            check = check_external_model_audit_report(report)

        row = report["models"][0]
        inventory = row["material_inventory"][0]
        classes = {item["material_class"] for item in inventory["material_classes"]}
        diagnostic_codes = {item["code"] for item in inventory["channel_diagnostics"]}
        self.assertEqual("browsable_material_inferred", row["audit_status"])
        self.assertFalse(row["import_supported"])
        self.assertEqual(1, report["summary"]["metadata_inferred_models"])
        self.assertEqual("CrystalGem", inventory["material_name"])
        self.assertEqual("fbx_ascii", inventory["metadata_source"])
        self.assertEqual("metallic_roughness", inventory["pbr_workflow"])
        self.assertEqual((0.8, 0.1, 0.05), tuple(inventory["color_factor"]))
        self.assertEqual((1.0, 0.0, 0.0), tuple(inventory["emissive_color"]))
        self.assertEqual((0.45, 0.45), tuple(inventory["vertex_alpha"]))
        self.assertEqual(0.35, inventory["scalar_hints"]["roughness"])
        self.assertEqual(0.0, inventory["scalar_hints"]["metalness"])
        self.assertEqual(0.2, inventory["scalar_hints"]["specular"])
        self.assertEqual(0.8, inventory["scalar_hints"]["emissive_intensity"])
        self.assertIn("base_color_scalar", inventory["detected_channels"])
        self.assertIn("roughness_scalar", inventory["detected_channels"])
        self.assertIn("metalness_scalar", inventory["detected_channels"])
        self.assertIn("emissive_scalar", inventory["detected_channels"])
        self.assertIn("opacity_scalar", inventory["detected_channels"])
        self.assertNotIn("roughness", inventory["missing_channels"])
        self.assertNotIn("metalness", inventory["missing_channels"])
        self.assertNotIn("emissive", inventory["missing_channels"])
        self.assertIn("source_vertex_alpha_opacity", diagnostic_codes)
        self.assertIn("source_emissive_scalar_no_texture", diagnostic_codes)
        self.assertIn("glass_crystal", classes)
        self.assertIn("emissive", classes)
        self.assertNotIn("missing_alpha_diagnostics", check["risk_flags"])
        self.assertNotIn("missing_emissive_diagnostics", check["risk_flags"])
        self.assertEqual(0, report["summary"]["materials_missing_roughness_metalness_diagnostics"])

    def test_catalogue_uses_ascii_fbx_scalar_color_for_material_classes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "plain_surface.fbx").write_text(
                """
Objects:  {
    Material: 100, "Material::PlainSurface", "" {
        Properties70:  {
            P: "DiffuseColor", "Color", "", "A",0.86,0.66,0.15
            P: "Metalness", "Number", "", "A",1.0
            P: "Roughness", "Number", "", "A",0.22
        }
    }
}
""",
                encoding="utf-8",
            )

            report = build_external_model_audit_catalogue([root])

        inventory = report["models"][0]["material_inventory"][0]
        classes = {item["material_class"]: item for item in inventory["material_classes"]}
        self.assertEqual("browsable_material_inferred", report["models"][0]["audit_status"])
        self.assertIn("gold", classes)
        self.assertIn("metal", classes)
        self.assertTrue(any("metallic yellow color" in reason for reason in classes["gold"]["evidence"]))
        self.assertTrue(any("metallic factor" in reason for reason in classes["metal"]["evidence"]))

    def test_catalogue_infers_binary_fbx_texture_strings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_png(root / "wire_base.png", (200, 90, 45, 255))
            _write_png(root / "wire_normal.png", (128, 128, 255, 255))
            (root / "generic_wire.fbx").write_bytes(
                b"Kaydara FBX Binary  \x00\x1a\x00"
                + (b"\x00" * 16)
                + b"Material::CopperWire\x00"
                + b"C:\\source\\wire_base.png\x00"
                + b"textures/wire_normal.png\x00"
            )

            report = build_external_model_audit_catalogue([root])

        row = report["models"][0]
        inventory = row["material_inventory"][0]
        slots = {slot["slot_kind"]: slot for slot in inventory["texture_slots"]}
        classes = {item["material_class"] for item in inventory["material_classes"]}
        self.assertEqual("browsable_material_inferred", row["audit_status"])
        self.assertFalse(row["import_supported"])
        self.assertEqual(1, report["summary"]["metadata_inferred_models"])
        self.assertEqual("CopperWire", inventory["material_name"])
        self.assertEqual("fbx_binary", slots["base"]["source"])
        self.assertEqual("fbx_binary_texture", slots["base"]["confidence"])
        self.assertEqual((2, 2), slots["base"]["resolution"])
        self.assertEqual("fbx_binary", slots["normal"]["source"])
        self.assertIn("copper", classes)
        self.assertIn("metal", classes)
        self.assertTrue(any("FBX binary" in warning for warning in row["warnings"]))

    def test_catalogue_indexes_zip_members_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "packed_sword.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("scene/model.gltf", json.dumps({"asset": {"version": "2.0"}}))
                zip_file.writestr("scene/model_base.png", b"png")
                zip_file.writestr("scene/model_normal.ktx2", b"\xabKTX 20\xbb\r\n\x1a\n")

            report = build_external_model_audit_catalogue([root])

            self.assertFalse((root / ".cdmw_extracted").exists())

        row = report["models"][0]
        textures = {item["archive_member"]: item for item in row["companion_textures"] if "archive_member" in item}
        self.assertEqual("archive_indexed", row["audit_status"])
        self.assertTrue(row["import_supported"])
        self.assertEqual(1, report["summary"]["archive_models"])
        self.assertEqual(("scene/model.gltf",), tuple(row["zip_importable_members"]))
        self.assertEqual("base", textures["scene/model_base.png"]["slot_guess"])
        self.assertEqual("normal", textures["scene/model_normal.ktx2"]["slot_guess"])
        self.assertTrue(textures["scene/model_normal.ktx2"]["diagnostic_only"])

    def test_catalogue_indexes_nested_zip_members_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as stage_dir:
            root = Path(temp_dir)
            stage = Path(stage_dir)
            scene = stage / "inner" / "scene"
            scene.mkdir(parents=True)
            _write_triangle_gltf(scene / "model.gltf")
            nested_payload = io.BytesIO()
            with zipfile.ZipFile(nested_payload, "w") as nested_zip:
                for path in sorted(scene.rglob("*")):
                    if path.is_file():
                        nested_zip.write(path, path.relative_to(stage / "inner").as_posix())
            archive = root / "packed_nested.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("source/model.zip.zip", nested_payload.getvalue())

            report = build_external_model_audit_catalogue([root])
            scanned = scan_local_model_files([root], extensions=(".zip",))
            member_refs = zip_importable_member_refs(archive)

            self.assertFalse((root / ".cdmw_extracted").exists())

        row = report["models"][0]
        textures = {item["archive_member"]: item for item in row["companion_textures"] if "archive_member" in item}
        self.assertTrue(scanned[0].import_supported)
        self.assertEqual(("source/model.zip.zip::scene/model.gltf",), member_refs)
        self.assertEqual("archive_indexed", row["audit_status"])
        self.assertTrue(row["import_supported"])
        self.assertEqual(("source/model.zip.zip::scene/model.gltf",), tuple(row["zip_importable_members"]))
        self.assertEqual(("source/model.zip.zip::scene/model.gltf",), tuple(row["zip_audit_members"]))
        self.assertEqual("base", textures["source/model.zip.zip::scene/gold_base.png"]["slot_guess"])
        self.assertEqual((2, 2), tuple(textures["source/model.zip.zip::scene/gold_base.png"]["resolution"]))

    def test_catalogue_audits_fbx_only_source_zip_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as stage_dir:
            root = Path(temp_dir)
            stage = Path(stage_dir)
            source_dir = stage / "source"
            source_dir.mkdir()
            _write_png(source_dir / "wire_base.png", (190, 90, 45, 255))
            _write_png(source_dir / "wire_normal.png", (128, 128, 255, 255))
            (source_dir / "copper_wire.fbx").write_text(
                """
Objects:  {
    Material: 100, "Material::CopperWire", "" {
    }
    Texture: 200, "Texture::Wire_BaseColor", "" {
        RelativeFilename: "wire_base.png"
    }
    Texture: 201, "Texture::Wire_Normal", "" {
        RelativeFilename: "wire_normal.png"
    }
}
Connections:  {
    C: "OP",200,100,"DiffuseColor"
    C: "OP",201,100,"NormalMap"
}
""",
                encoding="utf-8",
            )
            archive = root / "source_bundle.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                for path in sorted(source_dir.rglob("*")):
                    zip_file.write(path, path.relative_to(stage).as_posix())

            indexed = build_external_model_audit_catalogue([root])
            audited = build_external_model_audit_catalogue([root], audit_zip_contents=True)

        self.assertFalse((root / ".cdmw_extracted").exists())
        indexed_row = indexed["models"][0]
        self.assertEqual("archive_indexed", indexed_row["audit_status"])
        self.assertFalse(indexed_row["import_supported"])
        self.assertEqual((), tuple(indexed_row["zip_importable_members"]))
        self.assertEqual(("source/copper_wire.fbx",), tuple(indexed_row["zip_audit_members"]))

        row = audited["models"][0]
        inventory = row["material_inventory"][0]
        slots = {slot["slot_kind"]: slot for slot in inventory["texture_slots"]}
        classes = {item["material_class"] for item in inventory["material_classes"]}
        self.assertEqual("archive_audited", row["audit_status"])
        self.assertFalse(row["import_supported"])
        self.assertEqual("source/copper_wire.fbx", row["zip_audited_member"])
        self.assertEqual(1, audited["summary"]["zip_audited_models"])
        self.assertEqual(1, audited["summary"]["fbx_metadata_inferred_models"])
        self.assertEqual("CopperWire", inventory["material_name"])
        self.assertEqual("fbx_ascii", slots["base"]["source"])
        self.assertIn("source_bundle.zip::source/wire_base.png", slots["base"]["texture_path"].replace("\\", "/"))
        self.assertIn("source_bundle.zip::source/wire_normal.png", slots["normal"]["texture_path"].replace("\\", "/"))
        self.assertIn("copper", classes)
        self.assertIn("metal", classes)
        self.assertTrue(any("temporary extraction" in warning for warning in row["warnings"]))

    def test_catalogue_can_audit_zip_contents_from_temp_extraction(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as stage_dir:
            root = Path(temp_dir)
            stage = Path(stage_dir)
            scene = stage / "scene"
            scene.mkdir(parents=True)
            _write_triangle_gltf(scene / "model.gltf")
            archive = root / "packed_sword.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                for path in sorted(scene.rglob("*")):
                    if path.is_file():
                        zip_file.write(path, path.relative_to(stage).as_posix())

            report = build_external_model_audit_catalogue([root], audit_zip_contents=True)

            self.assertFalse((root / ".cdmw_extracted").exists())

        row = report["models"][0]
        inventory = row["material_inventory"][0]
        slots = {slot["slot_kind"]: slot for slot in inventory["texture_slots"]}
        self.assertTrue(report["audit_zip_contents"])
        self.assertEqual("archive_audited", row["audit_status"])
        self.assertEqual(1, report["summary"]["zip_audited_models"])
        self.assertEqual("scene/model.gltf", row["zip_audited_member"])
        self.assertEqual("metallic_roughness", inventory["pbr_workflow"])
        self.assertIn("packed_sword.zip::scene/gold_base.png", slots["base"]["texture_path"].replace("\\", "/"))
        self.assertIn("packed_sword.zip::scene/gold_normal.png", slots["normal"]["texture_path"].replace("\\", "/"))

    def test_catalogue_can_audit_nested_zip_contents_from_temp_extraction(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as stage_dir:
            root = Path(temp_dir)
            stage = Path(stage_dir)
            scene = stage / "inner" / "scene"
            scene.mkdir(parents=True)
            _write_triangle_gltf(scene / "model.gltf")
            nested_payload = io.BytesIO()
            with zipfile.ZipFile(nested_payload, "w") as nested_zip:
                for path in sorted(scene.rglob("*")):
                    if path.is_file():
                        nested_zip.write(path, path.relative_to(stage / "inner").as_posix())
            archive = root / "packed_nested.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("source/model.zip.zip", nested_payload.getvalue())

            report = build_external_model_audit_catalogue([root], audit_zip_contents=True)

            self.assertFalse((root / ".cdmw_extracted").exists())

        row = report["models"][0]
        inventory = row["material_inventory"][0]
        slots = {slot["slot_kind"]: slot for slot in inventory["texture_slots"]}
        self.assertTrue(report["audit_zip_contents"])
        self.assertEqual("archive_audited", row["audit_status"])
        self.assertEqual(1, report["summary"]["zip_audited_models"])
        self.assertEqual("source/model.zip.zip::scene/model.gltf", row["zip_audited_member"])
        self.assertEqual("metallic_roughness", inventory["pbr_workflow"])
        self.assertIn("packed_nested.zip::source/model.zip.zip::scene/gold_base.png", slots["base"]["texture_path"].replace("\\", "/"))
        self.assertIn("packed_nested.zip::source/model.zip.zip::scene/gold_normal.png", slots["normal"]["texture_path"].replace("\\", "/"))

    def test_catalogue_zip_audit_decodes_collada_percent_encoded_texture_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as stage_dir:
            root = Path(temp_dir)
            stage = Path(stage_dir)
            scene = stage / "source"
            texture_dir = scene / "Textures With Spaces"
            texture_dir.mkdir(parents=True)
            _write_png(texture_dir / "red gem.png", (220, 20, 20, 255))
            _write_triangle_dae_with_base_texture(scene / "model.dae", "Textures%20With%20Spaces/red%20gem.png")
            archive = root / "packed_gem.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                for path in sorted(scene.rglob("*")):
                    if path.is_file():
                        zip_file.write(path, path.relative_to(stage).as_posix())

            report = build_external_model_audit_catalogue([root], audit_zip_contents=True)

            self.assertFalse((root / ".cdmw_extracted").exists())

        row = report["models"][0]
        inventory = row["material_inventory"][0]
        slots = {slot["slot_kind"]: slot for slot in inventory["texture_slots"]}
        base_slot = slots["base"]
        self.assertEqual("archive_audited", row["audit_status"])
        self.assertEqual("source/model.dae", row["zip_audited_member"])
        self.assertEqual(0, report["summary"]["textures_missing_channel_stats"])
        self.assertEqual(0, report["summary"]["textures_missing_resolution"])
        self.assertEqual("png", base_slot["image_format"])
        self.assertEqual((2, 2), tuple(base_slot["resolution"]))
        self.assertTrue(base_slot["channel_stats"])
        self.assertIn("packed_gem.zip::source/Textures With Spaces/red gem.png", base_slot["texture_path"].replace("\\", "/"))
        self.assertNotIn("%20", base_slot["texture_path"])
        self.assertFalse(any("missing" in warning.lower() for warning in row["warnings"]))

    def test_catalogue_zip_audit_reports_unresolved_texture_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as stage_dir:
            root = Path(temp_dir)
            stage = Path(stage_dir)
            scene = stage / "source"
            texture_dir = stage / "textures"
            scene.mkdir(parents=True)
            texture_dir.mkdir(parents=True)
            Image.new("RGB", (2, 2), (100, 90, 80)).save(texture_dir / "Metal_Seamed.jpeg")
            _write_triangle_dae_with_base_texture(scene / "model.dae", "Missing%20Textures/red_gem.jpg")
            archive = root / "packed_missing_ref.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                for path in sorted(stage.rglob("*")):
                    if path.is_file():
                        zip_file.write(path, path.relative_to(stage).as_posix())

            report = build_external_model_audit_catalogue([root], audit_zip_contents=True)
            check = check_external_model_audit_report(report)

            self.assertFalse((root / ".cdmw_extracted").exists())

        row = report["models"][0]
        candidates = tuple(row["unresolved_texture_candidates"])
        self.assertEqual(1, report["summary"]["missing_texture_refs"])
        self.assertEqual(1, report["summary"]["unresolved_texture_candidates"])
        self.assertEqual(1, check["counts"]["unresolved_texture_candidates"])
        self.assertIn("unresolved_texture_candidates", check["allowed_risk_flags"])
        self.assertNotIn("unresolved_texture_candidates", check["review_risk_flags"])
        self.assertTrue(any("nearby texture candidate" in warning for warning in check["warnings"]))
        self.assertEqual(1, len(candidates))
        self.assertIn("Missing Textures/red_gem.jpg", candidates[0]["missing_texture_ref"].replace("\\", "/"))
        self.assertIn("packed_missing_ref.zip::textures/Metal_Seamed.jpeg", candidates[0]["candidate_path"].replace("\\", "/"))
        self.assertEqual("", candidates[0]["candidate_slot_guess"])
        self.assertEqual("nearby_texture", candidates[0]["confidence"])
        self.assertEqual((2, 2), tuple(candidates[0]["candidate_resolution"]))
        self.assertEqual("available", candidates[0]["candidate_resolution_status"])
        self.assertEqual("available", candidates[0]["candidate_channel_stats_status"])
        self.assertEqual("srgb", candidates[0]["candidate_color_space"])
        stats = dict(candidates[0]["candidate_channel_stats"])
        self.assertAlmostEqual(100 / 255.0, stats["r_mean"], places=4)
        self.assertAlmostEqual(90 / 255.0, stats["g_mean"], places=4)
        self.assertAlmostEqual(80 / 255.0, stats["b_mean"], places=4)
        self.assertTrue(any("unresolved texture candidate" in warning for warning in row["warnings"]))

    def test_catalogue_caps_zip_content_audits_with_skip_evidence(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as stage_dir:
            root = Path(temp_dir)
            stage = Path(stage_dir)
            for name in ("first", "second"):
                scene = stage / name / "scene"
                scene.mkdir(parents=True)
                _write_triangle_gltf(scene / "model.gltf")
                archive = root / f"{name}.zip"
                with zipfile.ZipFile(archive, "w") as zip_file:
                    for path in sorted(scene.rglob("*")):
                        if path.is_file():
                            zip_file.write(path, path.relative_to(stage / name).as_posix())

            report = build_external_model_audit_catalogue([root], audit_zip_contents=True, max_zip_audits=1)

            self.assertFalse((root / ".cdmw_extracted").exists())

        skipped = [row for row in report["models"] if row.get("zip_content_audit_skipped")]
        self.assertTrue(report["audit_zip_contents"])
        self.assertEqual(1, report["max_zip_audits"])
        self.assertEqual(1, report["summary"]["zip_audited_models"])
        self.assertEqual(1, report["summary"]["zip_content_audit_skipped_by_limit"])
        self.assertEqual(1, len(skipped))
        self.assertEqual("archive_indexed", skipped[0]["audit_status"])
        self.assertEqual("max_zip_audits:1", skipped[0]["zip_content_audit_skip_reason"])
        self.assertTrue(any("content audit skipped" in warning for warning in skipped[0]["warnings"]))

    def test_external_model_audit_checker_passes_strong_material_inventory(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_triangle_gltf(root / "gold_sword.gltf")

            report = build_external_model_audit_catalogue([root])
            result = check_external_model_audit_report(report)

        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["risk_flags"])
        self.assertEqual(1, result["counts"]["audited_models"])
        self.assertEqual(1, result["counts"]["material_inventory_rows"])
        self.assertEqual(3, result["counts"]["texture_slot_rows"])
        self.assertEqual(0, result["counts"]["texture_slots_missing_resolution"])
        self.assertEqual(0, result["counts"]["texture_slots_missing_format"])
        self.assertEqual(0, result["counts"]["texture_slots_missing_color_space"])
        self.assertEqual(0, result["counts"]["texture_slots_missing_channel_stats"])
        self.assertEqual(1, result["counts"]["material_section_rows"])

    def test_external_model_audit_checker_reports_blocking_and_review_gaps(self) -> None:
        report = {
            "schema_version": 1,
            "tool": "external_model_audit_catalogue",
            "roots": ["C:/models"],
            "audit_zip_contents": True,
            "models": [
                {
                    "path": "weak.gltf",
                    "audit_status": "audited",
                    "import_supported": True,
                    "missing_texture_refs": ["missing_base.png"],
                    "ambiguous_texture_refs": ["weak:base:a.png,b.png"],
                    "material_inventory": [
                        {
                            "material_name": "Weak Glass",
                            "alpha_mode": "BLEND",
                            "pbr_workflow": "",
                            "material_classes": (),
                            "detected_channels": (),
                            "missing_channels": (),
                            "channel_diagnostics": (),
                            "texture_slots": (
                                {
                                    "slot_kind": "base",
                                    "texture_path": "weak_base.png",
                                },
                            ),
                            "sections": (
                                {
                                    "section_name": "WeakPart",
                                    "vertex_count": 0,
                                    "face_count": 0,
                                    "has_uvs": False,
                                    "has_normals": False,
                                },
                            ),
                        },
                        {
                            "material_name": "No Evidence",
                            "pbr_workflow": "metallic_roughness",
                            "material_classes": ({"material_class": "unknown"},),
                            "detected_channels": (),
                            "missing_channels": (),
                            "channel_diagnostics": (),
                            "texture_slots": (),
                            "sections": (
                                {
                                    "section_name": "NoEvidencePart",
                                    "vertex_count": 3,
                                    "face_count": 1,
                                    "has_uvs": True,
                                    "has_normals": True,
                                },
                            ),
                        },
                        {
                            "material_name": "Misrouted",
                            "material_index": 2,
                            "pbr_workflow": "metallic_roughness",
                            "material_classes": ({"material_class": "metal"},),
                            "detected_channels": ("base_color", "roughness", "metalness"),
                            "missing_channels": ("emissive",),
                            "channel_diagnostics": (
                                {
                                    "code": "source_base_texture_bound_as_emissive",
                                    "message": "Base-color texture is also wired to emissive.",
                                    "slot_kind": "emissive",
                                    "texture_path": "shared_base.png",
                                },
                            ),
                            "texture_slots": (
                                {
                                    "slot_kind": "base",
                                    "texture_path": "shared_base.png",
                                    "texture_name": "shared_base.png",
                                    "image_format": "png",
                                    "color_space": "srgb",
                                    "resolution": (2, 2),
                                    "channel_stats": (("r_mean", 0.7),),
                                },
                            ),
                            "sections": (
                                {
                                    "section_name": "MisroutedPart",
                                    "vertex_count": 3,
                                    "face_count": 1,
                                    "has_uvs": True,
                                    "has_normals": True,
                                },
                            ),
                        },
                    ],
                },
                {
                    "path": "empty.gltf",
                    "audit_status": "audited",
                    "import_supported": True,
                    "material_inventory": (),
                },
                {
                    "path": "packed.zip",
                    "audit_status": "archive_indexed",
                    "zip_audit_members": ("scene/model.gltf",),
                    "zip_content_audit_skipped": True,
                    "material_inventory": (),
                },
            ],
        }

        failed = check_external_model_audit_report(report, allowed_risk_flags=())
        warn_only = check_external_model_audit_report(report, fail_on_risk_flags=(), allowed_risk_flags=())

        self.assertEqual("failed", failed["status"])
        self.assertIn("audited_model_without_material_inventory", failed["blocking_risk_flags"])
        self.assertEqual("needs_review", warn_only["status"])
        self.assertIn("archive_content_not_audited", warn_only["review_risk_flags"])
        self.assertIn("zip_audit_limit_skipped", warn_only["review_risk_flags"])
        self.assertIn("missing_pbr_workflow", warn_only["review_risk_flags"])
        self.assertIn("missing_material_classes", warn_only["review_risk_flags"])
        self.assertIn("missing_channel_diagnostics", warn_only["review_risk_flags"])
        self.assertIn("missing_texture_slot_facts", warn_only["review_risk_flags"])
        self.assertIn("texture_missing_resolution", warn_only["review_risk_flags"])
        self.assertIn("texture_missing_format", warn_only["review_risk_flags"])
        self.assertIn("texture_missing_color_space", warn_only["review_risk_flags"])
        self.assertIn("texture_missing_channel_stats", warn_only["review_risk_flags"])
        self.assertIn("section_missing_geometry", warn_only["review_risk_flags"])
        self.assertIn("section_missing_uvs", warn_only["review_risk_flags"])
        self.assertIn("section_missing_normals", warn_only["review_risk_flags"])
        self.assertIn("missing_texture_refs", warn_only["review_risk_flags"])
        self.assertIn("ambiguous_texture_refs", warn_only["review_risk_flags"])
        self.assertIn("missing_alpha_diagnostics", warn_only["review_risk_flags"])
        self.assertIn("missing_emissive_diagnostics", warn_only["review_risk_flags"])
        self.assertIn("missing_roughness_metalness_diagnostics", warn_only["review_risk_flags"])
        self.assertIn("source_texture_route_mismatch", warn_only["review_risk_flags"])
        self.assertEqual(1, warn_only["counts"]["audited_model_without_material_inventory"])
        self.assertEqual(1, warn_only["counts"]["archive_indexed_with_audit_members"])
        self.assertEqual(1, warn_only["counts"]["zip_content_audit_skipped_by_limit"])
        self.assertEqual(1, warn_only["counts"]["materials_missing_texture_facts"])
        self.assertEqual(1, warn_only["counts"]["sections_missing_geometry"])
        self.assertEqual(1, warn_only["counts"]["source_texture_route_mismatches"])
        examples = warn_only["examples"]
        self.assertEqual("missing_base.png", examples["missing_texture_refs"][0]["texture_ref"])
        self.assertEqual("Weak Glass", examples["missing_pbr_workflow"][0]["material_name"])
        self.assertEqual("base", examples["texture_missing_resolution"][0]["slot_kind"])
        self.assertEqual("WeakPart", examples["section_missing_geometry"][0]["section_name"])
        self.assertEqual("packed.zip", examples["archive_content_not_audited"][0]["path"])
        self.assertEqual(["scene/model.gltf"], examples["archive_content_not_audited"][0]["zip_audit_members"])
        self.assertEqual("source_base_texture_bound_as_emissive", examples["source_texture_route_mismatch"][0]["code"])
        self.assertEqual("Misrouted", examples["source_texture_route_mismatch"][0]["material_name"])
        self.assertEqual("shared_base.png", examples["source_texture_route_mismatch"][0]["texture_path"])

    def test_external_model_audit_checker_does_not_block_non_importable_fbx_metadata_without_inventory(self) -> None:
        report = {
            "schema_version": 1,
            "tool": "external_model_audit_catalogue",
            "roots": ["models"],
            "audit_zip_contents": True,
            "models": [
                {
                    "path": "source/Hammer.FBX.fbx",
                    "audit_status": "archive_audited",
                    "import_supported": False,
                    "material_inventory": (),
                    "warnings": (
                        "FBX is browsable but not material-audited without an importer; export OBJ, DAE, GLB, or glTF.",
                    ),
                }
            ],
        }

        result = check_external_model_audit_report(report)

        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["blocking_risk_flags"])
        self.assertEqual(0, result["counts"]["audited_model_without_material_inventory"])

    def test_external_model_audit_checker_cli_writes_result_json(self) -> None:
        self._require_native_mesh_core()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_triangle_gltf(root / "gold_sword.gltf")
            report_path = root / "external_model_material_audit.json"
            out_json = root / "check.json"
            write_external_model_audit_catalogue(build_external_model_audit_catalogue([root]), report_path)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = check_external_model_audit_main([str(report_path), "--out-json", str(out_json)])

            payload = json.loads(out_json.read_text(encoding="utf-8"))
            printed = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertEqual("passed", payload["status"])
        self.assertEqual("passed", printed["status"])
        self.assertEqual(1, payload["counts"]["material_inventory_rows"])

    def test_external_model_audit_checker_cli_runs_by_script_path_outside_repo(self) -> None:
        self._require_native_mesh_core()
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as cwd_dir:
            root = Path(temp_dir)
            _write_triangle_gltf(root / "gold_sword.gltf")
            report_path = root / "external_model_material_audit.json"
            out_json = root / "check.json"
            write_external_model_audit_catalogue(build_external_model_audit_catalogue([root]), report_path)

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "tools" / "check_external_model_audit.py"),
                    str(report_path),
                    "--out-json",
                    str(out_json),
                ],
                cwd=cwd_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            printed = json.loads(result.stdout)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", payload["status"])
        self.assertEqual("passed", printed["status"])


if __name__ == "__main__":
    unittest.main()
