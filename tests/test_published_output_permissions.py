"""Published output takes its folder's Windows permissions, not the staging folder's.

Python makes ``tempfile.mkdtemp`` folders private on Windows (SYSTEM, Administrators,
owner; inheritance off). A mod staged there and moved into DMM's mods folder kept that
list, so the game could not open it when CDMW had run as administrator.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core.atomic_file import atomic_publish_directory, atomic_publish_files, atomic_publish_paths
from cdmw.core.file_permissions import dacl_description, inherit_parent_permissions

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows permission lists")

_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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


def test_inherit_parent_permissions_retains_current_user_when_parent_lacks_inherited_user_access(tmp_path):
    user = os.environ.get("USERNAME", "").strip()
    if not user:
        pytest.skip("USERNAME environment variable is unavailable.")
    broken = tmp_path / "broken_parent"
    broken.mkdir()
    subprocess.run(
        [
            "icacls",
            str(broken),
            "/inheritance:r",
            "/grant",
            "SYSTEM:(OI)(CI)F",
            "/grant",
            "Administrators:(OI)(CI)F",
            "/grant",
            f"{user}:F",
        ],
        check=True,
        capture_output=True,
    )
    try:
        stage = _private_stage(broken)
        _private_or_skip(stage)

        target = broken / "Helm-dmm"
        atomic_publish_directory(stage, target)

        protected, _sddl = dacl_description(target)
        assert not protected
        assert sorted(p.name for p in target.iterdir()) == ["character", "manifest.json"]
        texture = target / "character" / "texture" / "a.dds"
        assert texture.read_bytes() == b"DDS "
        texture.write_bytes(b"DDS2")
        assert texture.read_bytes() == b"DDS2"
        extra = target / "extra.txt"
        extra.write_text("ok", encoding="utf-8")
        assert extra.read_text(encoding="utf-8") == "ok"
    finally:
        subprocess.run(["icacls", str(broken), "/reset", "/t", "/q"], capture_output=True)


def test_ensure_archive_preview_source_recovers_from_readonly_and_inaccessible_cache_dir(tmp_path, monkeypatch):
    from cdmw.core import archive_media_preview
    from cdmw.core.protected_roots import ProtectedGameFolderWrite
    from cdmw.models import ArchiveEntry

    user = os.environ.get("USERNAME", "").strip()
    if not user:
        pytest.skip("USERNAME environment variable is unavailable.")
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(archive_media_preview, "app_temp_cache_path", lambda *parts: cache_root.joinpath(*parts))

    paz = tmp_path / "0009" / "0.paz"
    paz.parent.mkdir(parents=True)
    paz.write_bytes(b"GAME")
    pamt = tmp_path / "0009" / "0.pamt"
    pamt.write_bytes(b"pamt")
    entry = ArchiveEntry("character/texture/cd_phm_00_hel_0282_00_01_01_o.dds", pamt, paz, 0, 4, 4, 0, 0)

    initial_path, _ = archive_media_preview.ensure_archive_preview_source(entry)
    assert initial_path.read_bytes() == b"GAME"
    primary_dir = initial_path.parent

    # Subcase A: read-only existing cache directory (with a read-only leftover file) is cleared and replaced.
    shutil.rmtree(primary_dir)
    primary_dir.mkdir(parents=True)
    stale_file = primary_dir / "stale.tmp"
    stale_file.write_bytes(b"STALE")
    os.chmod(stale_file, stat.S_IREAD)
    os.chmod(primary_dir, stat.S_IREAD)
    try:
        ro_recovered, _ = archive_media_preview.ensure_archive_preview_source(entry)
        assert ro_recovered.parent == primary_dir
        assert ro_recovered.read_bytes() == b"GAME"
        assert not stale_file.exists()
    finally:
        if primary_dir.exists():
            os.chmod(primary_dir, stat.S_IWRITE | stat.S_IREAD)
            for child in primary_dir.iterdir():
                os.chmod(child, stat.S_IWRITE | stat.S_IREAD)

    # Subcase B: ACL-denied existing cache directory is skipped via fallback slot -r1.
    shutil.rmtree(primary_dir)
    primary_dir.mkdir(parents=True)
    (primary_dir / initial_path.name).write_bytes(b"LOCKED")
    plain_dir = str(primary_dir).removeprefix("\\\\?\\")
    subprocess.run(
        [
            "icacls",
            plain_dir,
            "/inheritance:r",
            "/grant",
            "SYSTEM:(OI)(CI)F",
            "/grant",
            "Administrators:(OI)(CI)F",
        ],
        check=True,
        capture_output=True,
    )
    try:
        fallback_path, _ = archive_media_preview.ensure_archive_preview_source(entry)
        assert fallback_path.parent != primary_dir
        assert fallback_path.parent.name.endswith("-r1")
        assert fallback_path.read_bytes() == b"GAME"
        assert not dacl_description(fallback_path.parent)[0]

        with monkeypatch.context() as patch:
            patch.setattr(
                archive_media_preview,
                "read_archive_entry_data",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should reuse -r1 cache slot")),
            )
            hit_path, _ = archive_media_preview.ensure_archive_preview_source(entry)
            assert hit_path == fallback_path
            assert hit_path.read_bytes() == b"GAME"
    finally:
        subprocess.run(["icacls", plain_dir, "/reset", "/t", "/q"], check=True, capture_output=True)

    # Subcase C: ProtectedGameFolderWrite is never swallowed or retried across fallback slots.
    entry2 = ArchiveEntry("character/texture/protected_target.dds", pamt, paz, 0, 4, 4, 0, 0)
    publish_calls = 0

    def fail_protected(*_args, **_kwargs):
        nonlocal publish_calls
        publish_calls += 1
        raise ProtectedGameFolderWrite("protected game folder")

    monkeypatch.setattr(archive_media_preview, "atomic_publish_directory", fail_protected)
    with pytest.raises(ProtectedGameFolderWrite):
        archive_media_preview.ensure_archive_preview_source(entry2)
    assert publish_calls == 1


def test_other_cache_and_export_publishers_inherit_parent_permissions(tmp_path):
    from cdmw.core.material_sidecar_package import _publish_fresh_package
    from cdmw.core.owned_temp import cleanup_owned_temp_directory, create_owned_temp_directory
    from cdmw.core.texture_decode_cache import preview_sidecar_path, preview_staging_dir, publish_preview_pair
    from cdmw.rendering.native_preview_package_cache import (
        create_native_preview_package_staging_dir,
        store_native_preview_package_cache,
    )
    from cdmw.services.mesh_free_edit_output import publish_free_edit_output
    from cdmw.services.mesh_rust_preview_files import atomic_preview_publication
    from tools.mesh_harness.fixtures import build_synthetic_mesh

    # 1. texture_decode_cache.publish_preview_pair
    decode_root = tmp_path / "decode_cache"
    decode_root.mkdir()
    final_png = decode_root / "tex.png"
    with preview_staging_dir(decode_root) as staging:
        _private_or_skip(staging)
        staged_png = staging / "tex.png"
        staged_png.write_bytes(_MINIMAL_PNG)
        publish_preview_pair(staged_png, final_png, {"status": "decoded"})
    _assert_like_destination(final_png, decode_root)
    _assert_like_destination(preview_sidecar_path(final_png), decode_root)

    # 2. native_preview_package_cache.store_native_preview_package_cache
    native_cache_root = tmp_path / "native_pkg_cache"
    staging_entry = create_native_preview_package_staging_dir(native_cache_root)
    _private_or_skip(staging_entry)
    (staging_entry / "package").mkdir()
    (staging_entry / "package" / "manifest.json").write_text("{}", encoding="utf-8")
    hit = store_native_preview_package_cache(
        native_cache_root,
        "key1",
        staging_entry,
        {},
        validate_package=lambda pkg: ((pkg / "manifest.json").is_file(), ()),
        max_bytes=1024 * 1024,
        target_bytes=512 * 1024,
    )
    assert hit is not None
    _assert_like_destination(hit.entry_dir, hit.entry_dir.parent)
    _assert_like_destination(hit.package_dir / "manifest.json", hit.package_dir)

    # 3. mesh_rust_preview_files.atomic_preview_publication
    @dataclass(frozen=True)
    class _FakePreviewPackage:
        package_dir: Path
        manifest_path: Path
        status_path: Path
        output_dir: Path
        edit_operations_path: Path

    @atomic_preview_publication
    def _build_fake_preview(*, output_package_dir: Path) -> _FakePreviewPackage:
        _private_or_skip(output_package_dir.parent)
        output_package_dir.mkdir(parents=True, exist_ok=True)
        manifest = output_package_dir / "manifest.json"
        status = output_package_dir / "status.json"
        ops = output_package_dir / "ops.json"
        out = output_package_dir / "out"
        out.mkdir()
        manifest.write_text("{}", encoding="utf-8")
        status.write_text("{}", encoding="utf-8")
        ops.write_text("{}", encoding="utf-8")
        return _FakePreviewPackage(output_package_dir, manifest, status, out, ops)

    rust_root = tmp_path / "rust_preview"
    rust_published = _build_fake_preview(output_package_dir=rust_root / "pkg")
    _assert_like_destination(rust_published.package_dir, rust_root)
    _assert_like_destination(rust_published.manifest_path, rust_published.package_dir)

    # 4. owned_temp.create_owned_temp_directory
    gen_parent = tmp_path / "generated"
    gen_parent.mkdir()
    owned_root = create_owned_temp_directory(prefix="run-", parent=gen_parent)
    try:
        _assert_like_destination(owned_root, gen_parent)
        derived = owned_root / "derived.txt"
        derived.write_text("ok", encoding="utf-8")
        _assert_like_destination(derived, owned_root)
    finally:
        cleanup_owned_temp_directory(owned_root)

    # 5. material_sidecar_package._publish_fresh_package (package folder and sibling zip)
    sidecar_root = tmp_path / "sidecar_exports"
    sidecar_root.mkdir()
    staging_parent = Path(tempfile.mkdtemp(prefix=".MatEdit.", suffix=".tmp", dir=sidecar_root))
    try:
        _private_or_skip(staging_parent)
        staged_root = staging_parent / "package"
        staged_root.mkdir()
        (staged_root / "manifest.json").write_text("{}", encoding="utf-8")
        staged_zip = staged_root.with_name(staged_root.name + ".zip")
        staged_zip.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
        package_root = sidecar_root / "MatEdit"
        _publish_fresh_package(staged_root, package_root)
        _assert_like_destination(package_root, sidecar_root)
        _assert_like_destination(package_root / "manifest.json", package_root)
        _assert_like_destination(sidecar_root / "MatEdit.zip", sidecar_root)
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)

    # 6. mesh_free_edit_output.publish_free_edit_output
    free_out = tmp_path / "free_edit_out"
    free_result = publish_free_edit_output(
        SimpleNamespace(mesh=build_synthetic_mesh(), mesh_revision=1, native_edit_revision=0),
        free_out,
    )
    _assert_like_destination(free_result.output_dir, tmp_path)
    _assert_like_destination(free_result.obj_path, free_result.output_dir)
    _assert_like_destination(free_result.manifest_path, free_result.output_dir)
