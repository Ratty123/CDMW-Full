"""Defect 2 (the freeze on opening a set): the UI thread's check of a cached preview
package no longer resolves every file's real path, and still refuses a file reached
through a link or junction out of the package."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from cdmw.services import mesh_rust_preview_files as files
from cdmw.services.mesh_rust_preview_cache import validate_resident_rust_preview_package
from cdmw.services.mesh_rust_preview_package import build_rust_preview_package, validate_rust_preview_package
from tests.test_preview_file_hash_once import _triangle


@pytest.fixture(autouse=True)
def _empty_memo():
    files.forget_verified_preview_files()
    yield
    files.forget_verified_preview_files()


def _package(tmp_path: Path) -> tuple[Path, dict, Path]:
    package = build_rust_preview_package(_triangle(), output_package_dir=tmp_path / "package",
                                         include_material_resources=False)
    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    return package.package_dir, manifest, package.manifest_path


def _move_document_into(package_dir: Path, manifest: dict, folder: str) -> Path:
    source = package_dir / manifest["document"]["path"]
    target = package_dir / folder / "nested" / source.name
    target.parent.mkdir(parents=True)
    shutil.move(source, target)
    manifest["document"]["path"] = f"{folder}/nested/{source.name}"
    return target


def test_a_file_in_nested_real_folders_is_accepted_on_both_checks(tmp_path: Path) -> None:
    package_dir, manifest, manifest_path = _package(tmp_path)
    _move_document_into(package_dir, manifest, "deep")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_rust_preview_package(package_dir) == ()
    assert validate_rust_preview_package(package_dir, hash_unverified=False) == ()


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_a_folder_junction_out_of_the_package_is_refused(tmp_path: Path) -> None:
    import _winapi

    package_dir, manifest, manifest_path = _package(tmp_path)
    outside = tmp_path / "outside"
    moved = _move_document_into(package_dir, manifest, "real")
    (outside / "nested").mkdir(parents=True)
    shutil.copy2(moved, outside / "nested" / moved.name)
    _winapi.CreateJunction(str(outside), str(package_dir / "linked"))
    manifest["document"]["path"] = f"linked/nested/{moved.name}"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    for hash_unverified in (True, False):
        problems = validate_rust_preview_package(package_dir, hash_unverified=hash_unverified)
        assert problems == ("preview resource path is not contained",)


def test_a_file_link_out_of_the_package_is_refused(tmp_path: Path) -> None:
    package_dir, manifest, manifest_path = _package(tmp_path)
    document = package_dir / manifest["document"]["path"]
    outside = tmp_path / "outside.json"
    shutil.copy2(document, outside)
    document.unlink()
    try:
        os.symlink(outside, document)
    except OSError:
        pytest.skip("this account may not create symbolic links")
    assert validate_rust_preview_package(package_dir, hash_unverified=False) == (
        "preview resource path is not contained",)


def test_the_ui_thread_check_resolves_only_the_package_root(tmp_path: Path, monkeypatch) -> None:
    package_dir, _manifest, _path = _package(tmp_path)
    calls: list[str] = []
    original = Path.resolve

    def counting(self, *args, **kwargs):
        calls.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counting)
    assert validate_resident_rust_preview_package(package_dir) == (True, ())
    resolved_inside = [call for call in calls if Path(call) != package_dir and package_dir in Path(call).parents]
    assert resolved_inside == []


def test_a_reparse_point_that_names_no_other_file_is_the_file_itself() -> None:
    """OneDrive placeholders and deduplicated files are reparse points but not links;
    the old resolve() accepted them and so does the check now."""

    cloud = os.stat_result((0o100644, 0, 0, 1, 0, 0, 10, 0, 0, 0))
    assert not files._is_link(cloud)

    class _Identity:
        st_mode = 0o100644
        st_reparse_tag = 0x9000001A  # IO_REPARSE_TAG_CLOUD_6: not a name surrogate

    assert not files._is_link(_Identity())
    _Identity.st_reparse_tag = 0xA0000003  # IO_REPARSE_TAG_MOUNT_POINT: a junction
    assert files._is_link(_Identity())
    _Identity.st_reparse_tag = 0xA000000C  # IO_REPARSE_TAG_SYMLINK
    assert files._is_link(_Identity())
