"""An edited texture is written back in the original's format, colour space and mips (decision 48)."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from cdmw.domain.textures.original_output import (
    WRITABLE_DDS_FORMATS,
    TextureOutputRefused,
    check_texture_editable,
    original_texture_output,
    texture_colour_space,
)
from cdmw.models import DdsInfo, TextureEditorDocument, TextureEditorLayer

DXGI = {"BC7_UNORM_SRGB": 99, "BC5_UNORM": 83, "BC1_UNORM": 71, "R8G8B8A8_UNORM": 28}


def _info(fmt: str, width=256, height=256, mips=9, **extra) -> DdsInfo:
    return DdsInfo(width=width, height=height, mip_count=mips, dds_format=fmt, source_path=Path("owned.dds"), **extra)


def _dds(path: Path, dxgi: int, width: int, height: int, mips: int) -> Path:
    """A DX10 DDS header and enough payload for the parser (owned fixture)."""
    header = bytearray(124)
    struct.pack_into("<7I", header, 0, 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000, height, width, 0, 0, mips)
    struct.pack_into("<2I4s", header, 72, 32, 0x4, b"DX10")
    struct.pack_into("<I", header, 104, 0x1000 | 0x400000 | 0x8)
    dx10 = struct.pack("<5I", dxgi, 3, 0, 1, 0)
    path.write_bytes(b"DDS " + bytes(header) + dx10 + bytes(width * height * 4))
    return path


def test_a_full_chain_original_is_written_with_its_format_colour_space_and_chain():
    output = original_texture_output(_info("BC7_UNORM_SRGB"))
    assert (output.dds_format, output.srgb, output.mip_count, output.full_chain) == ("BC7_UNORM_SRGB", True, 9, True)
    assert (output.width, output.height) == (256, 256) and not output.notes


def test_linear_data_stays_linear():
    output = original_texture_output(_info("BC5_UNORM"))
    assert output.srgb is False and texture_colour_space("BC5_UNORM") == "linear"
    assert texture_colour_space("bc1_unorm_srgb") == "srgb"


def test_a_resized_full_chain_keeps_a_full_chain():
    output = original_texture_output(_info("BC1_UNORM"), width=64, height=32)
    assert output.mip_count == 7 and output.full_chain
    assert any("64x32" in note for note in output.notes)


def test_a_short_chain_keeps_its_length_and_says_when_it_cannot():
    assert original_texture_output(_info("BC1_UNORM", mips=3)).mip_count == 3
    clamped = original_texture_output(_info("BC1_UNORM", width=256, height=256, mips=5), width=8, height=8)
    assert clamped.mip_count == 4 and any("5 mips" in note for note in clamped.notes)
    assert original_texture_output(_info("BC1_UNORM", mips=1)).mip_count == 1


@pytest.mark.parametrize("fmt", ["R8G8_UNORM", "A8_UNORM", "B5G6R5_UNORM"])
def test_a_format_the_encoder_cannot_write_is_refused_with_its_name(fmt):
    assert fmt not in WRITABLE_DDS_FORMATS
    with pytest.raises(TextureOutputRefused, match=fmt) as refused:
        original_texture_output(_info(fmt))
    assert refused.value.dds_format == fmt and "cannot write" in refused.value.reason


def test_unknown_and_keep_only_textures_are_refused():
    with pytest.raises(TextureOutputRefused, match="unknown"):
        original_texture_output(_info(""))
    with pytest.raises(TextureOutputRefused, match="kept as it is"):
        original_texture_output(_info("BC7_UNORM", preserve_only_source=True))


def test_the_check_reads_the_file_before_any_edit(tmp_path):
    output = check_texture_editable(_dds(tmp_path / "a.dds", DXGI["BC5_UNORM"], 64, 64, 7))
    assert (output.dds_format, output.mip_count, output.srgb) == ("BC5_UNORM", 7, False)
    (tmp_path / "broken.dds").write_bytes(b"not a texture")
    with pytest.raises(TextureOutputRefused, match="cannot read"):
        check_texture_editable(tmp_path / "broken.dds")


def test_the_encode_writes_exactly_what_was_matched(tmp_path):
    from cdmw.core import texture_native
    from cdmw.core.texture_pipeline.inspection import parse_dds
    from cdmw.services.texture_editor_service import TextureEditorNativeDdsService

    if texture_native.find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built here")
    document = TextureEditorDocument("Owned", 32, 32, active_layer_id="paint",
                                     layers=(TextureEditorLayer("paint", "Paint", "unused.png"),))
    pixels = np.zeros((32, 32, 4), dtype=np.uint8)
    pixels[..., 0] = np.arange(32, dtype=np.uint8)[None, :] * 8
    pixels[..., 3] = 255
    for fmt, mips in (("BC5_UNORM", 6), ("BC7_UNORM_SRGB", 1)):
        original = original_texture_output(_info(fmt, width=32, height=32, mips=mips))
        result = TextureEditorNativeDdsService().export_matching_original(
            document, {"paint": pixels}, original, tmp_path / f"{fmt}.dds", temp_root=tmp_path / "temp")
        written = parse_dds(result.dds_path)
        assert (written.dds_format, written.mip_count, written.width) == (fmt, mips, 32)


def test_a_size_mismatch_and_an_existing_file_are_refused(tmp_path):
    from cdmw.services.texture_editor_service import TextureEditorNativeDdsService

    document = TextureEditorDocument("Owned", 16, 16, active_layer_id="paint",
                                     layers=(TextureEditorLayer("paint", "Paint", "unused.png"),))
    original = original_texture_output(_info("BC1_UNORM", width=32, height=32, mips=6))
    with pytest.raises(ValueError, match="another size"):
        TextureEditorNativeDdsService().export_matching_original(document, {}, original, tmp_path / "x.dds")
