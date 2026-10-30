"""Exercise cache I/O with Windows long-path opt-in disabled in a private process."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

import pytest

from cdmw.core.filesystem import filesystem_path

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows filesystem contract")


@pytest.mark.parametrize("source, expected", [
    (r"C:\cache\one\..\two.dds", r"\\?\C:\cache\two.dds"),
    ("C:/cache/two.dds", r"\\?\C:\cache\two.dds"),
    (r"\\server\share\cache\two.dds", r"\\?\UNC\server\share\cache\two.dds"),
    (r"\\?\C:\cache\two.dds", r"\\?\C:\cache\two.dds"),
])
def test_windows_filesystem_path_normalizes_before_prefix(source, expected):
    assert str(filesystem_path(source)) == expected


def test_prefixed_cache_paths_share_the_same_lease(tmp_path):
    from cdmw.core import temp_cache

    path = tmp_path / "archive_preview_cache" / "entry" / "source.dds"
    assert temp_cache._cache_unit_key(path) == temp_cache._cache_unit_key(filesystem_path(path))
    assert temp_cache._cache_unit_lock(path) is temp_cache._cache_unit_lock(filesystem_path(path))


@pytest.fixture
def legacy_python(tmp_path):
    from PyInstaller.utils.win32 import winmanifest

    executable = tmp_path / "python-legacy.exe"
    shutil.copy2(sys._base_executable, executable)
    manifest = winmanifest.read_manifest_from_executable(str(executable))
    if isinstance(manifest, tuple):
        _, manifest = manifest
    manifest, count = re.subn(
        rb"(<(?:\w+:)?longPathAware\b[^>]*>)true(</(?:\w+:)?longPathAware>)",
        rb"\g<1>false\g<2>", manifest,
    )
    assert count == 1
    winmanifest.write_manifest_to_executable(str(executable), manifest)
    return executable


@pytest.mark.parametrize("decode_preview", [False, True])
def test_archive_cache_in_legacy_windows_process(tmp_path, legacy_python, decode_preview):
    from cdmw.core.texture_native import find_directxtex_texture_binary

    helper = find_directxtex_texture_binary() if decode_preview else None
    if decode_preview and helper is None:
        pytest.skip("built DDS helper is required for the complete preview check")
    env = os.environ.copy()
    env["PYTHONHOME"] = sys.base_prefix
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT), *[p for p in sys.path if "site-packages" in p]))
    env["PATH"] = sys.base_prefix + os.pathsep + env.get("PATH", "")
    env["QT_QPA_PLATFORM"] = "offscreen"
    run = subprocess.run(
        [str(legacy_python), "-X", "utf8", str(Path(__file__).resolve()),
         "--probe", str(tmp_path), str(helper) if helper else ""],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result["legacy_read_failed"]
    assert result["prepared_read_ok"]
    if decode_preview:
        assert result["preview_ok"]


def _probe(root: Path, helper: str) -> None:
    from cdmw.core import archive_extraction, texture_native
    from cdmw.models import ArchiveEntry

    deep = root / "Unicode å中" / ("p" * 75) / ("q" * 75) / ("r" * 75)
    source = deep / "prepared.dds"
    io_source = filesystem_path(source)
    io_source.parent.mkdir(parents=True)
    data = bytearray(144)
    data[:4] = b"DDS "
    struct.pack_into("<7I", data, 4, 124, 0x81007, 4, 4, 16, 0, 1)
    struct.pack_into("<II4s", data, 76, 32, 4, b"DXT5")
    struct.pack_into("<I", data, 108, 0x1000)
    data[128] = 255
    io_source.write_bytes(data)
    result = {"legacy_read_failed": False}
    try:
        source.stat()
    except OSError:
        result["legacy_read_failed"] = True
    entry = ArchiveEntry(
        "ui/texture/owned.dds", root / "unused.pamt", root / "unused.paz",
        0, len(data), len(data), 0, 0, prepared_path=source,
        prepared_size=len(data), prepared_sha256=hashlib.sha256(data).hexdigest(),
    )
    result["prepared_read_ok"] = archive_extraction.read_archive_entry_data(entry)[0] == data
    if helper:
        from PySide6.QtGui import QImage
        from cdmw.core.archive_preview_result_builder import build_archive_preview_result

        os.environ["CDMW_TEMP_CACHE_ROOT"] = str(deep / "workspace" / "cache")
        texture_native.find_directxtex_texture_binary = lambda: Path(helper)
        preview = build_archive_preview_result(entry)
        assert preview.preview_image_path, preview.detail_text
        image = QImage(preview.preview_image_path)
        assert not image.isNull(), preview.preview_image_path
        assert image.width() == image.height() == 4
        assert "DDS metadata unavailable" not in preview.detail_text
        second = build_archive_preview_result(entry)
        assert second.preview_image_path == preview.preview_image_path
        result["preview_ok"] = True
    print(json.dumps(result))


if __name__ == "__main__":
    _probe(Path(sys.argv[2]), sys.argv[3])
