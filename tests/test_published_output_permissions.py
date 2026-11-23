"""Published output takes its folder's Windows permissions, not the staging folder's.

Python makes ``tempfile.mkdtemp`` folders private on Windows (SYSTEM, Administrators,
owner; inheritance off). A mod staged there and moved into DMM's mods folder kept that
list, so the game could not open it when CDMW had run as administrator.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from cdmw.core.atomic_file import atomic_publish_directory, atomic_publish_files, atomic_publish_paths
from cdmw.core.file_permissions import dacl_description, inherit_parent_permissions

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows permission lists")


def _private_stage(parent: Path) -> Path:
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=parent))
    (stage / "character" / "texture").mkdir(parents=True)
    (stage / "character" / "texture" / "a.dds").write_bytes(b"DDS ")
    (stage / "manifest.json").write_text("{}", encoding="utf-8")
    return stage


def _private_or_skip(stage: Path) -> None:
    protected, _sddl = dacl_description(stage)
    if not protected:
        pytest.skip("This Python does not make mkdtemp folders private.")


def _normal_permissions(folder: Path) -> str:
    probe = folder / "probe.txt"
    probe.write_text("x", encoding="utf-8")
    try:
        return dacl_description(probe)[1]
    finally:
        probe.unlink()


def _entries(sddl: str) -> str:
    """The access entries alone. Setting a file's list marks it auto-inherited
    (``D:AI``), which a file just made there lacks; the access is the same."""
    return sddl[sddl.find("("):] if "(" in sddl else sddl


def _assert_like_destination(path: Path, destination: Path) -> None:
    protected, sddl = dacl_description(path)
    assert not protected
    if path.is_file():
        assert _entries(sddl) == _entries(_normal_permissions(destination))


def test_published_mod_folder_takes_the_mods_folder_permissions(tmp_path):
    mods = tmp_path / "mods"
    mods.mkdir()
    stage = _private_stage(tmp_path)
    _private_or_skip(stage)

    atomic_publish_directory(stage, mods / "Helm-dmm")

    folder = mods / "Helm-dmm"
    _assert_like_destination(folder, mods)
    texture = folder / "character" / "texture" / "a.dds"
    _assert_like_destination(texture, texture.parent)
    assert dacl_description(texture)[1] == _normal_permissions(texture.parent)


def test_publish_paths_and_files_take_the_destination_permissions(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    stage = _private_stage(tmp_path)
    _private_or_skip(stage)

    atomic_publish_paths([(stage, out / "Body-dmm")], replace_existing=False)
    _assert_like_destination(out / "Body-dmm" / "manifest.json", out / "Body-dmm")

    files_stage = _private_stage(tmp_path)
    atomic_publish_files({files_stage / "manifest.json": out / "loose.json"})
    _assert_like_destination(out / "loose.json", out)


def test_inherit_parent_permissions_reports_a_missing_path(tmp_path):
    assert inherit_parent_permissions(tmp_path / "missing") is False
