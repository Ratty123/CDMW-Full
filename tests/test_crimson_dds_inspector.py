from __future__ import annotations

import struct
import unittest

from cdmw.core.archive import _dds_surface_size
from cdmw.core.pipeline import classify_crimson_dds_vpath_last4, inspect_crimson_dds


def _dds(
    width: int = 4,
    height: int = 4,
    *,
    mips: int = 3,
    depth: int = 0,
    fourcc: bytes = b"DXT1",
    dxgi_format: int | None = None,
    last4: int = 0,
) -> bytes:
    header = bytearray(124)
    struct.pack_into("<I", header, 0, 124)
    struct.pack_into("<I", header, 4, 0x0002100F)
    struct.pack_into("<I", header, 8, height)
    struct.pack_into("<I", header, 12, width)
    struct.pack_into("<I", header, 20, depth)
    struct.pack_into("<I", header, 24, mips)
    struct.pack_into("<I", header, 72, 32)
    struct.pack_into("<I", header, 76, 0x4)
    header[80:84] = b"DX10" if dxgi_format is not None else fourcc
    struct.pack_into("<I", header, 120, last4)
    if dxgi_format is None:
        return b"DDS " + bytes(header) + b"\x00" * 64
    dx10 = bytearray(20)
    struct.pack_into("<I", dx10, 0, dxgi_format)
    struct.pack_into("<I", dx10, 4, 3)
    struct.pack_into("<I", dx10, 12, 1)
    return b"DDS " + bytes(header) + bytes(dx10) + b"\x00" * 64


class CrimsonDdsInspectorTests(unittest.TestCase):
    def test_path_prefix_last4_rules(self) -> None:
        self.assertEqual(0x1580, classify_crimson_dds_vpath_last4("/ui/icon/sample.dds"))
        self.assertEqual(0x0480, classify_crimson_dds_vpath_last4("character/texture/body_n.dds"))
        self.assertEqual(0x1380, classify_crimson_dds_vpath_last4("/character/texture/body_tattoo_o.dds"))
        self.assertEqual(0x1280, classify_crimson_dds_vpath_last4("/character/texture/body_o.dds"))
        self.assertIsNone(classify_crimson_dds_vpath_last4("/object/texture/body_o.dds"))

    def test_dxt1_uses_format_fallback_when_path_is_unknown(self) -> None:
        info = inspect_crimson_dds(_dds(fourcc=b"DXT1"), vpath="/object/texture/sample.dds")

        self.assertEqual("BC1_UNORM", info.dds_format)
        self.assertEqual(12, info.last4_format_derived)
        self.assertEqual(12, info.effective_last4)
        self.assertEqual(8, info.block_bytes)

    def test_path_classifier_overrides_format_fallback(self) -> None:
        info = inspect_crimson_dds(_dds(fourcc=b"DXT5"), vpath="/ui/icon/sample.dds")

        self.assertEqual("BC3_UNORM", info.dds_format)
        self.assertEqual(15, info.last4_format_derived)
        self.assertEqual(0x1580, info.last4_path_class)
        self.assertEqual(0x1580, info.effective_last4)

    def test_dx10_bc7_reports_pathc_requirement(self) -> None:
        info = inspect_crimson_dds(_dds(dxgi_format=98), vpath="/object/texture/bc7.dds")
        codes = {finding.code for finding in info.findings}

        self.assertTrue(info.is_dx10)
        self.assertEqual("BC7_UNORM", info.dds_format)
        self.assertEqual(16, info.block_bytes)
        self.assertTrue(info.requires_pathc)
        self.assertIn("requires_pathc", codes)

    def test_dx10_bc6h_signed_format_has_sixteen_byte_blocks(self) -> None:
        info = inspect_crimson_dds(_dds(dxgi_format=96), vpath="/object/texture/bc6h.dds")

        self.assertEqual("BC6H_SF16", info.dds_format)
        self.assertEqual(16, info.block_bytes)
        self.assertEqual(16, _dds_surface_size(4, 4, 96, b"DX10"))

    def test_malformed_dds_reports_fatal_findings(self) -> None:
        short_info = inspect_crimson_dds(b"DDS ")
        bad_magic_info = inspect_crimson_dds(b"NOPE" + b"\x00" * 124)

        self.assertTrue(short_info.has_fatal_findings)
        self.assertIn("header_too_short", {finding.code for finding in short_info.findings})
        self.assertTrue(bad_magic_info.has_fatal_findings)
        self.assertIn("bad_magic", {finding.code for finding in bad_magic_info.findings})

    def test_missing_mips_and_non_power_of_two_dimensions_are_warnings(self) -> None:
        info = inspect_crimson_dds(_dds(width=60, height=32, mips=1, fourcc=b"DXT5"))
        warning_codes = {finding.code for finding in info.findings if finding.severity == "warning"}

        self.assertIn("depth_zero", warning_codes)
        self.assertIn("missing_mips", warning_codes)
        self.assertIn("non_power_of_two_dims", warning_codes)


if __name__ == "__main__":
    unittest.main()
