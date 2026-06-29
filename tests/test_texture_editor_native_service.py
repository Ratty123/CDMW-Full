from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset, texture_editor_dds_preset_warning
from cdmw.models import TextureEditorDocument, TextureEditorLayer
from cdmw.services.texture_editor_service import (
    NativeTextureEditorExportError,
    TextureEditorNativeDdsOptions,
    TextureEditorNativeDdsService,
)


def _minimal_dx10_dds(dxgi_format: int, *, width: int = 8, height: int = 8, mip_count: int = 4) -> bytes:
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = int(height).to_bytes(4, "little")
    header[12:16] = int(width).to_bytes(4, "little")
    header[24:28] = max(1, int(mip_count)).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = b"DX10"
    dx10 = bytearray(20)
    dx10[0:4] = int(dxgi_format).to_bytes(4, "little")
    dx10[4:8] = (3).to_bytes(4, "little")
    return b"DDS " + bytes(header) + bytes(dx10) + (b"\x00" * 4096)


def _document() -> tuple[TextureEditorDocument, dict[str, np.ndarray]]:
    pixels = np.zeros((8, 8, 4), dtype=np.uint8)
    pixels[..., 0] = 128
    pixels[..., 3] = 255
    document = TextureEditorDocument(
        "native_service",
        8,
        8,
        active_layer_id="base",
        layers=(TextureEditorLayer("base", "Base", ""),),
    )
    return document, {"base": pixels}


class TextureEditorNativeServiceTests(unittest.TestCase):
    def test_preset_rules_choose_requested_formats_mips_and_warnings(self) -> None:
        base = resolve_texture_editor_dds_preset("base_color", width=8, height=8)
        normal = resolve_texture_editor_dds_preset("normal", width=8, height=8)
        mask = resolve_texture_editor_dds_preset("mask_packed", width=8, height=8)
        ui_single = resolve_texture_editor_dds_preset("ui_icon", width=8, height=8)
        ui_rgba_full = resolve_texture_editor_dds_preset("ui_icon", width=8, height=8, dds_format="RGBA", mip_mode="full")
        scalar_r16 = resolve_texture_editor_dds_preset("height_scalar", width=8, height=8, dds_format="R16")

        self.assertEqual(("BC7_UNORM_SRGB", True, 4), (base.dds_format, base.srgb, base.mip_count))
        self.assertEqual(("BC5_UNORM", False, 4), (normal.dds_format, normal.srgb, normal.mip_count))
        self.assertEqual(("BC7_UNORM", False, 4), (mask.dds_format, mask.srgb, mask.mip_count))
        self.assertIn("channel", texture_editor_dds_preset_warning("mask_packed").lower())
        self.assertEqual(("BC7_UNORM_SRGB", 1), (ui_single.dds_format, ui_single.mip_count))
        self.assertEqual(("R8G8B8A8_UNORM_SRGB", 4), (ui_rgba_full.dds_format, ui_rgba_full.mip_count))
        self.assertEqual("R16_UNORM", scalar_r16.dds_format)

    def test_export_flattens_to_png_calls_native_and_normalizes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "cd-texture-dx.exe"
            binary.write_bytes(b"fake")
            output = root / "out.dds"
            document, pixels = _document()

            def fake_encode(png_path: Path, output_dds_path: Path, **kwargs: object) -> dict[str, object]:
                self.assertTrue(Path(png_path).is_file())
                self.assertEqual(output, Path(output_dds_path))
                self.assertEqual("BC7_UNORM_SRGB", kwargs["dds_format"])
                self.assertEqual(4, kwargs["mip_count"])
                self.assertFalse(kwargs["overwrite"])
                output.write_bytes(_minimal_dx10_dds(99))
                return {
                    "status": "encoded",
                    "native_backend": "directxtex",
                    "format": "DXGI_FORMAT_BC7_UNORM_SRGB",
                    "mip_count": 4,
                    "encode_ms": 1.5,
                }

            with (
                patch("cdmw.services.texture_editor_service.texture_native.find_directxtex_texture_binary", return_value=binary),
                patch("cdmw.services.texture_editor_service.texture_native.encode_dds_with_directxtex", side_effect=fake_encode),
            ):
                result = TextureEditorNativeDdsService().export_dds(
                    document,
                    pixels,
                    TextureEditorNativeDdsOptions(output_path=output, overwrite=False, temp_root=root / "temp"),
                )

        self.assertEqual(output.resolve(), result.dds_path)
        self.assertEqual("directxtex", result.report["native_backend"])
        self.assertEqual("BC7_UNORM_SRGB", result.report["format"])
        self.assertEqual(99, result.report["dxgi_format"])
        self.assertGreater(result.report["output_byte_size"], 0)

    def test_missing_native_fails_before_encode_without_texconv_fallback(self) -> None:
        document, pixels = _document()
        with patch("cdmw.services.texture_editor_service.texture_native.find_directxtex_texture_binary", return_value=None):
            with patch("cdmw.services.texture_editor_service.texture_native.encode_dds_with_directxtex") as encode_mock:
                with self.assertRaises(NativeTextureEditorExportError):
                    TextureEditorNativeDdsService().export_dds(
                        document,
                        pixels,
                        TextureEditorNativeDdsOptions(output_path=Path("out.dds")),
                    )
        encode_mock.assert_not_called()
        source = Path("cdmw/services/texture_editor_service.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("texconv", source)

    def test_preview_writes_supplied_preview_path_and_loads_rgba(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "cd-texture-dx.exe"
            binary.write_bytes(b"fake")
            output = root / "preview.dds"
            preview = root / "preview.png"
            document, pixels = _document()

            def fake_encode(_png_path: Path, output_dds_path: Path, **_kwargs: object) -> dict[str, object]:
                Path(output_dds_path).write_bytes(_minimal_dx10_dds(98))
                return {"status": "encoded", "native_backend": "directxtex", "format": "DXGI_FORMAT_BC7_UNORM"}

            def fake_decode(dds_path: Path, output_png_path: Path, **kwargs: object) -> dict[str, object]:
                self.assertEqual(output.resolve(), Path(dds_path))
                self.assertEqual(preview.resolve(), Path(output_png_path))
                self.assertEqual((root / "temp").resolve(), Path(kwargs["temp_root"]))
                Image.fromarray(np.full((8, 8, 4), 255, dtype=np.uint8), "RGBA").save(output_png_path)
                return {"status": "decoded", "native_backend": "directxtex", "format": "BC7_UNORM"}

            with (
                patch("cdmw.services.texture_editor_service.texture_native.find_directxtex_texture_binary", return_value=binary),
                patch("cdmw.services.texture_editor_service.texture_native.encode_dds_with_directxtex", side_effect=fake_encode),
                patch("cdmw.services.texture_editor_service.texture_native.decode_dds_preview_with_directxtex", side_effect=fake_decode),
            ):
                result = TextureEditorNativeDdsService().preview_compressed(
                    document,
                    pixels,
                    TextureEditorNativeDdsOptions(
                        output_path=output,
                        preview_output_path=preview,
                        temp_root=root / "temp",
                    ),
                )

        self.assertEqual(preview.resolve(), result.preview_path)
        self.assertEqual((8, 8, 4), result.preview_rgba.shape)
        self.assertEqual("decoded", result.preview_report["status"])


if __name__ == "__main__":
    unittest.main()
