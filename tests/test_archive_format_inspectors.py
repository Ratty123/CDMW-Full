"""Archive Browser inspectors for formats that used to show only a strings dump.

Shader cache entries (`.padxil`, `.pars`), reflection-serialized objects
(`.parg`, `.pasg`, `.pcg`, `.save`, `.uianiminit`), the exact `.pae`/`.paem`
object graph, UI fonts (`.ttf`) and animated cursors (`.ani`). Every fixture is
built here from the documented layouts; no game file is needed.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest

from cdmw.core.archive_preview_result_builder import build_archive_preview_result
from cdmw.core.archive_reflect_preview import build_effect_tree_section, build_reflect_object_preview
from cdmw.core.archive_shader_preview import (
    ShaderContainerError,
    build_shader_cache_preview,
    read_dxbc_chunks,
)
from cdmw.core.archive_ui_resource_preview import (
    UiResourceError,
    build_ui_resource_preview,
    read_animated_cursor,
    read_font_info,
)
from cdmw.models import ArchiveEntry

EFFECT_FIXTURES = Path(__file__).parent / "fixtures" / "effects"


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """An unencrypted, uncompressed archive entry backed by its own PAZ file."""

    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))

    def make(path: str, payload: bytes, *, package: str = "0008") -> ArchiveEntry:
        folder = tmp_path / package
        folder.mkdir(parents=True, exist_ok=True)
        paz = folder / f"{len(list(folder.glob('*.paz')))}.paz"
        paz.write_bytes(payload)
        return ArchiveEntry(path, folder / "0.pamt", paz, 0, len(payload), len(payload), 0, 0)

    return make


# -- shader cache ------------------------------------------------------------


def dxbc(chunks: list[tuple[bytes, bytes]]) -> bytes:
    header_size = 32 + 4 * len(chunks)
    offsets, body = [], b""
    for fourcc, data in chunks:
        offsets.append(header_size + len(body))
        body += fourcc + struct.pack("<I", len(data)) + data
    total = header_size + len(body)
    return b"DXBC" + bytes(16) + struct.pack("<HHII", 1, 0, total, len(chunks)) + struct.pack(f"<{len(chunks)}I", *offsets) + body


def root_signature() -> bytes:
    """Version 1.1: a one-range SRV table, a root CBV, and one static sampler."""

    header = 24
    parameters = header
    table_payload = parameters + 2 * 12
    ranges = table_payload + 8
    cbv_payload = ranges + 24
    samplers = cbv_payload + 12
    data = struct.pack("<6I", 2, 2, parameters, 1, samplers, 0x1)
    data += struct.pack("<III", 0, 5, table_payload)  # descriptor table, pixel
    data += struct.pack("<III", 2, 0, cbv_payload)  # root CBV, all stages
    data += struct.pack("<II", 1, ranges)
    data += struct.pack("<6I", 0, 4, 0, 1, 0, 0)  # SRV t0-t3 space 1
    data += struct.pack("<III", 0, 2147420894, 0)  # b0 in the AMD intrinsics space
    data += struct.pack("<4If3I2f3I", 0x15, 3, 3, 3, 0.0, 1, 0, 0, 0.0, 3.402823466e38, 7, 4, 0)
    return data


def signature(elements: list[tuple[str, int, int, int]]) -> bytes:
    """ISG1/OSG1: (semantic, index, register, mask) per element, float components."""

    names = b""
    name_offsets = []
    table_end = 8 + 32 * len(elements)
    for name, *_rest in elements:
        name_offsets.append(table_end + len(names))
        names += name.encode() + b"\0"
    rows = b"".join(
        struct.pack("<6IBBHI", 0, name_offsets[i], index, 0, 3, register, mask, 0, 0, 0)
        for i, (_name, index, register, mask) in enumerate(elements)
    )
    return struct.pack("<II", len(elements), 8) + rows + names


def pixel_shader_padxil() -> bytes:
    program = struct.pack("<II", (0 << 16) | 0x66, 10) + struct.pack("<4I", 0x4C495844, 0x106, 16, 32) + bytes(32)
    runtime = bytes(24) + bytes([0, 0, 0, 0, 2, 1, 0, 2]) + bytes(4) + bytes(12) + struct.pack("<I", 1)
    strings = b"\0MainPS\0"
    strings += bytes(-len(strings) % 4)
    psv = struct.pack("<I", len(runtime)) + runtime
    psv += struct.pack("<II", 1, 24) + struct.pack("<6I", 3, 1, 0, 0, 2, 0)  # SRV Texture2D t0 space 1
    psv += struct.pack("<I", len(strings)) + strings + struct.pack("<I", 0)
    container = dxbc(
        [
            (b"SFI0", struct.pack("<Q", 0x4000)),
            (b"ISG1", signature([("SV_Position", 0, 0, 0xF), ("TEXCOORD", 0, 1, 0x3)])),
            (b"OSG1", signature([("SV_Target", 0, 0, 0xF)])),
            (b"PSV0", psv),
            (b"HASH", struct.pack("<I", 0) + bytes(range(16))),
            (b"DXIL", program),
        ]
    )
    total = 36 + len(container)
    return b"PASC" + struct.pack("<IIII", 8, total, 61, 36) + bytes(range(16)) + container


def test_root_signature_lists_parameters_ranges_and_samplers():
    preview = build_shader_cache_preview(dxbc([(b"RTS0", root_signature())]), "shadercache__/d3d12/windows/sky.pars", extension=".pars")

    text = preview.preview_text
    assert preview.metadata_label == "Root Signature"
    assert "- Version: 1.1" in text
    assert "- Flags: allow input assembler layout" in text
    assert "[0] Descriptor table (pixel), 1 range" in text
    assert "SRV t0-t3, space 1" in text
    assert "[1] Root CBV (all): b0, space 2147420894 (AMD shader-intrinsics extension slot)" in text
    assert "s7, space 4 (all): min linear, mag linear, mip linear; clamp/clamp/clamp" in text


def test_padxil_reports_stage_entry_point_signatures_and_bindings():
    preview = build_shader_cache_preview(pixel_shader_padxil(), "shadercache__/d3d12/windows/a_b.padxil", extension=".padxil")

    text = preview.preview_text
    assert preview.metadata_label == "Pixel Shader"
    assert "- Stage: Pixel shader" in text
    assert "- Shader model: 6.6 (DXIL 1.6)" in text
    assert "- Entry point: MainPS" in text
    assert "- Required features: wave ops" in text
    assert "SRV Texture2D  t0, space 1" in text
    assert "SV_Position  float.xyzw  (v0)" in text
    assert "TEXCOORD  float.xy  (v1)" in text
    assert "SV_Target  float.xyzw  (v0)" in text
    assert "- Shader hash: 000102030405060708090a0b0c0d0e0f" in text


def test_library_shaders_name_their_functions_and_resources_from_rdat():
    strings = b"\0RayGenMain\0g_sceneTexture\0"
    strings += bytes(-len(strings) % 4)
    functions = struct.pack("<II", 1, 44) + struct.pack("<11I", 1, 1, 0, 0, 7, 0, 0, 0, 0, 0, 0)
    resources = struct.pack("<II", 1, 32) + struct.pack("<8I", 0, 2, 0, 3, 5, 5, 12, 0)
    parts = [(1, strings), (3, resources), (4, functions)]
    offsets, body = [], b""
    table_size = 8 + 4 * len(parts)
    for part_type, part in parts:
        offsets.append(table_size + len(body))
        body += struct.pack("<II", part_type, len(part)) + part
    rdat = struct.pack("<II", 0x10, len(parts)) + struct.pack(f"<{len(parts)}I", *offsets) + body
    program = struct.pack("<II", (6 << 16) | 0x66, 10) + struct.pack("<4I", 0x4C495844, 0x106, 16, 0)
    container = dxbc([(b"RDAT", rdat), (b"DXIL", program)])

    text = build_shader_cache_preview(container, "x.padxil", extension=".padxil").preview_text

    assert "- Stage: Library shader" in text
    assert "RayGenMain  (Ray generation)" in text
    assert "SRV Texture2D  t5, space 3  g_sceneTexture" in text


def test_a_truncated_container_is_refused_not_guessed():
    data = pixel_shader_padxil()
    with pytest.raises(ShaderContainerError):
        build_shader_cache_preview(data[:-10], "x.padxil", extension=".padxil")
    with pytest.raises(ShaderContainerError):
        read_dxbc_chunks(b"DXBC" + bytes(28))


def test_shader_cache_entries_preview_through_the_archive_browser(stored):
    shader = build_archive_preview_result(stored("shadercache__/d3d12/windows/a_b.padxil", pixel_shader_padxil()))
    signature_result = build_archive_preview_result(stored("shadercache__/d3d12/windows/sky.pars", dxbc([(b"RTS0", root_signature())])))

    assert shader.preview_text.startswith("D3D12 shader cache entry for")
    assert "Pixel Shader" in shader.metadata_summary
    assert signature_result.preview_text.startswith("D3D12 root signature for")
    assert "Root Signature" in signature_result.metadata_summary


# -- reflection objects --------------------------------------------------------


def _text(value: str) -> bytes:
    raw = value.encode()
    return struct.pack("<I", len(raw)) + raw


def _member(name: str, type_name: str, kind: int, size: int) -> bytes:
    return _text(name) + _text(type_name) + struct.pack("<4H", kind, size, 0, 0)


def save_preset(*, prefix: bytes = b"") -> bytes:
    """A two-type reflection container: typed values, an array and an object pointer."""

    types = _text("FieldSaveData") + struct.pack("<H", 7)
    types += _member("_saveVersion", "uint32", 0, 4)
    types += _member("_ownerLevelName", "staticstringA", 1, 1)
    types += _member("_originSpawnTransform", "Transform", 0, 40)
    types += _member("_aliasNameHash", "HashCode32", 0, 4)
    types += _member("_gimmickInfoKey", "GimmickInfoKey", 0, 4)
    types += _member("_points", "float3", 3, 12)
    types += _member("_child", "ChildData", 5, 8)
    types += _text("ChildData") + struct.pack("<H", 1) + _member("_mesh", "staticstringA", 1, 1)
    header = struct.pack("<HHH", 0xFFFF, 4, 0) + bytes(8) + struct.pack("<IH", 15, 2) + types + struct.pack("<I", 0)
    blob_offset = len(header) + 28

    blob = struct.pack("<H", 1) + bytes([0x5F]) + struct.pack("<HB", 0, 0) + b"\0"
    blob += struct.pack("<I", 6) + _text("Node_Test")
    blob += struct.pack("<10f", 1, 1, 1, 0, 0.5, 0, 0.8660254, 10, 20, 30)
    blob += struct.pack("<I", 0x866C7489) + struct.pack("<I", 1006161)
    blob += b"\0" + struct.pack("<I", 2) + struct.pack("<6f", 1, 2, 3, 4, 5, 6)
    blob += b"\x01"
    child = struct.pack("<H", 1) + b"\x01" + struct.pack("<HB", 1, 0) + struct.pack("<Q", 0)
    site = blob_offset + len(blob) + len(child)
    pointee_body = struct.pack("<HH", 0, 0) + _text("effect/mesh/test.pam")
    child += struct.pack("<I", site + 4) + pointee_body + struct.pack("<I", len(pointee_body))
    blob += child
    data_header = struct.pack("<III", 1, blob_offset + len(blob), 0) + b"\xff" * 8 + struct.pack("<II", blob_offset, len(blob))
    return prefix + header + data_header + blob


def test_reflection_objects_render_their_graph_with_game_value_types():
    preview = build_reflect_object_preview(save_preset(), "gamedata/savepreset/bin/node_test.save", extension=".save")

    text = preview.bundle.preview_text
    assert preview.bundle.metadata_label == "Save Preset"
    assert "- Root object: FieldSaveData" in text
    assert "- Decode: complete (every blob byte accounted for)" in text
    assert '_ownerLevelName = "Node_Test"' in text
    assert "_originSpawnTransform = scale (1, 1, 1), rotation (0, 0.5, 0, 0.866025), position (10, 20, 30)" in text
    assert "_aliasNameHash = 0x866c7489" in text
    assert "_gimmickInfoKey = 1006161" in text
    assert "_points = float3[2] [(1, 2, 3), (4, 5, 6)]" in text
    assert '_child: ChildData\n    _mesh = "effect/mesh/test.pam"' in text
    assert preview.reference_names == ("effect/mesh/test.pam",)


def convex_geometry(revision: int = 15) -> bytes:
    """One ConvexHull: a tetrahedron with four triangular faces.

    Revision 15 puts a null byte before every container's count; revision 14
    writes the count alone, as the game's revision-14 `.pcg` files do.
    """

    types = _text("ConvexGeometry") + struct.pack("<H", 1) + _member("_convexHullList", "ConvexHull", 6, 0)
    types += _text("ConvexHull") + struct.pack("<H", 5)
    types += _member("_vertices", "float3", 3, 12)
    types += _member("_faceLinks", "uint16", 3, 2)
    types += _member("_firstFaceVertexIndices", "uint16", 3, 2)
    types += _member("_faceNumIndices", "uint16", 3, 2)
    types += _member("_indices", "uint8", 3, 1)
    header = struct.pack("<HHH", 0xFFFF, 4, 0) + bytes(8) + struct.pack("<IH", revision, 2) + types + struct.pack("<I", 0)
    blob_offset = len(header) + 28
    flag = b"\0" if revision >= 15 else b""

    def array(layout: str, values: list) -> bytes:
        flat = [component for value in values for component in (value if isinstance(value, tuple) else (value,))]
        return flag + struct.pack("<I", len(values)) + struct.pack(f"<{len(flat)}{layout}", *flat)

    indices = [0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3]
    members = array("f", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)])
    members += array("H", [0] * 12) + array("H", [0, 3, 6, 9]) + array("H", [3, 3, 3, 3]) + array("B", indices)
    blob = struct.pack("<H", 1) + b"\x01" + struct.pack("<HB", 0, 0) + b"\0"
    blob += flag + struct.pack("<I", 1) + b"\0" + struct.pack("<III", 0, 0, 0)
    element = struct.pack("<H", 1) + b"\x1f" + struct.pack("<HB", 1, 0) + struct.pack("<Q", 0)
    site = blob_offset + len(blob) + len(element)
    pointee_body = struct.pack("<HH", 0, 0) + members
    blob += element + struct.pack("<I", site + 4) + pointee_body + struct.pack("<I", len(pointee_body))
    data_header = struct.pack("<III", 1, blob_offset + len(blob), 0) + b"\xff" * 8 + struct.pack("<II", blob_offset, len(blob))
    return header + data_header + blob


@pytest.mark.parametrize("revision", [15, 14])
def test_convex_geometry_opens_as_a_3d_model_of_its_hulls(stored, revision):
    result = build_archive_preview_result(stored("object/00_common/test_hull.pcg", convex_geometry(revision)))

    assert "- Decode: complete" in result.preview_text
    assert result.preferred_view == "model"
    model = result.preview_model
    assert model is not None and model.format == "pcg"
    assert model.mesh_count == 1
    assert model.face_count == 4
    assert model.meshes[0].indices == [0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3]


def test_ui_animation_states_skip_their_four_zero_bytes():
    preview = build_reflect_object_preview(save_preset(prefix=bytes(4)), "sequencer/03_ui_seq/a.uianiminit", extension=".uianiminit")

    assert "- Layout: 4 zero bytes, then the reflection container" in preview.bundle.preview_text
    assert "- Decode: complete" in preview.bundle.preview_text


def test_an_empty_container_is_named_empty_instead_of_falling_back():
    data = bytes(4) + struct.pack("<HHH", 0xFFFF, 4, 0) + bytes(8) + struct.pack("<IH", 15, 0) + bytes(12)

    preview = build_reflect_object_preview(data, "miscellaneous/inputpresetb.save", extension=".save")

    assert preview.bundle.metadata_label == "Save Preset (empty)"
    assert "- Root object: none; the container declares no types" in preview.bundle.preview_text


def test_reflection_objects_preview_through_the_archive_browser(stored):
    result = build_archive_preview_result(stored("gamedata/savepreset/bin/node_test.save", save_preset()))

    assert result.preview_text.startswith("Save preset inspector for gamedata/savepreset/bin/node_test.save")
    assert "Save Preset" in result.metadata_summary
    assert [reference.reference_name for reference in result.model_texture_references] == ["effect/mesh/test.pam"]


def test_effect_inspector_leads_with_the_exact_object_graph(stored):
    emitter = (EFFECT_FIXTURES / "cdem_standard_fire_large_fire_ember_001a.paem").read_bytes()

    section = build_effect_tree_section(emitter, extension=".paem")
    result = build_archive_preview_result(stored("effect/binary__/emitter/cdem_standard_fire_large_fire_ember_001a.paem", emitter))

    assert section[0] == "Decoded object graph:"
    assert "- Decode: complete (every blob byte accounted for)" in section
    assert '  _emitterDataName = "emitter/cdem_standard_fire_large_fire_ember_001a"' in section
    assert result.preview_text.startswith("PAE effect inspector for")
    assert "Decoded object graph:" in result.preview_text
    assert build_effect_tree_section(b"PARC" + bytes(12) + b"junk", extension=".paem") == []


# -- fonts and animated cursors -----------------------------------------------


def minimal_font() -> bytes:
    """name/maxp/head/OS2/cmap only: enough to describe, not enough to rasterize."""

    def name_table() -> bytes:
        records = [(1, "Test Sans"), (2, "Regular"), (4, "Test Sans Regular")]
        strings = b""
        rows = b""
        for name_id, text in records:
            raw = text.encode("utf-16-be")
            rows += struct.pack(">6H", 3, 1, 0x409, name_id, len(raw), len(strings))
            strings += raw
        return struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + rows + strings

    maxp = struct.pack(">IH", 0x00005000, 3)
    head = bytes(18) + struct.pack(">H", 1000) + bytes(32)
    os2 = struct.pack(">HhHHH", 4, 500, 700, 5, 0) + bytes(48) + b"TEST" + bytes(34)
    # cmap format 4: 'A'-'C' map to glyphs 1-3, plus the closing segment.
    segments = [(0x41, 0x43, -0x40), (0xFFFF, 0xFFFF, 1)]
    seg_x2 = 2 * len(segments)
    format4 = struct.pack(">HHHHHHH", 4, 0, 0, seg_x2, 0, 0, 0)
    format4 += b"".join(struct.pack(">H", end) for _start, end, _delta in segments) + b"\0\0"
    format4 += b"".join(struct.pack(">H", start) for start, _end, _delta in segments)
    format4 += b"".join(struct.pack(">h", delta) for _start, _end, delta in segments)
    format4 += b"\0\0" * len(segments)
    format4 = format4[:2] + struct.pack(">H", len(format4)) + format4[4:]
    cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + format4
    tables = sorted({b"OS/2": os2, b"cmap": cmap, b"head": head, b"maxp": maxp, b"name": name_table()}.items())
    offset = 12 + 16 * len(tables)
    directory, body = b"", b""
    for tag, data in tables:
        directory += struct.pack(">4sIII", tag, 0, offset + len(body), len(data))
        body += data + bytes(-len(data) % 4)
    return struct.pack(">IHHHH", 0x00010000, len(tables), 0, 0, 0) + directory + body


def test_font_metadata_and_coverage_come_from_its_tables():
    info = read_font_info(minimal_font())

    assert info.names["Family"] == "Test Sans"
    assert info.names["Full name"] == "Test Sans Regular"
    assert info.glyph_count == 3
    assert info.units_per_em == 1000
    assert info.weight_class == 700
    assert info.vendor == "TEST"
    assert info.code_points == frozenset({0x41, 0x42, 0x43})
    preview = build_ui_resource_preview(minimal_font(), "ui/fonts/test.ttf", extension=".ttf", render_image=False)
    assert "- Weight class: 700 (Bold)" in preview.bundle.preview_text
    assert "Basic Latin (U+0020-U+007E): 3" in preview.bundle.preview_text


def test_a_font_freetype_cannot_rasterize_keeps_its_description(stored):
    result = build_archive_preview_result(stored("ui/fonts/test.ttf", minimal_font()))

    assert result.preview_text.startswith("Font preview for ui/fonts/test.ttf")
    assert "Font" in result.metadata_summary
    assert "could not be rendered" in result.detail_text
    with pytest.raises(UiResourceError):
        read_font_info(b"not a font at all")


def animated_cursor() -> bytes:
    from PIL import Image

    frames = []
    for colour in ((255, 0, 0, 255), (0, 0, 255, 255)):
        buffer = io.BytesIO()
        Image.new("RGBA", (16, 16), colour).save(buffer, format="ICO", sizes=[(16, 16)])
        icon = bytearray(buffer.getvalue())
        icon[2:4] = b"\x02\x00"  # cursor
        icon[10:14] = struct.pack("<HH", 3, 5)  # hotspot
        frames.append(bytes(icon))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return tag + struct.pack("<I", len(body)) + body + bytes(len(body) & 1)

    anih = struct.pack("<9I", 36, 2, 2, 0, 0, 0, 0, 6, 1)
    frames_list = chunk(b"LIST", b"fram" + b"".join(chunk(b"icon", frame) for frame in frames))
    body = b"ACON" + chunk(b"anih", anih) + chunk(b"rate", struct.pack("<2I", 6, 12)) + frames_list
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_animated_cursor_lists_frames_and_renders_a_strip(stored):
    cursor = read_animated_cursor(animated_cursor())
    result = build_archive_preview_result(stored("ui/cursor/test.ani", animated_cursor()))

    assert len(cursor.frames) == 2
    assert cursor.rates == (6, 12)
    assert result.preferred_view == "image"
    assert Path(result.preview_image_path).is_file()
    assert "- Default frame time: 6 jiffies (100 ms)" in result.preview_text
    assert "[1] cursor, 16 x 16" in result.preview_text
    assert "hotspot 3,5" in result.preview_text


# -- tree impostors ---------------------------------------------------------------


def impostor_descriptor(atlas: int = 1024, views: int = 8) -> bytes:
    floats = struct.pack("<10f", 0.0, 1.5, 0.0, -1.0, 0.0, -1.0, 1.0, 3.0, 0.9, 1.6)
    return b"IMP " + bytes([0, 1, 0, 0]) + bytes(8) + floats + struct.pack("<III", atlas, views, 1) + bytes(4)


def test_impostor_descriptor_names_its_atlases_and_grid():
    from cdmw.core.archive_impostor_preview import ImpostorError, build_impostor_preview

    preview = build_impostor_preview(impostor_descriptor(), "tree/impostor/bush_alder_01.imp")

    assert preview.atlas_paths == (
        "tree/impostor/bush_alder_01_impostor_color.dds",
        "tree/impostor/bush_alder_01_impostor_depth.dds",
    )
    assert "- Atlas size: 1024 px (matches the shipped atlases)" in preview.bundle.preview_text
    assert "- Views per side: 8 (8 x 8 grid in the colour atlas)" in preview.bundle.preview_text
    with pytest.raises(ImpostorError):
        build_impostor_preview(impostor_descriptor()[:-1], "x.imp")


def test_impostor_preview_lists_its_atlases_in_asset_family(stored):
    result = build_archive_preview_result(stored("tree/impostor/bush_alder_01.imp", impostor_descriptor()))

    assert result.preview_text.startswith("Tree impostor descriptor for tree/impostor/bush_alder_01.imp")
    assert "Tree Impostor" in result.metadata_summary
    assert {reference.reference_name for reference in result.model_texture_references} >= {
        "tree/impostor/bush_alder_01_impostor_color.dds", "tree/impostor/bush_alder_01_impostor_depth.dds",
    }


# -- sound banks --------------------------------------------------------------


def sound_bank() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return kind + struct.pack("<I", len(payload)) + payload

    def sound(object_id: int, plugin: int, media: int) -> bytes:
        body = struct.pack("<IIBI", object_id, plugin, 0, media) + struct.pack("<IB", 0, 0) + bytes(4)
        return struct.pack("<BI", 2, len(body)) + body

    event = struct.pack("<BI", 4, 8) + struct.pack("<II", 77, 0)
    objects = [sound(10, 0x00040001, 42), sound(11, 0x00040001, 99), sound(12, 0x00650002, 5), event]
    hirc = struct.pack("<I", len(objects)) + b"".join(objects)
    return (
        chunk(b"BKHD", struct.pack("<IIII", 150, 1234, 0, 0))
        + chunk(b"DIDX", struct.pack("<III", 42, 0, 4))
        + chunk(b"DATA", b"RIFF")
        + chunk(b"HIRC", hirc)
    )


def test_bank_preview_lists_object_types_and_where_each_sound_plays_from():
    from cdmw.core.archive_media_preview import build_bnk_soundbank_preview

    text, _detail = build_bnk_soundbank_preview(sound_bank())

    assert "  Sound: 3" in text and "  Event: 1" in text
    assert "- Sounds with media: 2 (1 in this bank, 1 elsewhere, usually a loose numeric .wem)" in text
    assert "- Generator sounds (no media): 1" in text
    assert "object 10: media 42.wem (in this bank), in memory, Vorbis" in text
    assert "object 11: media 99.wem (not in this bank), in memory, Vorbis" in text
    assert "object 12: generator plugin 0x00650002" in text
    assert "Readable strings" not in text
