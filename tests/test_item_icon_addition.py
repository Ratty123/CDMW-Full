"""Gates for new-item icons: a generated DDS at a new path, named the way the row expects."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.item_icon_addition import (  # noqa: E402
    ItemIconAdditionError,
    build_new_item_icon,
    icon_string_for_stem,
    icon_target_path,
)
from cdmw.core.stringinfo_table import stringinfo_key  # noqa: E402
from cdmw.core.texture_pipeline.inspection import parse_dds  # noqa: E402
from cdmw.models import ArchiveEntry  # noqa: E402


def _fake_dds_bytes(width: int, height: int, *, mips: int = 1, fourcc: bytes = b"DXT5") -> bytes:
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


REFERENCE = ArchiveEntry(
    "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_0109.dds", Path("0019/0.pamt"), Path("0019/3.paz"),
    0, 65664, 65664, 0x02, 3,
)


class NamingTests(unittest.TestCase):
    def test_string_and_path_follow_the_shipped_convention(self) -> None:
        self.assertEqual(icon_string_for_stem("cd_phm_01_sword_9109"), "ItemIcon_Prefab_cd_phm_01_sword_9109")
        self.assertEqual(icon_target_path("ItemIcon_Prefab_CD_PHM_01_Sword_0109"), "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_0109.dds")
        for bad in ("", "with space", "../x", "_leading"):
            with self.assertRaises(ItemIconAdditionError):
                icon_string_for_stem(bad)
        with self.assertRaises(ItemIconAdditionError):
            icon_target_path("Prefab_cd_phm_01_sword_9109")
        with self.assertRaises(ItemIconAdditionError):
            icon_target_path("ItemIcon_Prefab_bad name")


class BuildTests(unittest.TestCase):
    def test_a_new_icon_is_shaped_like_the_reference_and_carries_its_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "render.png"
            Image.new("RGBA", (128, 64), (10, 20, 30, 255)).save(source)
            reference = _fake_dds_bytes(256, 256, mips=1)
            seen: list[dict[str, object]] = []

            def fake_native_encode(_source: Path, output: Path, **kwargs: object) -> dict[str, object]:
                seen.append(dict(kwargs))
                output.write_bytes(_fake_dds_bytes(int(kwargs["width"]), int(kwargs["height"]), mips=int(kwargs["mip_count"])))
                return {"status": "encoded"}

            with patch("cdmw.core.item_icon.encode_dds_with_directxtex", side_effect=fake_native_encode):
                icon = build_new_item_icon(
                    source_path=source,
                    reference_entry=REFERENCE,
                    reference_payload=reference,
                    icon_string="ItemIcon_Prefab_cd_phm_01_sword_9109",
                    existing_paths=lambda path: path == REFERENCE.path,
                )
            self.assertEqual(icon.target_path, "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_9109.dds")
            self.assertEqual(icon.icon_string, "ItemIcon_Prefab_cd_phm_01_sword_9109")
            self.assertEqual(icon.icon_hash, stringinfo_key("ItemIcon_Prefab_cd_phm_01_sword_9109"))
            self.assertEqual(seen[0]["dds_format"], "BC3_UNORM")
            self.assertEqual((seen[0]["width"], seen[0]["height"], seen[0]["mip_count"]), (256, 256, 1))
            produced = root / "out.dds"
            produced.write_bytes(icon.payload_data)
            info = parse_dds(produced)
            self.assertEqual((info.width, info.height, info.dds_format), (256, 256, "BC3_UNORM"))
            self.assertEqual(icon.add_request.path, icon.target_path)
            self.assertEqual(icon.add_request.pamt_path, REFERENCE.pamt_path)
            self.assertEqual(icon.add_request.flags, REFERENCE.flags)
            self.assertEqual(icon.add_request.payload_data, icon.payload_data)
            self.assertEqual(icon.build.target_path, icon.target_path)

    def test_refusals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "render.png"
            Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(source)
            with self.assertRaisesRegex(ItemIconAdditionError, "already exists"):
                build_new_item_icon(
                    source_path=source, reference_entry=REFERENCE, reference_payload=b"x",
                    icon_string="ItemIcon_Prefab_CD_PHM_01_Sword_0109", existing_paths=lambda path: True,
                )
            with self.assertRaisesRegex(ItemIconAdditionError, "empty"):
                build_new_item_icon(source_path=source, reference_entry=REFERENCE, reference_payload=b"", icon_string="ItemIcon_Prefab_x")
            with self.assertRaises(ItemIconAdditionError):
                build_new_item_icon(source_path=source, reference_entry=REFERENCE, reference_payload=b"x", icon_string="nope")


if __name__ == "__main__":
    unittest.main()
