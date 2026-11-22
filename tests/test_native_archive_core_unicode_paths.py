"""The full archive core works under folders whose names the ANSI code page cannot spell (2026-11-22).

Its paths arrive as UTF-8, but MSVC's ``std::filesystem::path::string()``
narrows through the ANSI code page and throws ``std::system_error`` for a
letter outside it: Cyrillic or CJK on English Windows. Building an index of a
game whose archives hold a file twice (override ranking reads the package
folder names) and reconstructing a partial DDS (the PATHC lookup) both failed
under such a folder. The core now converts its paths with ``u8string()``.

The library tested is ``CDMW_FULL_ARCHIVE_CORE_DLL`` when set (a fresh build),
else the built one; a test skips when neither exists.
"""

from __future__ import annotations

import ctypes
import os
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="the ANSI code page narrowing is MSVC's")

# Letters outside every Western ANSI code page, and one outside the BMP.
FOLDER_NAMES = ("Моды CDMW", "模组", "mods \U0001f600")


@pytest.fixture(scope="module")
def library():
    path = Path(os.environ.get("CDMW_FULL_ARCHIVE_CORE_DLL")
                or ROOT / "native/cdmw_full_archive_backend/build/Release/cdmw-full-archive-core.dll")
    if not path.is_file():
        pytest.skip(f"{path} is not built")
    return ctypes.CDLL(str(path))


def _package(folder: Path, data: bytes = b"hello") -> None:
    """One PAMT listing ``file.txt``, stored raw in its PAZ, as test_native_long_paths writes it."""
    names = struct.pack("<I", 0xFFFFFFFF) + bytes([8]) + b"file.txt"
    folder.mkdir(parents=True)
    (folder / "0.paz").write_bytes(data)
    (folder / "0.pamt").write_bytes(
        struct.pack("<7I", 0, 1, 0, 0, 0, 0, 0) + struct.pack("<I", len(names)) + names
        + struct.pack("<II", 0, 1) + struct.pack("<IIIIHH", 0, 0, len(data), len(data), 0, 0))


@pytest.mark.parametrize("name", FOLDER_NAMES)
def test_an_index_with_an_overridden_file_builds_under_the_folder(library, tmp_path, name) -> None:
    game = tmp_path / name / "game"
    _package(game / "0000")
    _package(game / "0001", b"world")  # the same path again: its load priority is ranked
    index = tmp_path / name / "cache" / "full.index"
    build = library.cdmw_full_archive_build_index_utf8
    build.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint64), ctypes.c_char_p,
                      ctypes.c_size_t]
    build.restype = ctypes.c_int
    count, error = ctypes.c_uint64(), ctypes.create_string_buffer(4096)
    status = build(str(game).encode("utf-8"), str(index).encode("utf-8"), ctypes.byref(count), error, len(error))
    assert status == 0, error.value.decode("utf-8", "replace")
    assert count.value == 2 and index.is_file()
    assert str(game / "0001" / "0.pamt").encode("utf-8") in index.read_bytes()


@pytest.mark.parametrize("pathc", [None, b"\0" * 8], ids=["missing", "truncated"])
@pytest.mark.parametrize("name", FOLDER_NAMES)
def test_a_partial_dds_reaches_its_pathc_under_the_folder(library, tmp_path, name, pathc) -> None:
    """A missing PATHC is named; a present one is opened and read (its cache key is the path)."""
    package = tmp_path / name / "game" / "0000"
    payload = b"\0" * 32
    package.mkdir(parents=True)
    (package / "0.paz").write_bytes(payload)
    if pathc is not None:
        (package.parent / "meta").mkdir()
        (package.parent / "meta" / "0.pathc").write_bytes(pathc)
    decode = library.cdmw_full_archive_decode_entry_with_context_utf8
    decode.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint64, ctypes.c_uint64,
                       ctypes.c_uint64, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_size_t,
                       ctypes.POINTER(ctypes.c_size_t), ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                       ctypes.c_size_t]
    decode.restype = ctypes.c_int
    required, note, error = ctypes.c_size_t(), ctypes.create_string_buffer(256), ctypes.create_string_buffer(4096)
    # Compression type 1 on a .dds: the header comes from <game>/meta/0.pathc, which is missing.
    status = decode(b"character/texture/a.dds", str(package / "0.pamt").encode("utf-8"),
                    str(package / "0.paz").encode("utf-8"), 0, len(payload), 4096, 1, None, 0,
                    ctypes.byref(required), note, len(note), error, len(error))
    message = error.value.decode("utf-8")
    assert status != 0
    # Before the fix the narrowing threw first: "No mapping for the Unicode character exists...".
    if pathc is None:
        assert message.startswith("partial DDS metadata was not found: ") and name in message, message
    else:
        assert message == "PATHC file is too small", message
