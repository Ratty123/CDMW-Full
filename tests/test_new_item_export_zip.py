"""A mod folder and its optional shareable ZIP publish or roll back together."""

from pathlib import Path
import threading
import zipfile

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.new_item_service import NewItemExportResult, _publish_package_atomically


def _write(staging):
    (staging / "payload.bin").write_bytes(b"new contents" * 100_000)
    return NewItemExportResult(staging, "CDUMM", ("payload.bin",), (), ())


def test_zip_keeps_dots_in_mod_name_and_contains_the_completed_folder(tmp_path):
    folder = tmp_path / "heahea.v1"
    other_zip = tmp_path / "heahea.zip"
    other_zip.write_bytes(b"unrelated ZIP")
    result = _publish_package_atomically(folder, _write, create_zip=True, replace_existing=False)
    assert result.package_root == folder
    assert result.zip_path == tmp_path / "heahea.v1.zip"
    with zipfile.ZipFile(result.zip_path) as archive:
        assert archive.namelist() == ["payload.bin"]
        assert archive.read("payload.bin") == (folder / "payload.bin").read_bytes()
    assert other_zip.read_bytes() == b"unrelated ZIP"
    assert not list(tmp_path.glob(".*cdmw-stage-*"))


@pytest.mark.parametrize("failure", ["zip_write", "cancel", "publish"])
def test_zip_failure_or_cancellation_preserves_existing_folder_and_zip(tmp_path, monkeypatch, failure):
    folder = tmp_path / "heahea"
    folder.mkdir()
    (folder / "payload.bin").write_bytes(b"old folder")
    target_zip = tmp_path / "heahea.zip"
    target_zip.write_bytes(b"old ZIP")
    stop = threading.Event()
    original_write = zipfile._ZipWriteFile.write

    def write_chunk(self, data):
        if failure == "zip_write":
            raise OSError("ZIP write failed")
        result = original_write(self, data)
        if failure == "cancel":
            stop.set()
        return result

    monkeypatch.setattr(zipfile._ZipWriteFile, "write", write_chunk)
    original_replace = Path.replace

    def replace(source, destination):
        if failure == "publish" and ".cdmw-stage-" in source.name and source.suffix == ".zip":
            raise OSError("ZIP publish failed")
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(RunCancelled if failure == "cancel" else OSError):
        _publish_package_atomically(folder, _write, create_zip=True, stop_event=stop)
    assert (folder / "payload.bin").read_bytes() == b"old folder"
    assert target_zip.read_bytes() == b"old ZIP"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["heahea", "heahea.zip"]


def test_new_mod_refuses_an_existing_zip_without_publishing_a_folder(tmp_path):
    target_zip = tmp_path / "heahea.zip"
    target_zip.write_bytes(b"existing ZIP")
    with pytest.raises(FileExistsError, match="already exists"):
        _publish_package_atomically(tmp_path / "heahea", _write, create_zip=True, replace_existing=False)
    assert not (tmp_path / "heahea").exists()
    assert target_zip.read_bytes() == b"existing ZIP"
