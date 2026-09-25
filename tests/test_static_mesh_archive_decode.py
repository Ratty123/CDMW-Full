from __future__ import annotations

import ctypes
import hashlib
import json
import struct
import subprocess
from pathlib import Path

import lz4.block
import pytest

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.models import ArchiveEntry, ModelPreviewRenderSettings
from cdmw.rendering.native_preview_core import build_native_preview_core_job

ROOT = Path(__file__).resolve().parents[1]


def pamlod_payload(table_padding: int = 0, materials: int = 1, no_texture: bool = False) -> tuple[bytes, bytes]:
    """Three independently aligned LODs: two compressed, one stored plain."""
    count = 3
    geometry = (0x50 + count * materials * 0x210 + count * 12 + 15) & ~15
    prefix = bytearray(geometry)
    struct.pack_into("<II", prefix, 0, count, geometry)
    struct.pack_into("<ffffff", prefix, 16, 0, 0, 0, 1, 1, 1)
    for index in range(count * materials):
        part = index % materials
        record = 0x50 + index * 0x210
        struct.pack_into("<IIII", prefix, record, 3, 3, part * 3, part * 3)
        name = (b"stone", b"wood")[part]
        texture = b"dds\0" if no_texture else name + b".dds\0"
        prefix[record + 16:record + 16 + len(texture)] = texture
        prefix[record + 272:record + 273 + len(name)] = name + b"\0"
    geometry_bytes = bytearray(materials * 66)
    for part in range(materials):
        for index, xyz in enumerate(((0, 0, 0), (65535, 0, 0), (0, 65535, 0))):
            struct.pack_into("<HHH", geometry_bytes, (part * 3 + index) * 20, *xyz)
        struct.pack_into("<HHH", geometry_bytes, materials * 60 + part * 6, 0, 1, 2)
    stored, decoded = bytearray(prefix), bytearray(prefix)
    for index in range(count):
        packed = lz4.block.compress(bytes(geometry_bytes), store_size=False) if index < 2 else bytes(geometry_bytes)
        for target, block, compressed in ((stored, packed, len(packed) if index < 2 else 0), (decoded, geometry_bytes, 0)):
            target.extend(bytes((-len(target)) % 16))
            struct.pack_into("<III", target, geometry - count * 12 - table_padding + index * 12, len(target), len(geometry_bytes), compressed)
            target.extend(block)
    return bytes(stored), bytes(decoded)


def _entry(tmp_path: Path, payload: bytes, original_size: int, prepared: bool = False) -> ArchiveEntry:
    path = tmp_path / "payload.pamlod"
    path.write_bytes(payload)
    return ArchiveEntry(
        path="object/stone.pamlod", pamt_path=tmp_path / "0.pamt", paz_file=path,
        offset=0, comp_size=len(payload), orig_size=original_size, flags=1, paz_index=0,
        prepared_path=path if prepared else None,
        prepared_size=len(payload) if prepared else None,
        prepared_sha256=hashlib.sha256(payload).hexdigest() if prepared else "",
        prepared_note="PartialRaw" if prepared else "",
    )


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("padding", [0, 4, 8, 12])
def test_partial_pamlod_decodes_each_lod_and_preserves_metadata(tmp_path, prepared, padding):
    raw, expected = pamlod_payload(padding)
    entry = _entry(tmp_path, raw, len(expected), prepared)
    result, decoded, note = read_archive_entry_data(entry)
    assert result == expected
    assert decoded and "PartialPAMLOD" in note and "PartialRaw" not in note
    # Already decoded worker payloads are not decompressed a second time.
    entry.prepared_path = tmp_path / "decoded.pamlod"
    entry.prepared_path.write_bytes(expected)
    entry.prepared_size = len(expected)
    entry.prepared_sha256 = hashlib.sha256(expected).hexdigest()
    assert read_archive_entry_data(entry)[0] == expected


def _damaged_pamlod(damage):
    raw, expected = pamlod_payload()
    payload = bytearray(raw)
    geometry = struct.unpack_from("<I", payload, 4)[0]
    table = geometry - 36
    if damage == "truncated":
        payload.pop()
    elif damage == "offset":
        struct.pack_into("<I", payload, table, len(payload) + 1)
    elif damage == "overlap":
        struct.pack_into("<I", payload, table + 12, geometry)
    elif damage == "decoded_size":
        struct.pack_into("<I", payload, table + 4, 1 << 30)
    elif damage == "lz4":
        payload[geometry:geometry + 4] = b"\xff\xff\xff\xff"
    return bytes(payload), len(expected) + (1 if damage == "archive_size" else 0)


@pytest.mark.parametrize("damage", ["truncated", "offset", "overlap", "decoded_size", "archive_size", "lz4"])
def test_partial_pamlod_rejects_invalid_blocks(tmp_path, damage):
    payload, original_size = _damaged_pamlod(damage)
    entry = _entry(tmp_path, payload, original_size, True)
    with pytest.raises((ValueError, lz4.block.LZ4BlockError)):
        read_archive_entry_data(entry)


def _native_decode(entry):
    library = ROOT / "native/cdmw_full_archive_core/build/Release/cdmw-full-archive-core.dll"
    if not library.is_file():
        pytest.skip("Build the full archive native core first")
    dll = ctypes.CDLL(str(library))
    decode = dll.cdmw_full_archive_decode_entry_utf8
    decode.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint64, ctypes.c_uint64,
                       ctypes.c_uint64, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_size_t,
                       ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t,
                       ctypes.c_void_p, ctypes.c_size_t]
    decode.restype = ctypes.c_int
    output = ctypes.create_string_buffer(entry.orig_size)
    required = ctypes.c_size_t()
    note, error = ctypes.create_string_buffer(256), ctypes.create_string_buffer(4096)
    status = decode(entry.path.encode(), str(entry.paz_file).encode(), 0, entry.comp_size, entry.orig_size, 1,
                    output, len(output), ctypes.byref(required), note, len(note), error, len(error))
    return status, output.raw[:required.value], note.value, error.value.decode()


@pytest.mark.parametrize("padding", [0, 4, 8, 12])
def test_worker_native_decoder_matches_python(tmp_path, padding):
    raw, expected = pamlod_payload(padding)
    status, payload, note, error = _native_decode(_entry(tmp_path, raw, len(expected)))
    assert status == 0, error
    assert payload == expected and note == b"PartialPAMLOD"


@pytest.mark.parametrize("version", [0x1802, 0x01001806])
def test_worker_native_decoder_preserves_pam_versions_and_trailers(tmp_path, version):
    from tests.test_archive_prepared_entry_read import _partial_pam_payload
    raw, expected = _partial_pam_payload()
    raw = raw[:4] + struct.pack("<I", version) + raw[8:]
    expected = expected[:4] + struct.pack("<I", version) + expected[8:]
    entry = _entry(tmp_path, raw, len(expected))
    entry.path = "object/stone.pam"
    status, payload, note, error = _native_decode(entry)
    assert status == 0, error
    assert payload == expected and note == b"PartialPAM"


@pytest.mark.parametrize("damage", ["truncated", "offset", "overlap", "decoded_size", "archive_size", "lz4"])
def test_worker_native_decoder_rejects_invalid_blocks(tmp_path, damage):
    payload, original_size = _damaged_pamlod(damage)
    status, _, _, error = _native_decode(_entry(tmp_path, payload, original_size))
    assert status != 0 and error


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("padding", [0, 4, 8, 12])
@pytest.mark.parametrize("materials,no_texture", [(1, False), (2, True)])
def test_native_preview_decodes_raw_and_old_prepared_pamlod(tmp_path, prepared, padding, materials, no_texture):
    binary = ROOT / "native/cdmw_preview_core/build/Release/cdmw-preview-core.exe"
    if not binary.is_file():
        pytest.skip("Build Preview Core first")
    raw, expected = pamlod_payload(padding, materials, no_texture)
    entry = _entry(tmp_path, raw, len(expected), prepared)
    output = tmp_path / "package"
    output.mkdir()
    job = build_native_preview_core_job(
        entry, cache_root=tmp_path / "cache", output_root=output,
        dependency_entries=(entry,), dependency_entries_complete=True,
        render_settings=ModelPreviewRenderSettings(use_textures_by_default=False),
    )
    job_path, report_path = tmp_path / "job.json", tmp_path / "report.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    subprocess.run([str(binary), "preview-job", str(job_path), str(report_path)],
                   check=True, capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    report = json.loads(report_path.read_text())
    assert report["status"] == "ok", report.get("fallback_reason")
    assert report["face_count"] == materials and report["lod_count"] == 3
    assert report["batch_count"] == materials
    manifest = json.loads((output / "manifest.json").read_text())
    assert [part["material_name"] for part in manifest["batches"]] == ["stone", "wood"][:materials]


def test_python_pamlod_preserves_parts_with_placeholder_texture_names():
    from cdmw.modding.mesh_parser import parse_pamlod
    from cdmw.core.model_preview import _read_pamlod_entries
    _, decoded = pamlod_payload(materials=2, no_texture=True)
    geometry = struct.unpack_from("<I", decoded, 4)[0]
    assert len(_read_pamlod_entries(decoded, geometry)) == 6
    parsed = parse_pamlod(decoded, "object/stone.pamlod")
    assert [part.material for part in parsed.submeshes] == ["stone", "wood"]
    assert all(part.texture == "" for part in parsed.submeshes)


def test_pamlod_placeholder_does_not_match_texture_filename_suffix():
    from cdmw.core.model_preview import _read_pamlod_entries
    data = bytearray(0x400)
    # At the suffix, the preceding string/count bytes also resemble a valid
    # descriptor. Only the start of the NUL-terminated field is authoritative.
    texture = 0x60
    struct.pack_into("<IIII", data, texture - 16, 1357, 4398, 85, 450)
    data[texture:texture + 15] = b"cd_rope_05.dds\0\0"
    entries = _read_pamlod_entries(data, len(data))
    assert len(entries) == 1 and entries[0].texture_name == "cd_rope_05.dds"
