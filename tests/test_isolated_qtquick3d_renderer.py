from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from cdmw.models import (
    ModelPreviewData,
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.core.texture_native import write_native_texture_report_sidecar
from cdmw.rendering.qtquick3d_preview_package import (
    ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES,
    read_isolated_qtquick3d_preview_manifest,
    write_isolated_qtquick3d_preview_package,
)


def _vertex(
    x: float,
    y: float,
    z: float,
    *,
    color: tuple[float, float, float] = (0.25, 0.50, 0.75),
    uv: tuple[float, float] = (0.0, 0.0),
) -> bytes:
    return struct.pack(
        "<23f",
        x,
        y,
        z,
        0.0,
        0.0,
        1.0,
        color[0],
        color[1],
        color[2],
        uv[0],
        uv[1],
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        1.0,
        0.0,
        0.0,
    )


def _minimal_bc_dds(fourcc: bytes = b"DXT1") -> bytes:
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = (4).to_bytes(4, "little")
    header[12:16] = (4).to_bytes(4, "little")
    header[24:28] = (1).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = fourcc
    block_size = 8 if fourcc == b"DXT1" else 16
    return b"DDS " + bytes(header) + (b"\0" * block_size)


class IsolatedQtQuick3DPreviewPackageTests(unittest.TestCase):
    def test_writes_empty_preview_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = write_isolated_qtquick3d_preview_package(
                ModelPreviewData(path="empty.pac"),
                PreparedModelPreviewData(source_path="empty.pac"),
                output_root=Path(temp_dir) / "package",
            )
            manifest = read_isolated_qtquick3d_preview_manifest(package_dir)

        self.assertEqual(4, manifest["schema_version"])
        self.assertEqual("empty.pac", manifest["source_path"])
        self.assertEqual([], manifest["batches"])

    def test_writes_geometry_and_direct_texture_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            normal = temp_path / "normal.png"
            specular = temp_path / "material_sp.png"
            packed = temp_path / "material_ma.png"
            detail = temp_path / "material_mg.png"
            height = temp_path / "height_disp.png"
            base_dds = temp_path / "base.dds"
            specular_dds = temp_path / "material_sp.dds"
            packed_dds = temp_path / "material_ma.dds"
            detail_dds = temp_path / "material_mg.dds"
            for path in (base, normal, specular, packed, detail, height):
                path.write_bytes(path.name.encode("ascii"))
            for path in (base_dds, specular_dds, packed_dds, detail_dds):
                path.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        texture_name="blade_base",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_dds_path=str(base_dds),
                        preview_normal_texture_path=str(normal),
                        preview_height_texture_path=str(height),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_sp",
                                source_dds_path=str(specular_dds),
                                preview_texture_path=str(specular),
                                semantic_subtype="specular",
                                shader_family="SkinnedMeshStandard_Ver2",
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_kind="byte4",
                                        parameter_name="_scratchMetallic",
                                        value="16777215",
                                    ),
                                    PreviewMaterialParameterInput(
                                        parameter_kind="byte4",
                                        parameter_name="_scratchRoughness",
                                        value="8388607",
                                    ),
                                ),
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_ma",
                                source_dds_path=str(packed_dds),
                                preview_texture_path=str(packed),
                                semantic_subtype="material_mask",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_detailMaskTexture",
                                texture_name="blade_mg",
                                source_dds_path=str(detail_dds),
                                preview_texture_path=str(detail),
                                semantic_subtype="detail_mask",
                            ),
                        ),
                        has_texture_coordinates=True,
                        source_submesh_index=7,
                        source_vertex_indices=(10, 11, 12),
                        editor_role="replacement",
                        editor_part_name="blade",
                    ),
                ),
            )

            package_dir = write_isolated_qtquick3d_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_qtquick3d_preview_manifest(package_dir)

            batch = manifest["batches"][0]
            geometry_path = package_dir / batch["vertex_file"]
            textures = batch["textures"]
            dds_textures = batch["dds_textures"]
            editor_identity = batch["editor_identity"]

            self.assertEqual(3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES, geometry_path.stat().st_size)
            self.assertEqual(7, editor_identity["source_submesh_index"])
            self.assertEqual("replacement", editor_identity["role"])
            self.assertEqual("blade", editor_identity["part_name"])
            identity_blob = (package_dir / editor_identity["identity_file"]).read_bytes()
            self.assertEqual((7, 10, 7, 11, 7, 12), struct.unpack("<iiiiii", identity_blob))
            self.assertTrue((package_dir / textures["base"]).is_file())
            self.assertTrue(dds_textures["base"]["direct_upload_candidate"])
            self.assertEqual("bc1", dds_textures["base"]["compressed_family"])
            self.assertEqual(3, len(dds_textures["material_inputs"]))
            self.assertTrue((package_dir / textures["normal"]).is_file())
            self.assertTrue((package_dir / textures["height"]).is_file())
            self.assertTrue((package_dir / textures["specular"]).is_file())
            self.assertEqual("", textures["roughness"])
            self.assertEqual("", textures["metalness"])
            self.assertTrue(batch["tangents_usable"])
            self.assertGreater(batch["native_material_hints"]["metalness"], 0.0)
            self.assertGreater(batch["native_material_hints"]["specular"], 0.0)
            self.assertIn("packed material map skipped", " ".join(batch["notes"]))

    def test_prefer_direct_dds_skips_preview_png_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            specular = temp_path / "material_sp.png"
            pbr = temp_path / "legacy_pbr.png"
            base_dds = temp_path / "base.dds"
            specular_dds = temp_path / "material_sp.dds"
            material_dds = temp_path / "material_ma.dds"
            for path in (base, specular, pbr):
                path.write_bytes(path.name.encode("ascii"))
            for path in (base_dds, specular_dds, material_dds):
                path.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        texture_name="blade_base",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_dds_path=str(base_dds),
                        preview_material_texture_path=str(pbr),
                        preview_material_texture_dds_path=str(material_dds),
                        preview_material_texture_subtype="legacy_pbr_combined",
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_sp",
                                source_dds_path=str(specular_dds),
                                preview_texture_path=str(specular),
                                semantic_subtype="specular",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_qtquick3d_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            batch = read_isolated_qtquick3d_preview_manifest(package_dir)["batches"][0]
            textures = batch["textures"]

            self.assertEqual("", textures["base"])
            self.assertEqual("", textures["specular"])
            self.assertEqual("", textures["roughness"])
            self.assertFalse((package_dir / "textures" / "combined").exists())
            notes = " ".join(batch["notes"])
            self.assertIn("base PNG fallback skipped", notes)
            self.assertIn("specular PNG fallback skipped", notes)
            self.assertIn("legacy PBR PNG split skipped", notes)

    def test_direct_base_material_input_promotes_to_authoritative_base_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base_png = temp_path / "batch_base.png"
            base_dds = temp_path / "resolved_base.dds"
            base_png.write_bytes(b"preview")
            base_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="head.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="head",
                        texture_name="head",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base_png),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                texture_name="resolved_base",
                                source_dds_path=str(base_dds),
                                preview_texture_path=str(base_png),
                                parameter_name="_baseColorTexture",
                                semantic_type="albedo",
                                semantic_subtype="base_color",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_qtquick3d_preview_package(
                ModelPreviewData(path="head.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            batch = read_isolated_qtquick3d_preview_manifest(package_dir)["batches"][0]

            self.assertEqual("", batch["textures"]["base"])
            self.assertEqual(str(base_dds), batch["dds_textures"]["base"]["source_path"])
            self.assertTrue(batch["dds_textures"]["base"]["promoted_from_material_input"])
            self.assertIn("base PNG fallback skipped", " ".join(batch["notes"]))

    def test_d3d11_manifest_honors_support_map_and_camera_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            normal_dds = temp_path / "normal_n.dds"
            material_dds = temp_path / "material_ma.dds"
            height_dds = temp_path / "height_disp.dds"
            base.write_bytes(b"base")
            for path in (normal_dds, material_dds, height_dds):
                path.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="armor.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="armor",
                        texture_name="armor_base",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_normal_texture_dds_path=str(normal_dds),
                        preview_material_texture_dds_path=str(material_dds),
                        preview_height_texture_dds_path=str(height_dds),
                        has_texture_coordinates=True,
                    ),
                ),
            )
            settings = ModelPreviewRenderSettings(
                disable_normal_map=True,
                disable_height_map=True,
                orbit_sensitivity=0.33,
                pan_sensitivity=1.25,
                invert_orbit_x=True,
                invert_pan_y=True,
            )

            package_dir = write_isolated_qtquick3d_preview_package(
                ModelPreviewData(path="armor.pac"),
                prepared,
                output_root=temp_path / "package",
                render_settings=settings,
                prefer_direct_dds=True,
            )
            manifest = read_isolated_qtquick3d_preview_manifest(package_dir)
            dds_textures = manifest["batches"][0]["dds_textures"]

            self.assertNotIn("normal", dds_textures)
            self.assertIn("material", dds_textures)
            self.assertNotIn("height", dds_textures)
            self.assertAlmostEqual(0.33, manifest["orbit_sensitivity"])
            self.assertAlmostEqual(1.25, manifest["pan_sensitivity"])
            self.assertTrue(manifest["invert_orbit_x"])
            self.assertTrue(manifest["invert_pan_y"])

    def test_prefer_direct_dds_keeps_png_fallback_when_dds_is_not_uploadable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            specular = temp_path / "material_sp.png"
            specular_dds = temp_path / "material_sp.dds"
            specular.write_bytes(b"preview")
            specular_dds.write_bytes(b"not a dds")
            self.assertTrue(
                write_native_texture_report_sidecar(
                    specular,
                    {
                        "source_path": str(specular_dds),
                        "slot_kind": "specular",
                        "direct_upload_candidate": False,
                    },
                )
            )
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        texture_name="blade_base",
                        vertex_blob=blob,
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_sp",
                                preview_texture_path=str(specular),
                                semantic_subtype="specular",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_qtquick3d_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            batch = read_isolated_qtquick3d_preview_manifest(package_dir)["batches"][0]
            textures = batch["textures"]

            self.assertTrue(textures["specular"])
            self.assertTrue((package_dir / textures["specular"]).is_file())
            notes = " ".join(batch["notes"])
            self.assertNotIn("specular PNG fallback skipped", notes)

    def test_package_combiner_generates_independent_pbr_slots(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "blade_o.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(180, 120, 70, 80))
            self.assertTrue(base_image.save(str(base), "PNG"))
            material = temp_path / "blade_ma.png"
            material_image = QImage(4, 4, QImage.Format_RGBA8888)
            material_image.fill(QColor(64, 180, 230, 255))
            self.assertTrue(material_image.save(str(material), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        texture_name="blade",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_ma.dds",
                                preview_texture_path=str(material),
                                source_texture_path="blade_ma.dds",
                                semantic_type="mask",
                                semantic_subtype="material_mask",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_qtquick3d_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_qtquick3d_preview_manifest(package_dir)

            batch = manifest["batches"][0]
            textures = batch["textures"]
            for slot in ("base", "occlusion", "roughness", "metalness", "specular"):
                self.assertTrue((package_dir / textures[slot]).is_file(), slot)
            self.assertTrue(batch["material_combiner_active"])
            self.assertIn("material_mask", batch["material_combiner_decode_modes"])
            self.assertIn("occlusion", batch["material_combiner_outputs"])
            self.assertFalse(batch["texture_flip_vertical"])

    def test_package_reuses_legacy_pbr_response_without_full_recombine(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            legacy_pbr = temp_path / "legacy_pbr.png"
            image = QImage(2, 2, QImage.Format_RGBA8888)
            image.fill(QColor(220, 96, 170, 210))
            self.assertTrue(image.save(str(legacy_pbr), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        vertex_blob=blob,
                        index_count=3,
                        preview_material_texture_path=str(legacy_pbr),
                        preview_material_texture_subtype="pbr_combined",
                        preview_material_texture_packed_channels=("ao", "roughness", "metallic", "specular"),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_qtquick3d_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_qtquick3d_preview_manifest(package_dir)

            batch = manifest["batches"][0]
            textures = batch["textures"]
            for slot in ("occlusion", "roughness", "metalness", "specular"):
                self.assertTrue((package_dir / textures[slot]).is_file(), slot)
            self.assertEqual(["pbr_combined"], batch["material_combiner_decode_modes"])
            self.assertIn("legacy PBR response reused", " ".join(batch["material_combiner_notes"]))


class IsolatedQtQuick3DRendererSourceGuardTests(unittest.TestCase):
    def test_native_host_is_isolated_from_qtquick_and_archive_stack(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("D3D11CreateDevice", source)
        self.assertIn("D3D11CreateDeviceAndSwapChain", source)
        self.assertIn("D3DCompile", source)
        self.assertIn("DirectX::LoadFromDDSFile", source)
        self.assertIn("DirectX::CreateShaderResourceView", source)
        self.assertIn("--preview-package", source)
        self.assertIn("--status-file", source)
        self.assertIn("--parent-hwnd", source)
        self.assertIn("--crash-dir", source)
        self.assertIn("--diagnostic-log", source)
        self.assertIn("dds_direct_upload_candidates", source)
        self.assertIn("dds_direct_uploads", source)
        self.assertIn("dds_upload_formats", source)
        self.assertIn("texture_cache_hits", source)
        self.assertIn("best_material_dds_for_role", source)
        self.assertIn("material_hints", source)
        self.assertIn("RenderTuning", source)
        self.assertIn("parse_render_tuning", source)
        self.assertIn("MaxAnisotropy", source)
        self.assertIn("render_tuning", source)
        self.assertIn("detail_tex", source)
        self.assertIn("CREATETEX_FORCE_SRGB", source)
        self.assertIn("CREATETEX_IGNORE_SRGB", source)
        self.assertIn("srgb_color_uploads", source)
        self.assertIn("linear_to_srgb", source)
        self.assertIn("srgb_to_linear", source)
        self.assertIn("begin_mouse_drag", source)
        self.assertIn("kZoomSteps", source)
        self.assertIn("WM_MOUSEWHEEL", source)
        self.assertIn("WM_COPYDATA", source)
        self.assertIn("kCdmwCommandCopyData", source)
        self.assertIn("process_pending_commands", source)
        self.assertIn("load_package", source)
        self.assertIn("source_submesh_indices", source)
        self.assertIn("highlight_strength", source)
        self.assertIn("png_fallbacks", source)
        self.assertIn("material_combiner_outputs", source)
        self.assertIn("Texture2D roughness_tex", source)
        self.assertIn("Texture2D metalness_tex", source)
        self.assertIn("Texture2D specular_tex", source)
        self.assertIn("Texture2D height_tex", source)
        self.assertNotIn("QtQuick", source)
        self.assertNotIn("QQuickWidget", source)
        self.assertNotIn("QQuickView", source)
        self.assertNotIn("QOpenGLWidget", source)
        self.assertNotIn("main_window", source)
        self.assertNotIn("configure_experimental_qtquick3d_rhi", source)
        self.assertNotIn("parse_mesh(", source)
        self.assertNotIn("build_archive_preview_result", source)
        self.assertNotIn("std::cin", source)

    def test_directxtex_helper_reports_dds_direct_upload_metadata(self) -> None:
        source = Path("native/cd_texture_dx/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("DirectX::LoadFromDDSFile", source)
        self.assertIn("DirectX::SaveToWICFile", source)
        self.assertIn("DirectX::SaveToDDSFile", source)
        self.assertIn("batch-encode-json", source)
        self.assertIn("native_diagnostics.h", source)
        self.assertIn("batch_preview_start", source)
        self.assertIn("batch_encode_start", source)
        self.assertIn("--diagnostic-log", source)
        self.assertIn("--crash-dir", source)
        self.assertIn("parse_encode_jobs", source)
        self.assertIn("CoInitializeEx", source)
        self.assertIn("DXGI_FORMAT_BC1_UNORM", source)
        self.assertIn("DXGI_FORMAT_BC3_UNORM", source)
        self.assertIn("DXGI_FORMAT_BC5_UNORM", source)
        self.assertIn("DXGI_FORMAT_BC7_UNORM", source)
        self.assertIn("direct_upload_candidate", source)
        self.assertIn("compressed_family", source)
        self.assertIn("normal_green_inverted", source)
        self.assertIn("DirectX::Decompress(*first, DXGI_FORMAT_R8G8B8A8_UNORM", source)
        self.assertIn("rgba.InitializeFromImage(*convert_source)", source)
        self.assertIn("source_format=", source)

    def test_native_d3d11_is_archive_renderer_backend_and_qtquick_is_not_used(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("archive_isolated_renderer_button", source)
        self.assertIn("archive_d3d11_preview_host", source)
        self.assertIn("ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertIn("ARCHIVE_MODEL_RENDERER_DEFAULT = ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertIn("normalize_archive_model_renderer_backend", source)
        self.assertIn("low_res_base", source)
        self.assertIn("NativeD3D11PreviewHostFrame", source)
        self.assertIn("_WM_SET_ZOOM", source)
        self.assertIn("_WM_COPYDATA_COMMAND", source)
        self.assertIn("load_package(self, package_dir", source)
        self.assertIn("clear_preview(self, status_file", source)
        self.assertIn("set_render_tuning(self, settings", source)
        self.assertIn("set_highlighted_source_submeshes", source)
        self.assertIn("archive_isolated_renderer_package_source", source)
        self.assertIn("_native_preview_core_failure_result", source)
        self.assertIn("D3D11 runtime is native-only", source)
        self.assertNotIn("_native_preview_core_quality_fallback_reason", source)
        self.assertNotIn("material quality fallback", source)
        self.assertIn("native_preview_package_path", source)
        self.assertIn("Reloading native D3D11 alignment preview without restarting", source)
        self.assertIn("base_srgb", source)
        self.assertIn("find_native_d3d11_host", source)
        self.assertIn("--preview-package", source)
        self.assertIn("--status-file", source)
        self.assertIn("--parent-hwnd", source)
        self.assertIn("--crash-dir", source)
        self.assertIn("--diagnostic-log", source)
        self.assertIn("enable_material_combiner=False", source)
        self.assertIn("prefer_direct_dds=True", source)
        self.assertIn('"preview/archive_renderer_backend"', source)
        self.assertNotIn("archive_model_preview_renderer_combo", source)
        self.assertNotIn('"--isolated-renderer-host"', source)

    def test_archive_launcher_is_one_shot_and_status_file_based(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("QProcess", source)
        self.assertIn("ArchiveD3D11PackageWorker", source)
        self.assertIn("_start_archive_isolated_preview_package_worker", source)
        self.assertIn("_handle_archive_isolated_package_ready", source)
        self.assertIn("_launch_archive_isolated_preview_result", source)
        self.assertIn("_poll_archive_isolated_renderer_status", source)
        self.assertIn("archive_isolated_renderer_status_timer", source)
        self.assertIn("_clear_archive_isolated_renderer_surface_for_request", source)
        self.assertIn("self.archive_d3d11_preview_host.clear_preview()", source)
        self.assertIn("self.archive_d3d11_preview_host.clear_preview(status_file)", source)
        self.assertIn("self.archive_d3d11_preview_host.load_package(package_dir, status_file, reset_view=True)", source)
        self.assertIn("process.terminate()", source)
        self.assertIn("readyReadStandardError.connect(self._handle_archive_isolated_renderer_stderr)", source)
        self.assertIn("finished.connect(self._handle_archive_isolated_renderer_finished)", source)
        self.assertIn("errorOccurred.connect(self._handle_archive_isolated_renderer_error)", source)
        self.assertIn("_check_archive_isolated_renderer_start_timeout", source)
        self.assertIn("_archive_isolated_renderer_sender_is_current", source)
        self.assertIn("process.disconnect()", source)
        self.assertIn('elif event == "loading":', source)
        self.assertNotIn("waitForFinished(", source)
        self.assertNotIn("readyReadStandardOutput.connect(self._handle_archive_isolated_renderer_stdout)", source)
        self.assertNotIn('"command": "load"', source)
        self.assertNotIn('"command": "shutdown"', source)

    def test_native_d3d11_host_supports_clear_command_for_stale_previews(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("bool clear_preview", source)
        self.assertIn('command == "clear_preview"', source)
        self.assertIn('command == "set_render_tuning"', source)
        self.assertIn("command_set_render_tuning", source)
        self.assertIn("texture_details", source)
        self.assertIn("batches_.clear()", source)
        self.assertIn("Native D3D11 preview cleared", source)
        self.assertIn("native_diagnostics.h", source)
        self.assertIn("package_load_start", source)
        self.assertIn("upload_batches", source)
        self.assertIn("first_frame", source)
        self.assertIn("native_unhandled_exception", Path("native/common/native_diagnostics.h").read_text(encoding="utf-8"))

    def test_native_d3d11_host_releases_model_texture_caches(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        diagnostics_source = Path("native/common/native_diagnostics.h").read_text(encoding="utf-8")

        self.assertIn("void release_model_resources", source)
        self.assertIn("PSSetShaderResources(0, kTotalSrvCount, null_srvs)", source)
        self.assertIn("context_->Flush()", source)
        self.assertIn("batches_.clear()", source)
        self.assertIn('reason_text == "shutdown" || reason_text == "destructor"', source)
        self.assertIn("srv_cache_.clear()", source)
        self.assertIn("texture_info_cache_.clear()", source)
        self.assertIn('release_model_resources("reload")', source)
        self.assertIn('release_model_resources("clear")', source)
        self.assertIn('release_model_resources("shutdown")', source)
        self.assertIn("model_resources_released", source)
        self.assertIn("texture_cache_entries", source)
        self.assertIn("texture_cache_releases", source)
        self.assertIn("estimated_texture_bytes", source)
        self.assertIn("process_working_set_bytes", source)
        self.assertIn("process_private_bytes", source)
        self.assertIn("GetProcessMemoryInfo", diagnostics_source)
        self.assertIn("current_process_memory", diagnostics_source)

    def test_native_d3d11_host_throttles_idle_rendering_and_prunes_srv_cache(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("void request_render()", source)
        self.assertIn("bool should_render() const", source)
        self.assertIn("render_requested_", source)
        self.assertIn("renderer.should_render()", source)
        self.assertIn("MsgWaitForMultipleObjects", source)
        self.assertIn("kIdleWaitMs", source)
        self.assertIn("WM_PAINT", source)
        self.assertIn("WM_SIZE", source)
        self.assertIn("kSrvCacheSoftMaxEntries", source)
        self.assertIn("kSrvCacheSoftMaxBytes", source)
        self.assertIn("prune_srv_cache_if_needed", source)
        self.assertIn("texture_cache_pruned", source)
        self.assertIn('prune_srv_cache_if_needed("pre_upload_soft_cap")', source)
        self.assertIn('prune_srv_cache_if_needed("texture_load_soft_cap")', source)

    def test_native_d3d11_host_rejects_stale_or_invalid_packages_and_exposes_debug_modes(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('release_model_resources("load-missing-package")', source)
        self.assertIn("native D3D11 package validation failed", source)
        self.assertIn("native D3D11 manifest read/parse failed", source)
        self.assertIn("next_batches.empty() || !missing_paths.empty()", source)
        self.assertIn("diagnostic_mode_code", source)
        self.assertIn("render_diagnostic_mode", source)
        self.assertIn("uv_checker", source)
        self.assertIn("material_slot_id", source)
        self.assertIn("layer_masks", source)
        self.assertIn("flags4.y", source)
        self.assertIn("flags4.z", source)
        self.assertIn("base_alpha < max(flags3.w", source)
        self.assertIn("discard;", source)
        self.assertIn("batch.two_sided", source)
        self.assertIn("batch.alpha_threshold", source)

    def test_pyinstaller_includes_host_modules(self) -> None:
        source = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")

        self.assertIn("cdmw.rendering.native_d3d11_host", source)
        self.assertIn("cdmw.rendering.qtquick3d_preview_package", source)
        self.assertIn("cd-texture-dx.exe", source)
        self.assertIn("cdmw-d3d11-preview.exe", source)

    def test_native_host_discovery_uses_env_override(self) -> None:
        from unittest.mock import patch

        from cdmw.rendering.native_d3d11_host import find_native_d3d11_host

        with tempfile.TemporaryDirectory() as temp_dir:
            host_path = Path(temp_dir) / "cdmw-d3d11-preview.exe"
            host_path.write_bytes(b"fake")
            with patch.dict("os.environ", {"CDMW_D3D11_PREVIEW_BIN": str(host_path)}):
                self.assertEqual(host_path, find_native_d3d11_host())


if __name__ == "__main__":
    unittest.main()
