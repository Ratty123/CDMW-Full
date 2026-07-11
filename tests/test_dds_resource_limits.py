from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cdmw.core import archive_extraction, texture_native
from cdmw.core.dds_native import DdsNativeInfo, inspect_dds_native
from cdmw.core.dds_resource_limits import DDS_MAX_DIMENSION, DDS_MAX_PAYLOAD_BYTES
from cdmw.core.pipeline import parse_dds
from cdmw.models import ArchiveEntry


def _bc_dds(*, width: int = 4, height: int = 4, mip_count: int = 1, complete: bool = True) -> bytes:
    header = bytearray(124)
    struct.pack_into("<I", header, 0, 124)
    struct.pack_into("<I", header, 4, 0x0002100F)
    struct.pack_into("<I", header, 8, height)
    struct.pack_into("<I", header, 12, width)
    struct.pack_into("<I", header, 24, mip_count)
    struct.pack_into("<I", header, 72, 32)
    struct.pack_into("<I", header, 76, 0x4)
    header[80:84] = b"DXT1"
    payload_size = 0
    level_width = width
    level_height = height
    levels = mip_count if complete else 1
    for _level in range(levels):
        payload_size += max(1, (level_width + 3) // 4) * max(1, (level_height + 3) // 4) * 8
        level_width = max(1, level_width // 2)
        level_height = max(1, level_height // 2)
    return b"DDS " + bytes(header) + (b"\0" * payload_size)


def _partial_dds_header(*, compressed_size: int, decompressed_size: int) -> bytes:
    header = bytearray(_bc_dds())
    struct.pack_into("<I", header, 32, compressed_size)
    struct.pack_into("<I", header, 36, decompressed_size)
    return bytes(header[:128])


def _rgba_dx10_header(*, width: int, height: int) -> bytes:
    header = bytearray(124)
    struct.pack_into("<I", header, 0, 124)
    struct.pack_into("<I", header, 8, height)
    struct.pack_into("<I", header, 12, width)
    struct.pack_into("<I", header, 24, 1)
    struct.pack_into("<I", header, 72, 32)
    struct.pack_into("<I", header, 76, 0x4)
    header[80:84] = b"DX10"
    dx10 = bytearray(20)
    struct.pack_into("<I", dx10, 0, 28)
    return b"DDS " + bytes(header) + bytes(dx10)


def _archive_entry(*, orig_size: int, comp_size: int = 1, flags: int = 1) -> ArchiveEntry:
    return ArchiveEntry(
        path="character/texture/test.dds",
        pamt_path=Path("test.pamt"),
        paz_file=Path("test.paz"),
        offset=0,
        comp_size=comp_size,
        orig_size=orig_size,
        flags=flags,
        paz_index=0,
    )


class DdsResourceLimitTests(unittest.TestCase):
    def test_native_inspector_rejects_oversized_dimensions_and_impossible_mips(self) -> None:
        oversized = bytearray(_bc_dds())
        struct.pack_into("<I", oversized, 16, DDS_MAX_DIMENSION + 1)
        oversized_info = inspect_dds_native(bytes(oversized))

        impossible_mips = bytearray(_bc_dds())
        struct.pack_into("<I", impossible_mips, 28, 0xFFFFFFFF)
        mip_info = inspect_dds_native(bytes(impossible_mips))

        self.assertFalse(oversized_info.supported_compressed)
        self.assertIn("resource limit", oversized_info.reason)
        self.assertFalse(mip_info.supported_compressed)
        self.assertIn("mip count", mip_info.reason)

    def test_native_inspector_requires_every_declared_mip_payload(self) -> None:
        truncated = inspect_dds_native(_bc_dds(width=8, height=8, mip_count=2, complete=False))
        complete = inspect_dds_native(_bc_dds(width=8, height=8, mip_count=2))

        self.assertFalse(truncated.supported_compressed)
        self.assertEqual((), truncated.mip_levels)
        self.assertIn("truncated", truncated.reason)
        self.assertTrue(complete.supported_compressed)
        self.assertEqual(2, len(complete.mip_levels))

    def test_native_inspector_rejects_payload_byte_count_over_resource_ceiling(self) -> None:
        header = _rgba_dx10_header(width=DDS_MAX_DIMENSION, height=DDS_MAX_DIMENSION)

        info = inspect_dds_native(header, payload_size=DDS_MAX_PAYLOAD_BYTES * 4)

        self.assertFalse(info.supported_uncompressed)
        self.assertIn("resource limit", info.reason)

    def test_parse_dds_rejects_dimensions_before_consumers_can_allocate(self) -> None:
        malformed = bytearray(_bc_dds())
        struct.pack_into("<I", malformed, 16, 0)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "zero_width.dds"
            path.write_bytes(malformed)
            with self.assertRaisesRegex(ValueError, "dimensions must be positive"):
                parse_dds(path)

    def test_directxtex_decode_rejects_decoded_resource_ceiling_before_process_start(self) -> None:
        texture_native.directxtex_texture_failure_reports(clear=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "cd-texture-dx.exe"
            source = root / "large.dds"
            binary.write_bytes(b"stub")
            source.write_bytes(_bc_dds())
            large_info = DdsNativeInfo(
                width=DDS_MAX_DIMENSION,
                height=DDS_MAX_DIMENSION,
                mip_count=1,
                format_name="BC1_UNORM",
                bytes_per_block=8,
                mip_levels=(),
                supported_compressed=True,
                compressed_family="bc1",
            )
            with (
                patch.object(texture_native, "find_directxtex_texture_binary", return_value=binary),
                patch.object(texture_native, "inspect_dds_native_path", return_value=large_info),
                patch.object(
                    texture_native,
                    "run_process_with_cancellation",
                    side_effect=AssertionError("decoder process must not start"),
                ),
            ):
                result = texture_native.decode_dds_preview_with_directxtex(
                    source,
                    root / "preview.png",
                    max_dimension=512,
                )
            reports = texture_native.directxtex_texture_failure_reports(clear=True)

        self.assertIsNone(result)
        self.assertEqual("unsafe_dds_input", reports[-1]["reason"])

    def test_partial_dds_rejects_oversized_output_before_lz4(self) -> None:
        header = _partial_dds_header(compressed_size=1, decompressed_size=DDS_MAX_PAYLOAD_BYTES + 1)
        fake_lz4 = SimpleNamespace(decompress=Mock(side_effect=AssertionError("must not decompress")))
        with (
            patch.object(archive_extraction, "get_archive_partial_dds_header", return_value=header),
            patch.object(archive_extraction, "lz4_block", fake_lz4),
            self.assertRaisesRegex(ValueError, "resource limit"),
        ):
            archive_extraction.reconstruct_partial_dds(
                _archive_entry(orig_size=1),
                (b"\0" * 128) + b"x",
            )
        fake_lz4.decompress.assert_not_called()

    def test_partial_dds_checks_actual_decompressed_block_size(self) -> None:
        header = _partial_dds_header(compressed_size=1, decompressed_size=8)
        fake_lz4 = SimpleNamespace(decompress=Mock(return_value=b"short"))
        with (
            patch.object(archive_extraction, "get_archive_partial_dds_header", return_value=header),
            patch.object(archive_extraction, "lz4_block", fake_lz4),
            self.assertRaisesRegex(ValueError, "unexpected size"),
        ):
            archive_extraction.reconstruct_partial_dds(
                _archive_entry(orig_size=8),
                (b"\0" * 128) + b"x",
            )

    def test_sparse_and_lz4_dds_reject_oversized_output_before_allocation(self) -> None:
        entry = _archive_entry(orig_size=DDS_MAX_PAYLOAD_BYTES + 1, flags=2)
        fake_lz4 = SimpleNamespace(decompress=Mock(side_effect=AssertionError("must not decompress")))
        with self.assertRaisesRegex(ValueError, "resource limit"):
            archive_extraction.maybe_reconstruct_sparse_dds(entry, _bc_dds())
        with (
            patch.object(archive_extraction, "lz4_block", fake_lz4),
            self.assertRaisesRegex(ValueError, "resource limit"),
        ):
            archive_extraction._decode_archive_entry_data(entry, b"x")
        fake_lz4.decompress.assert_not_called()


if __name__ == "__main__":
    unittest.main()
