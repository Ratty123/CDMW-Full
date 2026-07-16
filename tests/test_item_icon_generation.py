from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from cdmw.core.item_icon import (
    ItemIconOverrideSpec,
    build_item_icon_payload,
    choose_item_icon_source,
    prepare_fit_pad_icon_png,
    prepare_item_icon_png,
)
from cdmw.core.pipeline import parse_dds


def _fake_dds_bytes(width: int, height: int, *, mips: int = 1, fourcc: bytes = b"DXT1") -> bytes:
    data = bytearray(128)
    data[0:4] = b"DDS "
    struct.pack_into("<I", data, 4 + 0, 124)
    struct.pack_into("<I", data, 4 + 8, height)
    struct.pack_into("<I", data, 4 + 12, width)
    struct.pack_into("<I", data, 4 + 24, mips)
    struct.pack_into("<I", data, 4 + 72, 32)
    struct.pack_into("<I", data, 4 + 76, 0x4)
    data[4 + 80 : 4 + 84] = fourcc
    return bytes(data)


class ItemIconGenerationTests(unittest.TestCase):
    def test_folder_auto_match_requires_unique_high_confidence_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            matched = root / "itemicon_prefab_cd_phm_01_sword_0166.png"
            other = root / "random_preview.png"
            Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(matched)
            Image.new("RGBA", (32, 32), (0, 255, 0, 255)).save(other)

            chosen, candidates, message = choose_item_icon_source(
                root,
                target_path="ui/itemicon/itemicon_prefab_cd_phm_01_sword_0166.dds",
                related_stems=("cd_phm_01_sword_0166",),
            )

            self.assertIsNotNone(chosen)
            self.assertEqual(matched, chosen.path)
            self.assertGreaterEqual(candidates[0].score, 80)
            self.assertIn("exact", message)

    def test_folder_auto_match_reports_ambiguous_top_score(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "itemicon_prefab_cd_phm_01_sword_0166.png"
            second = root / "itemicon_prefab_cd_phm_01_sword_0166.jpg"
            Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(first)
            Image.new("RGB", (32, 32), (0, 255, 0)).save(second)

            chosen, candidates, message = choose_item_icon_source(
                root,
                target_path="ui/itemicon/itemicon_prefab_cd_phm_01_sword_0166.dds",
                related_stems=("cd_phm_01_sword_0166",),
            )

            self.assertIsNone(chosen)
            self.assertEqual(2, len(candidates))
            self.assertIn("ambiguous", message)

    def test_fit_pad_preserves_aspect_ratio_and_exact_target_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "wide.png"
            output = root / "icon.png"
            Image.new("RGBA", (100, 50), (255, 0, 0, 255)).save(source)

            source_size = prepare_fit_pad_icon_png(source, output, 64, 64)

            self.assertEqual((100, 50), source_size)
            with Image.open(output) as image:
                self.assertEqual((64, 64), image.size)
                self.assertEqual((0, 0, 0, 0), image.convert("RGBA").getpixel((0, 0)))
                self.assertEqual((255, 0, 0, 255), image.convert("RGBA").getpixel((32, 32)))

    def test_auto_transparent_removes_opaque_preview_background(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "preview.png"
            output = root / "icon.png"
            image = Image.new("RGBA", (96, 96), (34, 35, 36, 255))
            for y in range(30, 70):
                for x in range(36, 60):
                    image.putpixel((x, y), (210, 40, 20, 255))
            image.save(source)

            result = prepare_item_icon_png(source, output, 64, 64, background_mode="auto_transparent")

            self.assertEqual((96, 96), (result.source_width, result.source_height))
            with Image.open(output) as prepared:
                rgba = prepared.convert("RGBA")
                self.assertEqual((64, 64), rgba.size)
                self.assertLess(rgba.getpixel((0, 0))[3], 16)
                self.assertGreater(rgba.getpixel((32, 32))[3], 240)

    def test_auto_transparent_preserves_existing_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "transparent.png"
            output = root / "icon.png"
            image = Image.new("RGBA", (48, 48), (0, 0, 255, 0))
            for y in range(8, 40):
                for x in range(12, 36):
                    image.putpixel((x, y), (0, 0, 255, 255))
            image.save(source)

            result = prepare_item_icon_png(source, output, 64, 64, background_mode="auto_transparent")

            self.assertEqual((), result.warnings)
            with Image.open(output) as prepared:
                rgba = prepared.convert("RGBA")
                self.assertLess(rgba.getpixel((0, 0))[3], 16)
                self.assertEqual((0, 0, 255), rgba.getpixel((32, 32))[:3])
                self.assertGreater(rgba.getpixel((32, 32))[3], 240)

    def test_auto_transparent_alpha_preview_keeps_dark_foreground_material(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "alpha_preview.png"
            output = root / "icon.png"
            image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
            for y in range(0, 96):
                for x in range(10, 86):
                    image.putpixel((x, y), (48, 48, 48, 255))
            for y in range(24, 72):
                for x in range(30, 66):
                    image.putpixel((x, y), (14, 13, 11, 255))
            image.save(source)

            prepare_item_icon_png(source, output, 64, 64, background_mode="auto_transparent")

            with Image.open(output) as prepared:
                rgba = prepared.convert("RGBA")
                self.assertLess(rgba.getpixel((0, 0))[3], 16)
                self.assertGreater(rgba.getpixel((32, 32))[3], 240)
                self.assertEqual((14, 13, 11), rgba.getpixel((32, 32))[:3])

    def test_auto_transparent_centers_and_pads_object_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "preview.png"
            output = root / "icon.png"
            image = Image.new("RGBA", (100, 100), (20, 20, 20, 255))
            for y in range(42, 58):
                for x in range(20, 80):
                    image.putpixel((x, y), (240, 220, 80, 255))
            image.save(source)

            prepare_item_icon_png(source, output, 64, 64, background_mode="auto_transparent")

            with Image.open(output) as prepared:
                rgba = prepared.convert("RGBA")
                bbox = rgba.getchannel("A").point(lambda value: 255 if value > 16 else 0).getbbox()
                self.assertIsNotNone(bbox)
                left, top, right, bottom = bbox or (0, 0, 0, 0)
                self.assertLessEqual(abs(((left + right) / 2) - 32), 1.5)
                self.assertLessEqual(abs(((top + bottom) / 2) - 32), 1.5)
                self.assertLessEqual(right - left, 56)
                self.assertLessEqual(bottom - top, 56)

    def test_keep_source_preserves_opaque_corners(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "solid.png"
            output = root / "icon.png"
            Image.new("RGBA", (64, 64), (10, 80, 160, 255)).save(source)

            prepare_item_icon_png(source, output, 64, 64, background_mode="keep_source")

            with Image.open(output) as prepared:
                self.assertEqual((10, 80, 160, 255), prepared.convert("RGBA").getpixel((0, 0)))

    def test_target_underlay_composites_processed_icon_over_target_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.png"
            target = root / "target.png"
            output = root / "icon.png"
            image = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
            for y in range(12, 36):
                for x in range(12, 36):
                    image.putpixel((x, y), (255, 0, 0, 255))
            image.save(source)
            Image.new("RGBA", (64, 64), (0, 0, 180, 255)).save(target)

            prepare_item_icon_png(source, output, 64, 64, background_mode="target_underlay", target_underlay_path=target)

            with Image.open(output) as prepared:
                rgba = prepared.convert("RGBA")
                self.assertEqual((0, 0, 180, 255), rgba.getpixel((0, 0)))
                self.assertEqual((255, 0, 0), rgba.getpixel((32, 32))[:3])

    def test_generated_dds_matches_target_template_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "custom_icon.png"
            target = root / "target_icon.dds"
            Image.new("RGBA", (128, 64), (10, 20, 30, 255)).save(source)
            target.write_bytes(_fake_dds_bytes(64, 64, mips=7, fourcc=b"DXT5"))
            seen_formats: list[str] = []

            def fake_native_encode(_source: Path, output: Path, **kwargs: object) -> dict[str, object]:
                dds_format = str(kwargs["dds_format"])
                seen_formats.append(dds_format)
                output.write_bytes(
                    _fake_dds_bytes(
                        int(kwargs["width"]),
                        int(kwargs["height"]),
                        mips=int(kwargs["mip_count"]),
                        fourcc=b"DXT5" if dds_format == "BC3_UNORM" else b"DXT1",
                    )
                )
                return {"status": "encoded", "format": dds_format}

            with patch("cdmw.core.item_icon.encode_dds_with_directxtex", side_effect=fake_native_encode):
                result = build_item_icon_payload(
                    ItemIconOverrideSpec(
                        source_path=source,
                        target_entry=object(),
                        target_path="ui/itemicon/itemicon_prefab_cd_phm_01_sword_0166.dds",
                        source_mode="file",
                    ),
                    target_template_path=target,
                )

            output = root / "generated.dds"
            output.write_bytes(result.payload_data)
            info = parse_dds(output)
            self.assertEqual((64, 64), (info.width, info.height))
            self.assertEqual(7, info.mip_count)
            self.assertEqual("BC3_UNORM", info.dds_format)
            self.assertEqual(["BC3_UNORM"], seen_formats)

    def test_jpeg_source_generated_dds_matches_target_template_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "custom_icon.jpeg"
            target = root / "target_icon.dds"
            Image.new("RGB", (90, 120), (40, 50, 60)).save(source)
            target.write_bytes(_fake_dds_bytes(80, 64, mips=6, fourcc=b"DXT5"))
            seen_formats: list[str] = []

            def fake_native_encode(_source: Path, output: Path, **kwargs: object) -> dict[str, object]:
                dds_format = str(kwargs["dds_format"])
                seen_formats.append(dds_format)
                output.write_bytes(
                    _fake_dds_bytes(
                        int(kwargs["width"]),
                        int(kwargs["height"]),
                        mips=int(kwargs["mip_count"]),
                        fourcc=b"DXT5" if dds_format == "BC3_UNORM" else b"DXT1",
                    )
                )
                return {"status": "encoded", "format": dds_format}

            with patch("cdmw.core.item_icon.encode_dds_with_directxtex", side_effect=fake_native_encode):
                result = build_item_icon_payload(
                    ItemIconOverrideSpec(
                        source_path=source,
                        target_entry=object(),
                        target_path="ui/itemicon/icon_prefab_cd_phm_01_sword_0166.dds",
                        source_mode="file",
                    ),
                    target_template_path=target,
                )

            output = root / "generated.dds"
            output.write_bytes(result.payload_data)
            info = parse_dds(output)
            self.assertEqual((80, 64), (info.width, info.height))
            self.assertEqual(6, info.mip_count)
            self.assertEqual("BC3_UNORM", info.dds_format)
            self.assertEqual(["BC3_UNORM"], seen_formats)


if __name__ == "__main__":
    unittest.main()
