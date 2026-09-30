"""Owned-cache lifetime, conservative cleanup and later-launch retry contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from cdmw.core import owned_temp, temp_cache
from cdmw.services.temp_data_cleanup import maintain_temp_data


def _abandon(root: Path, *, age: float = 3600) -> None:
    handle = owned_temp._owners.pop(root)
    handle.close()
    marker = root / owned_temp.OWNER_MARKER
    payload = json.loads(marker.read_bytes())
    payload["created_at"] = time.time() - age
    marker.write_text(json.dumps(payload), encoding="utf-8")


def _maintain(root: Path, *cache_roots: Path) -> dict:
    return maintain_temp_data(temp_root=root, cache_roots=cache_roots, report_path=root / "logs" / "cleanup.json")


def test_cleanup_preserves_live_recent_unmarked_and_recovery_data(tmp_path: Path) -> None:
    live = owned_temp.create_owned_temp_directory(prefix="cdmw_effect_workspace_", parent=tmp_path)
    recent = owned_temp.create_owned_temp_directory(prefix="cdmw_preview_session_output_", parent=tmp_path)
    abandoned = owned_temp.create_owned_temp_directory(prefix="cdmw_effect_workspace_", parent=tmp_path)
    (abandoned / "derived.png").write_bytes(b"derived")
    _abandon(recent, age=0)
    _abandon(abandoned)
    unknown = tmp_path / "cdmw_new_item_model_legacy"
    unknown.mkdir()
    (unknown / "keep.gltf").write_text("saved work", encoding="utf-8")
    backups = tmp_path / "CrimsonDesertModWorkbench" / "archive_patch_backups"
    backups.mkdir(parents=True)
    (backups / "original.paz").write_bytes(b"recovery")
    history = tmp_path / "mod_export_history"
    history.mkdir()
    (history / "draft.json").write_bytes(b"saved draft")

    report = _maintain(tmp_path, backups.parent)

    assert report["removed_roots"] == 1
    assert not abandoned.exists()
    assert live.is_dir() and recent.is_dir()
    assert (unknown / "keep.gltf").read_text(encoding="utf-8") == "saved work"
    assert (backups / "original.paz").read_bytes() == b"recovery"
    assert (history / "draft.json").read_bytes() == b"saved draft"
    assert any(item["outcome"] == "unmarked_leftover" for item in report["details"])
    assert json.loads((tmp_path / "logs" / "cleanup.json").read_bytes()) == report


def test_filesystem_lock_protects_a_second_live_process_then_allows_crash_recovery(tmp_path: Path) -> None:
    script = """
import json, sys, time
from pathlib import Path
from cdmw.core import owned_temp
root = owned_temp.create_owned_temp_directory(prefix='cdmw_effect_workspace_', parent=Path(sys.argv[1]))
handle = owned_temp._owners[root]
handle.seek(0)
payload = json.loads(handle.read())
payload['created_at'] = time.time() - 3600
handle.seek(0)
handle.write(json.dumps(payload).encode())
handle.truncate()
handle.flush()
print(root, flush=True)
sys.stdin.read()
"""
    process = subprocess.Popen([sys.executable, "-B", "-c", script, str(tmp_path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        root_text = process.stdout.readline().strip()
        assert root_text, process.stderr.read()
        root = Path(root_text)
        assert _maintain(tmp_path)["removed_roots"] == 0
        assert root.is_dir()
        process.kill()
        process.communicate(timeout=5)
        assert _maintain(tmp_path)["removed_roots"] == 1
        assert not root.exists()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_failed_deletion_keeps_the_marker_and_is_retried(tmp_path: Path, monkeypatch) -> None:
    root = owned_temp.create_owned_temp_directory(prefix="cdmw_effect_workspace_", parent=tmp_path)
    (root / "package_1").mkdir()
    (root / "package_1" / "derived.bin").write_bytes(b"temporary")
    _abandon(root)
    with monkeypatch.context() as patch:
        patch.setattr(owned_temp.shutil, "rmtree", lambda _path: (_ for _ in ()).throw(PermissionError("locked")))
        report = _maintain(tmp_path)
    assert report["deferred_roots"] == 1
    assert (root / owned_temp.OWNER_MARKER).is_file()
    assert _maintain(tmp_path)["removed_roots"] == 1
    assert not root.exists()


def test_failed_owned_cleanup_restores_live_protection(tmp_path: Path, monkeypatch) -> None:
    root = owned_temp.create_owned_temp_directory(prefix="cdmw_effect_workspace_", parent=tmp_path)
    (root / "package_1").mkdir()
    with monkeypatch.context() as patch:
        patch.setattr(owned_temp.shutil, "rmtree", lambda _path: (_ for _ in ()).throw(PermissionError("locked")))
        assert not owned_temp.cleanup_owned_temp_directory(root)
    assert root in owned_temp._owners
    assert owned_temp.owned_temp_directory_is_protected(root)
    assert owned_temp.cleanup_owned_temp_directory(root)


@pytest.mark.parametrize("damage", ["invalid_json", "wrong_identity", "wrong_root"])
def test_cleanup_refuses_unverifiable_markers(tmp_path: Path, damage: str) -> None:
    root = owned_temp.create_owned_temp_directory(prefix="cdmw_effect_workspace_", parent=tmp_path)
    (root / "keep.txt").write_bytes(b"unknown")
    _abandon(root)
    marker = root / owned_temp.OWNER_MARKER
    payload = json.loads(marker.read_bytes())
    if damage == "wrong_identity":
        payload["identity"] = [0, 0]
    elif damage == "wrong_root":
        payload["root"] = str(tmp_path)
    marker.write_text("not json" if damage == "invalid_json" else json.dumps(payload), encoding="utf-8")
    assert _maintain(tmp_path)["removed_roots"] == 0
    assert (root / "keep.txt").read_bytes() == b"unknown"


def test_linked_tree_cannot_delete_external_data(tmp_path: Path) -> None:
    root = owned_temp.create_owned_temp_directory(prefix="cdmw_effect_workspace_", parent=tmp_path)
    external = tmp_path / "user_files"
    external.mkdir()
    (external / "keep.txt").write_bytes(b"user file")
    link = root / "link"
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)], capture_output=True)
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(external, target_is_directory=True)
    _abandon(root)
    assert not owned_temp.cleanup_owned_temp_directory(root, abandoned_only=True)
    assert (external / "keep.txt").read_bytes() == b"user file"
    link.rmdir() if os.name == "nt" else link.unlink()
    assert owned_temp.cleanup_owned_temp_directory(root, abandoned_only=True)


def test_empty_root_cleanup_never_removes_payloads_or_unmarked_roots(tmp_path: Path) -> None:
    root = owned_temp.create_owned_temp_directory(prefix="cdmw_effect_workspace_", parent=tmp_path)
    (root / "building.bin").write_bytes(b"active builder")
    assert not owned_temp.cleanup_owned_temp_directory(root, only_empty=True)
    (root / "building.bin").unlink()
    assert owned_temp.cleanup_owned_temp_directory(root, only_empty=True)
    external = tmp_path / "external_empty"
    external.mkdir()
    assert not owned_temp.cleanup_owned_temp_directory(external, only_empty=True)
    assert external.is_dir()


def test_generated_material_cache_is_shared_within_session_and_pinned(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv(temp_cache.APP_TEMP_CACHE_ROOT_ENV, str(cache))
    path = temp_cache.session_generated_cache_path("cdmw_synthetic_materials", "derived.png")
    assert path == temp_cache.session_generated_cache_path("cdmw_synthetic_materials", "derived.png")
    root = path.parent.parent
    path.parent.mkdir()
    path.write_bytes(b"texture")
    assert root.parent == cache / temp_cache.GENERATED_MATERIALS_CACHE_DIRNAME
    assert temp_cache.prune_app_temp_cache(root=cache, max_bytes=1, target_bytes=0).removed_units == 0
    assert path.read_bytes() == b"texture"
    _abandon(root)
    assert temp_cache.prune_app_temp_cache(root=cache, max_bytes=1, target_bytes=0).removed_units == 1
    next_path = temp_cache.session_generated_cache_path("cdmw_synthetic_materials", "derived.png")
    assert next_path.parent.parent != root


def test_startup_checks_configured_and_legacy_cache_roots(tmp_path: Path, monkeypatch) -> None:
    from cdmw.app import startup_maintenance
    from cdmw.constants import APP_NAME

    system_temp = tmp_path / "temp"
    system_temp.mkdir()
    configured = tmp_path / "configured-cache"
    legacy = system_temp / APP_NAME
    for cache in (configured, legacy):
        root = owned_temp.create_owned_temp_directory(prefix="run-", parent=cache / temp_cache.GENERATED_MATERIALS_CACHE_DIRNAME)
        (root / "old.png").write_bytes(b"regenerable")
        _abandon(root)
    monkeypatch.setenv(temp_cache.APP_TEMP_CACHE_ROOT_ENV, str(configured))
    monkeypatch.setattr(startup_maintenance, "bootstrap_root", lambda: tmp_path / "app")
    monkeypatch.setattr(startup_maintenance.tempfile, "gettempdir", lambda: str(system_temp))

    startup_maintenance.prepare_app_temp_cache_cleanup()

    report_path = tmp_path / "app" / "workspace" / "logs" / "temp_data_cleanup.json"
    report = json.loads(report_path.read_bytes())
    assert report["removed_roots"] == 2
    assert set(report["cache_pruning"]) == {str(configured), str(legacy)}
    assert all(value["total_bytes_before"] > 0 for value in report["cache_pruning"].values())
    assert not list(configured.rglob("old.png")) and not list(legacy.rglob("old.png"))
