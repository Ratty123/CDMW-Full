from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from cdmw.models import (
    ModelPreviewData,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
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

        self.assertEqual(2, manifest["schema_version"])
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

            self.assertEqual(3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES, geometry_path.stat().st_size)
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
        self.assertIn("dds_direct_upload_candidates", source)
        self.assertIn("dds_direct_uploads", source)
        self.assertIn("dds_upload_formats", source)
        self.assertIn("texture_cache_hits", source)
        self.assertIn("best_material_dds_for_role", source)
        self.assertIn("material_hints", source)
        self.assertIn("detail_tex", source)
        self.assertIn("CREATETEX_FORCE_SRGB", source)
        self.assertIn("CREATETEX_IGNORE_SRGB", source)
        self.assertIn("srgb_color_uploads", source)
        self.assertIn("linear_to_srgb", source)
        self.assertIn("srgb_to_linear", source)
        self.assertIn("begin_mouse_drag", source)
        self.assertIn("kZoomSteps", source)
        self.assertIn("WM_MOUSEWHEEL", source)
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
        self.assertIn("DXGI_FORMAT_BC1_UNORM", source)
        self.assertIn("DXGI_FORMAT_BC3_UNORM", source)
        self.assertIn("DXGI_FORMAT_BC5_UNORM", source)
        self.assertIn("DXGI_FORMAT_BC7_UNORM", source)
        self.assertIn("direct_upload_candidate", source)
        self.assertIn("compressed_family", source)
        self.assertIn("normal_green_inverted", source)

    def test_archive_button_is_separate_from_embedded_renderer_combo(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("archive_isolated_renderer_button", source)
        self.assertIn("archive_d3d11_preview_host", source)
        self.assertIn("low_res_base", source)
        self.assertIn("NativeD3D11PreviewHostFrame", source)
        self.assertIn("_WM_SET_ZOOM", source)
        self.assertIn("base_srgb", source)
        self.assertIn("find_native_d3d11_host", source)
        self.assertIn("--preview-package", source)
        self.assertIn("--status-file", source)
        self.assertIn("--parent-hwnd", source)
        self.assertIn("enable_material_combiner=False", source)
        self.assertIn("prefer_direct_dds=True", source)
        self.assertIn('"preview/archive_renderer_backend"', source)
        self.assertNotIn("ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertNotIn('"--isolated-renderer-host"', source)

    def test_archive_launcher_is_one_shot_and_status_file_based(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("QProcess", source)
        self.assertIn("_launch_archive_isolated_preview_result", source)
        self.assertIn("_poll_archive_isolated_renderer_status", source)
        self.assertIn("archive_isolated_renderer_status_timer", source)
        self.assertIn("process.terminate()", source)
        self.assertIn("readyReadStandardError.connect(self._handle_archive_isolated_renderer_stderr)", source)
        self.assertIn("finished.connect(self._handle_archive_isolated_renderer_finished)", source)
        self.assertIn("errorOccurred.connect(self._handle_archive_isolated_renderer_error)", source)
        self.assertIn("_check_archive_isolated_renderer_start_timeout", source)
        self.assertIn("_archive_isolated_renderer_sender_is_current", source)
        self.assertIn("process.disconnect()", source)
        self.assertIn('elif event == "loading":', source)
        self.assertNotIn("readyReadStandardOutput.connect(self._handle_archive_isolated_renderer_stdout)", source)
        self.assertNotIn('"command": "load"', source)
        self.assertNotIn('"command": "shutdown"', source)

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
