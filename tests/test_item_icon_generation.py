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

    def test_generated_dds_matches_target_template_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "custom_icon.png"
            target = root / "target_icon.dds"
            texconv = root / "texconv.exe"
            Image.new("RGBA", (128, 64), (10, 20, 30, 255)).save(source)
            target.write_bytes(_fake_dds_bytes(64, 64, mips=7, fourcc=b"DXT5"))
            texconv.write_bytes(b"fake")
            seen_command: list[str] = []

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                seen_command[:] = command
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                fmt = str(command[command.index("-f") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips, fourcc=b"DXT5" if fmt == "BC3_UNORM" else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.item_icon.run_process_with_cancellation", side_effect=fake_texconv):
                result = build_item_icon_payload(
                    ItemIconOverrideSpec(
                        source_path=source,
                        target_entry=object(),
                        target_path="ui/itemicon/itemicon_prefab_cd_phm_01_sword_0166.dds",
                        source_mode="file",
                    ),
                    target_template_path=target,
                    texconv_path=texconv,
                )

            output = root / "generated.dds"
            output.write_bytes(result.payload_data)
            info = parse_dds(output)
            self.assertEqual((64, 64), (info.width, info.height))
            self.assertEqual(7, info.mip_count)
            self.assertEqual("BC3_UNORM", info.texconv_format)
            self.assertIn("BC3_UNORM", seen_command)

    def test_jpeg_source_generated_dds_matches_target_template_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "custom_icon.jpeg"
            target = root / "target_icon.dds"
            texconv = root / "texconv.exe"
            Image.new("RGB", (90, 120), (40, 50, 60)).save(source)
            target.write_bytes(_fake_dds_bytes(80, 64, mips=6, fourcc=b"DXT5"))
            texconv.write_bytes(b"fake")
            seen_command: list[str] = []

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                seen_command[:] = command
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                fmt = str(command[command.index("-f") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips, fourcc=b"DXT5" if fmt == "BC3_UNORM" else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.item_icon.run_process_with_cancellation", side_effect=fake_texconv):
                result = build_item_icon_payload(
                    ItemIconOverrideSpec(
                        source_path=source,
                        target_entry=object(),
                        target_path="ui/itemicon/icon_prefab_cd_phm_01_sword_0166.dds",
                        source_mode="file",
                    ),
                    target_template_path=target,
                    texconv_path=texconv,
                )

            output = root / "generated.dds"
            output.write_bytes(result.payload_data)
            info = parse_dds(output)
            self.assertEqual((80, 64), (info.width, info.height))
            self.assertEqual(6, info.mip_count)
            self.assertEqual("BC3_UNORM", info.texconv_format)
            self.assertIn("BC3_UNORM", seen_command)


if __name__ == "__main__":
    unittest.main()
