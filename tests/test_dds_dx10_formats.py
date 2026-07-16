from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cdmw.core.pipeline import parse_dds


def _minimal_dx10_dds(dxgi_format: int, *, width: int = 4, height: int = 4) -> bytes:
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = int(height).to_bytes(4, "little")
    header[12:16] = int(width).to_bytes(4, "little")
    header[24:28] = (1).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = b"DX10"
    dx10 = bytearray(20)
    dx10[0:4] = int(dxgi_format).to_bytes(4, "little")
    dx10[4:8] = (3).to_bytes(4, "little")
    return b"DDS " + bytes(header) + bytes(dx10) + b"\x00" * 64


class DdsDx10FormatTests(unittest.TestCase):
    def test_parse_dds_accepts_uncompressed_dx10_preview_formats(self) -> None:
        cases = {
            2: "R32G32B32A32_FLOAT",
            10: "R16G16B16A16_FLOAT",
            24: "R10G10B10A2_UNORM",
            41: "R32_FLOAT",
            54: "R16_FLOAT",
            61: "R8_UNORM",
            88: "B8G8R8X8_UNORM",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for dxgi_format, expected_texconv in cases.items():
                path = root / f"dxgi_{dxgi_format}.dds"
                path.write_bytes(_minimal_dx10_dds(dxgi_format))

                info = parse_dds(path)

                self.assertEqual(info.dds_format, expected_texconv)


if __name__ == "__main__":
    unittest.main()
