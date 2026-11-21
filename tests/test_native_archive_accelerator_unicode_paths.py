"""The archive accelerator works when the CDMW folder's path has letters outside ASCII (2026-11-20).

Python writes accelerator jobs with ``ensure_ascii``. The accelerator's JSON
readers dropped the backslash of each escape and kept ``u00f6``, so every job
under such a folder looked for a file that does not exist. Building a mod with
an archive payload over 64 KiB then stopped with "The archive checksum helper
is unavailable", and the other jobs fell back to slower Python code.
"""

from __future__ import annotations

import tempfile

import pytest

from cdmw.core import archive_accelerator
from cdmw.core.archive_format import calculate_pa_checksum
from cdmw.core.archive_overlay import _payload_checksum
from cdmw.models import ArchiveEntry

_BINARY = archive_accelerator.find_native_archive_accelerator()

pytestmark = pytest.mark.skipif(
    not archive_accelerator._native_archive_accelerator_ready(_BINARY),
    reason="needs the native archive accelerator",
)

FOLDER_NAMES = ("Jörg CDMW", "模组", "mods \U0001f600")


@pytest.fixture
def cdmw_folder_named(tmp_path, monkeypatch):
    def use(name: str):
        folder = tmp_path / name
        temp = folder / "workspace" / "temp"
        temp.mkdir(parents=True)
        # The app points tempfile at <CDMW folder>\workspace\temp at start.
        monkeypatch.setattr(tempfile, "tempdir", str(temp))
        return folder

    return use


@pytest.mark.parametrize("name", FOLDER_NAMES)
def test_a_large_mod_payload_gets_its_checksum(cdmw_folder_named, name) -> None:
    cdmw_folder_named(name)
    payload = bytearray(bytes(range(256)) * 1024)  # 256 KiB: over the 64 KiB native threshold
    assert _payload_checksum(payload, stop_event=None) == calculate_pa_checksum(bytes(payload))


@pytest.mark.parametrize("name", FOLDER_NAMES)
def test_files_under_the_folder_are_checksummed(cdmw_folder_named, name) -> None:
    folder = cdmw_folder_named(name)
    path = folder / "a å.bin"
    data = b"crimson" * 4096
    path.write_bytes(data)
    result = archive_accelerator.checksum_files_native([path])
    assert result is not None
    assert result[path] == (calculate_pa_checksum(data), len(data))


@pytest.mark.parametrize("name", FOLDER_NAMES)
def test_an_entry_is_read_from_a_paz_under_the_folder(cdmw_folder_named, name) -> None:
    folder = cdmw_folder_named(name)
    paz = folder / "0000" / "0.paz"
    paz.parent.mkdir()
    payload = b"entry payload " * 64
    paz.write_bytes(b"\0" * 16 + payload)
    entry = ArchiveEntry(
        path="character/a.txt", pamt_path=paz.parent / "0.pamt", paz_file=paz,
        offset=16, comp_size=len(payload), orig_size=len(payload), flags=0, paz_index=0,
    )
    result = archive_accelerator.read_archive_entry_data_native(entry)
    assert result is not None
    assert result[0] == payload
