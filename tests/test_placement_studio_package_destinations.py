"""Package destinations preserve existing user files and stay inside the chosen parent."""
from pathlib import Path

import pytest

from tests.test_placement_studio_phase5 import _files, _metadata, _plan
from tools.placement_studio.packaging import (
    PackageMetadata, PackagingError, build_all, build_package,
)


def test_existing_destination_requires_explicit_replacement(tmp_path):
    destination = tmp_path / "DMM"
    destination.mkdir()
    notes = destination / "personal-notes.txt"
    notes.write_bytes(b"keep these notes")

    with pytest.raises(PackagingError, match="already exists"):
        build_package("DMM", _plan(), _files(), _metadata(), out_root=destination)

    assert notes.read_bytes() == b"keep these notes"
    assert list(destination.iterdir()) == [notes]


@pytest.mark.parametrize("name", [
    "../Outside/MyMod", r"..\Outside\MyMod", r"C:\Outside\Mod", "C:Mod",
    "/Outside/Mod", r"\\server\share\Mod", "..", "", "Mod.", "NUL",
    "CON.txt", "COM1", "Bad?Name", "Bad\x00Name",
])
def test_unsafe_mod_name_is_refused_before_writing(tmp_path, name):
    output = tmp_path / "chosen"
    with pytest.raises(PackagingError, match="name"):
        build_all(_plan(), _files(), PackageMetadata(name), out_root=output)
    assert list(tmp_path.iterdir()) == []


def test_all_destinations_are_checked_before_any_package_is_written(tmp_path):
    occupied = tmp_path / f"{_metadata().name} - JMM"
    occupied.mkdir()
    (occupied / "notes.txt").write_bytes(b"keep")
    with pytest.raises(PackagingError, match="already exists"):
        build_all(_plan(), _files(), _metadata(), out_root=tmp_path)
    assert list(tmp_path.iterdir()) == [occupied]
    assert (occupied / "notes.txt").read_bytes() == b"keep"


@pytest.mark.parametrize("name", ["My Mod v1.2 (beta)", "鎧テスト", "Sword & Shield"])
def test_ordinary_display_names_keep_their_titles_and_folder_names(tmp_path, name):
    import json

    packages = build_all(_plan(), _files(), PackageMetadata(name), out_root=tmp_path)
    for package in packages:
        assert package.root.name == f"{name} - {package.manager}"
        assert package.root.resolve().parent == tmp_path.resolve()
        assert package.backup_root is None
    manifest = json.loads((packages[0].root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == name


def test_confirmed_rebuild_retains_complete_previous_outputs(tmp_path):
    previous = build_all(_plan(), _files(), _metadata(), out_root=tmp_path)
    snapshots = {}
    for package in previous:
        (package.root / "personal-notes.txt").write_bytes(b"keep my notes")
        snapshots[package.manager] = {
            p.relative_to(package.root): p.read_bytes()
            for p in package.root.rglob("*") if p.is_file()
        }
    payload = {"character/new.xml": b"replacement"}
    rebuilt = build_all(
        _plan(), payload, _metadata(), out_root=tmp_path, replace_existing=True,
    )
    for package in rebuilt:
        assert package.backup_root.parent == tmp_path
        assert {
            p.relative_to(package.backup_root): p.read_bytes()
            for p in package.backup_root.rglob("*") if p.is_file()
        } == snapshots[package.manager]
        assert not (package.root / "personal-notes.txt").exists()
        assert str(package.backup_root) in package.describe()
        assert package.payload_paths == ("character/new.xml",)


def test_destination_created_during_preparation_is_preserved(tmp_path, monkeypatch):
    from cdmw.core import mod_package

    destination = tmp_path / "DMM"
    original = mod_package.finalize_mod_package_export

    def finalize(*args, **kwargs):
        result = original(*args, **kwargs)
        destination.mkdir()
        (destination / "notes.txt").write_bytes(b"created while building")
        return result

    monkeypatch.setattr(mod_package, "finalize_mod_package_export", finalize)
    with pytest.raises(PackagingError, match="already exists"):
        build_package("DMM", _plan(), _files(), _metadata(), out_root=destination)
    assert (destination / "notes.txt").read_bytes() == b"created while building"
    assert list(tmp_path.iterdir()) == [destination]


def test_resolved_destination_must_stay_in_selected_parent(tmp_path, monkeypatch):
    original = Path.resolve
    destination = tmp_path / f"{_metadata().name} - DMM"
    outside = tmp_path.parent / "outside"

    def resolve(path, *args, **kwargs):
        return outside if path == destination else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(PackagingError, match="inside"):
        build_all(_plan(), _files(), _metadata(), out_root=tmp_path)
    assert list(tmp_path.iterdir()) == []
