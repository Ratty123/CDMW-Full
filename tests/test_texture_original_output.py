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


@pytest.mark.parametrize("fmt", ["BC5_SNORM", "BC4_SNORM", "BC6H_UF16", "BC6H_SF16", "R16G16B16A16_FLOAT",
                                 "R32_FLOAT", "R16_UNORM", "R16G16B16A16_SNORM"])
def test_an_original_the_8_bit_document_cannot_hold_is_refused(fmt):
    """H4: float, BC6H, SNORM and 16-bit originals lose range or precision in an RGBA8 document."""
    with pytest.raises(TextureOutputRefused, match="more than 8 bits") as refused:
        original_texture_output(_info(fmt))
    assert refused.value.dds_format == fmt


def test_a_texture_marked_precision_sensitive_is_refused_whatever_its_name():
    with pytest.raises(TextureOutputRefused, match="more than 8 bits"):
        original_texture_output(_info("BC7_UNORM", precision_sensitive=True))


def test_srgb_colour_is_stored_once_not_encoded_twice(tmp_path):
    """H3: the flattened PNG's pixels are already sRGB. Encoded as R8G8B8A8_UNORM_SRGB the
    stored bytes must be the document's own values, not a second gamma curve over them."""
    from cdmw.core import texture_native
    from cdmw.services.texture_editor_service import TextureEditorNativeDdsService

    if texture_native.find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built here")
    document = TextureEditorDocument("Grey", 4, 4, active_layer_id="paint",
                                     layers=(TextureEditorLayer("paint", "Paint", "unused.png"),))
    pixels = np.full((4, 4, 4), 128, dtype=np.uint8)
    pixels[..., 3] = 255
    for fmt in ("R8G8B8A8_UNORM_SRGB", "R8G8B8A8_UNORM"):
        original = original_texture_output(_info(fmt, width=4, height=4, mips=1))
        result = TextureEditorNativeDdsService().export_matching_original(
            document, {"paint": pixels}, original, tmp_path / f"{fmt}.dds", temp_root=tmp_path / "temp")
        data = result.dds_path.read_bytes()
        offset = 148 if data[84:88] == b"DX10" else 128
        texel = data[offset:offset + 4]
        assert abs(texel[0] - 128) <= 1 and texel[3] == 255, (fmt, tuple(texel))


@pytest.mark.parametrize("layout", ["cubemap", "cubemap_dx10", "array", "volume"])
def test_cubemaps_arrays_and_volumes_are_refused_before_an_edit(tmp_path, layout):
    import struct

    path = _dds(tmp_path / f"{layout}.dds", DXGI["BC7_UNORM_SRGB"], 64, 64, 1)
    data = bytearray(path.read_bytes())
    if layout == "cubemap":
        struct.pack_into("<I", data, 112, 0x200 | 0xFC00)
    elif layout == "cubemap_dx10":
        struct.pack_into("<I", data, 136, 0x4)
    elif layout == "array":
        struct.pack_into("<I", data, 140, 6)
    else:
        struct.pack_into("<I", data, 132, 4)
    path.write_bytes(bytes(data))
    with pytest.raises(TextureOutputRefused, match="one flat image"):
        check_texture_editable(path)


@pytest.mark.parametrize("fault", ["truncated", "wrong_size"])
def test_an_incomplete_or_wrong_size_encode_saves_nothing(tmp_path, monkeypatch, fault):
    from cdmw.core import texture_native
    from cdmw.services.texture_editor_service import TextureEditorNativeDdsService

    def fake_encode(png, out, *, dds_format, width, height, mip_count, **_kwargs):
        written_width = width * 2 if fault == "wrong_size" else width
        _dds(Path(out), DXGI["BC1_UNORM"], written_width, height, mip_count)
        if fault == "truncated":
            Path(out).write_bytes(Path(out).read_bytes()[:148 + 8])
        return {"format": dds_format}

    monkeypatch.setattr(texture_native, "find_directxtex_texture_binary", lambda: Path("cd-texture-dx.exe"))
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", fake_encode)
    document = TextureEditorDocument("Owned", 32, 32, active_layer_id="paint",
                                     layers=(TextureEditorLayer("paint", "Paint", "unused.png"),))
    pixels = np.zeros((32, 32, 4), dtype=np.uint8)
    original = original_texture_output(_info("BC1_UNORM", width=32, height=32, mips=1))
    target = tmp_path / "out.dds"
    with pytest.raises(TextureOutputRefused, match="nothing was saved"):
        TextureEditorNativeDdsService().export_matching_original(document, {"paint": pixels}, original, target)
    assert not target.exists()
