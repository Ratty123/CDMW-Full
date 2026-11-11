"""P16 stage 1 and P13 stage A: one folder for everything CDMW writes."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from cdmw.app import app_folder

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh_folder(monkeypatch):
    """Forget the cached answer before and after, with the variables cleared."""

    for name in (app_folder.PROFILE_DIR_ENV, app_folder.APP_FOLDER_ENV, app_folder.SYSTEM_TEMP_ENV):
        monkeypatch.delenv(name, raising=False)
    previous_tempdir = tempfile.tempdir
    app_folder._reset_for_tests()
    yield monkeypatch
    tempfile.tempdir = previous_tempdir
    app_folder._reset_for_tests()


def test_without_variables_the_folder_is_the_repository_root(fresh_folder) -> None:
    assert app_folder.cdmw_folder() == ROOT
    assert app_folder.profile_override() is None
    assert app_folder.profile_scope() == ""


def test_the_profile_override_wins_and_is_read_once(fresh_folder, tmp_path: Path) -> None:
    fresh_folder.setenv(app_folder.APP_FOLDER_ENV, str(tmp_path / "launcher"))
    fresh_folder.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path / "profile"))
    assert app_folder.cdmw_folder() == (tmp_path / "profile").resolve()
    fresh_folder.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path / "other"))
    assert app_folder.cdmw_folder() == (tmp_path / "profile").resolve()


def test_a_launcher_folder_is_used_without_an_override(fresh_folder, tmp_path: Path) -> None:
    fresh_folder.setenv(app_folder.APP_FOLDER_ENV, str(tmp_path / "CDMW"))
    assert app_folder.cdmw_folder() == (tmp_path / "CDMW").resolve()


def test_settings_crash_reports_and_workspace_follow_the_folder(fresh_folder, tmp_path: Path) -> None:
    from cdmw.app.bootstrap_reports import bootstrap_root
    from cdmw.services.settings_service import resolve_settings_file_path

    fresh_folder.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path))
    assert resolve_settings_file_path() == tmp_path.resolve() / "CrimsonDesertModWorkbench.cfg"
    assert bootstrap_root() == tmp_path.resolve()
    assert app_folder.workspace_temp_folder() == tmp_path.resolve() / "workspace" / "temp"


def test_temp_files_and_children_go_to_workspace_temp(fresh_folder, tmp_path: Path) -> None:
    fresh_folder.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path))
    for name in ("TMP", "TEMP", "TMPDIR"):
        fresh_folder.setenv(name, os.environ.get(name, tempfile.gettempdir()))
    system = tempfile.gettempdir()
    target = app_folder.prepare_process_temp()
    assert target == tmp_path.resolve() / "workspace" / "temp"
    assert tempfile.gettempdir() == str(target)
    assert os.environ["TMP"] == os.environ["TEMP"] == str(target)
    assert os.environ[app_folder.SYSTEM_TEMP_ENV] == system
    assert app_folder.system_temp_dir() == Path(system)
    made = Path(tempfile.mkdtemp(prefix="cdmw_probe_"))
    assert made.parent == target
    # A child process inherits the redirect.
    child = subprocess.run([sys.executable, "-c", "import tempfile; print(tempfile.gettempdir())"],
                           capture_output=True, text=True, check=True)
    assert Path(child.stdout.strip()) == target


def test_a_read_only_folder_is_reported_not_worked_around(fresh_folder, tmp_path: Path) -> None:
    blocked = tmp_path / "profile"
    blocked.mkdir()
    (blocked / "workspace").write_text("a file where the workspace folder belongs")
    fresh_folder.setenv(app_folder.PROFILE_DIR_ENV, str(blocked))
    before = tempfile.gettempdir()
    with pytest.raises(app_folder.AppFolderNotWritable) as raised:
        app_folder.prepare_process_temp()
    assert raised.value.folder == blocked.resolve()
    assert tempfile.gettempdir() == before


def test_a_profile_scopes_the_single_instance_guard(fresh_folder, tmp_path: Path) -> None:
    from cdmw.app import single_instance

    fresh_folder.delenv(single_instance.SINGLE_INSTANCE_SCOPE_ENV, raising=False)
    assert single_instance._single_instance_mutex_name() == single_instance.APP_SINGLE_INSTANCE_MUTEX_NAME
    fresh_folder.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path))
    expected = "profile-" + hashlib.sha256(str(tmp_path.resolve()).casefold().encode()).hexdigest()[:16]
    assert single_instance._single_instance_mutex_name().endswith("." + expected)
    fresh_folder.setenv(single_instance.SINGLE_INSTANCE_SCOPE_ENV, "explicit")
    assert single_instance._single_instance_mutex_name().endswith(".explicit")


def test_the_installation_lock_stays_where_the_game_looks(fresh_folder, tmp_path: Path) -> None:
    from cdmw.services.installation_lane import lock_path

    fresh_folder.setenv(app_folder.SYSTEM_TEMP_ENV, str(tmp_path / "system-temp"))
    tempfile.tempdir = str(tmp_path / "workspace-temp")
    assert lock_path(tmp_path / "game").parent == tmp_path / "system-temp"


class _Registry:
    def __init__(self, values):
        self.values = dict(values)
        self.reads = 0

    def allKeys(self):  # noqa: N802 - QSettings API
        self.reads += 1
        return list(self.values)

    def value(self, key, default=None):
        return self.values.get(key, default)


def _file_settings(path: Path):
    from PySide6.QtCore import QSettings

    return QSettings(str(path), QSettings.Format.IniFormat)


def test_registry_values_are_copied_once_and_never_overwrite(tmp_path: Path) -> None:
    from cdmw.services.settings_service import REGISTRY_VALUES_COPIED_KEY, copy_registry_values_once

    settings = _file_settings(tmp_path / "CrimsonDesertModWorkbench.cfg")
    settings.setValue("new_item/blender_executable", "C:/chosen/blender.exe")
    registry = _Registry({"new_item/blender_executable": "C:/old/blender.exe", "new_item/rig_dir": "C:/rigs"})
    assert copy_registry_values_once(settings, registry=registry) == 1
    assert settings.value("new_item/blender_executable") == "C:/chosen/blender.exe"
    assert settings.value("new_item/rig_dir") == "C:/rigs"
    assert str(settings.value(REGISTRY_VALUES_COPIED_KEY)).lower() == "true"
    assert copy_registry_values_once(settings, registry=registry) == 0
    assert registry.reads == 1


def test_a_private_profile_never_reads_the_registry(fresh_folder, tmp_path: Path, monkeypatch) -> None:
    import PySide6.QtCore as qtcore

    from cdmw.services import settings_service

    fresh_folder.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path))
    class Guarded(qtcore.QSettings):
        def __init__(self, *args, **kwargs):
            if len(args) == 2 and all(isinstance(value, str) for value in args):
                raise AssertionError("the registry was opened under a private profile")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(qtcore, "QSettings", Guarded)
    monkeypatch.setattr(settings_service, "_registry_copy_checked", set())
    settings = settings_service.app_settings()
    assert Path(settings.fileName()).resolve() == tmp_path.resolve() / "CrimsonDesertModWorkbench.cfg"
    settings.setValue("new_item/blender_executable", "C:/x/blender.exe")
    settings.sync()
    assert (tmp_path / "CrimsonDesertModWorkbench.cfg").is_file()


def test_the_former_registry_sites_use_the_settings_file(fresh_folder, tmp_path: Path) -> None:
    import re

    fresh_folder.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path))
    sites = ("cdmw/services/fbx_blender_conversion.py", "cdmw/ui/new_item/blender_setting.py",
             "cdmw/ui/new_item/controller_task_mixin.py", "cdmw/ui/new_item/effect_placement_dialog_support.py",
             "cdmw/ui/new_item/panels_model.py", "cdmw/ui/new_item/panels_model_preview_mixin.py",
             "cdmw/ui/new_item/preview_controls.py", "cdmw/ui/shell/app_context.py")
    for site in sites:
        text = (ROOT / site).read_text(encoding="utf-8")
        assert not re.search(r"QSettings\(\s*(?:\"CrimsonDesertModWorkbench\"|_SETTINGS_SCOPE|scope)\s*,", text), site
    from cdmw.ui.new_item.blender_setting import blender_for_fbx

    # Behaviour, not only source: the stored choice is read from the profile's file.
    from cdmw.services.settings_service import app_settings

    settings = app_settings()
    settings.setValue("new_item/blender_executable", str(tmp_path / "missing" / "blender.exe"))
    settings.sync()
    assert blender_for_fbx() == ""  # not an executable, so nothing is chosen
    from cdmw.ui.shell.app_context import AppContext

    context = AppContext.create_default()
    assert Path(context.settings.fileName()).resolve() == tmp_path.resolve() / "CrimsonDesertModWorkbench.cfg"


def test_stale_workspace_temp_entries_are_pruned(tmp_path: Path) -> None:
    from cdmw.core.owned_temp import OWNER_MARKER
    from cdmw.services.temp_data_cleanup import prune_stale_workspace_temp

    root = tmp_path / "temp"
    old, fresh, marked, kept = root / "cdmw_preview_core_old", root / "cdmw_preview_core_new", root / "owned", root / "CrimsonDesertModWorkbench"
    for folder in (old, fresh, marked, kept):
        folder.mkdir(parents=True)
        (folder / "file.bin").write_bytes(b"x")
    (marked / OWNER_MARKER).write_text("{}")
    loose = root / "tmpabc.json"
    loose.write_text("{}")
    day_ago = time.time() - 2 * 24 * 3600
    for path in (old, old / "file.bin", loose, marked, marked / "file.bin", kept, kept / "file.bin"):
        os.utime(path, (day_ago, day_ago))
    report = prune_stale_workspace_temp(root, keep=("CrimsonDesertModWorkbench",))
    assert not old.exists() and not loose.exists()
    assert fresh.exists() and marked.exists() and kept.exists()
    assert report == {"removed": 2, "kept": 3, "failed": 0}


def test_the_deepest_temp_paths_fit_in_a_long_cdmw_folder() -> None:
    # A folder name users plausibly have, about 120 characters long. Temp files
    # moved from %TEMP% into workspace\temp; these are the deepest they make.
    folder = Path("C:/Users/a.long.user.name/Documents/Games/Modding Tools/Crimson Desert/"
                  "Crimson Desert Mod Workbench 0.12.0-alpha.4 portable")
    deepest = (
        "workspace/temp/cdmw_preview_core_abcdefgh/package/geometry/batch_0000_identity.bin",
        "workspace/temp/CrimsonDesertModWorkbench/generated_materials/run-0123456789abcdef/texture-0000-0123456789ab.dds",
        "workspace/temp/cdmw_rust_preview/.rust-preview-abcdefgh/package/preview-geometry-0000-0123456789ab.bin",
        "workspace/temp/cdmw-rust-mesh-editor/session-0123456789abcdef0123456789abcdef/texture-0000-0123456789ab.dds",
    )
    longest = max(len(str(folder / path)) for path in deepest)
    assert longest < 260, longest


def test_a_profiled_run_writes_only_inside_its_folder(tmp_path: Path) -> None:
    """Start the app's own entry code in a child under a profile and compare."""

    profile = tmp_path / "profile"
    default_cfg = ROOT / "CrimsonDesertModWorkbench.cfg"
    before_cfg = default_cfg.read_bytes() if default_cfg.exists() else None
    before_registry = _registry_snapshot()
    probe = r"""
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
from cdmw.app.app_folder import prepare_process_temp
prepare_process_temp()
from cdmw.services.settings_service import app_settings, resolve_settings_file_path
settings = app_settings()
settings.setValue("new_item/blender_executable", "C:/probe/blender.exe")
settings.setValue("preview/probe", 1)
settings.sync()
handle, name = tempfile.mkstemp(prefix="cdmw_probe_")
os.close(handle)
print(json.dumps({"settings": str(resolve_settings_file_path()), "temp": name}))
"""
    env = {key: value for key, value in os.environ.items() if key != app_folder.SYSTEM_TEMP_ENV}
    env[app_folder.PROFILE_DIR_ENV] = str(profile)
    result = subprocess.run([sys.executable, "-c", probe, str(ROOT)], env=env, capture_output=True, text=True,
                            check=True, timeout=120)
    paths = json.loads(result.stdout.strip().splitlines()[-1])
    for value in paths.values():
        assert Path(value).resolve().is_relative_to(profile.resolve()), value
    assert (default_cfg.read_bytes() if default_cfg.exists() else None) == before_cfg
    assert _registry_snapshot() == before_registry


def _registry_snapshot():
    if os.name != "nt":
        return None
    import winreg

    def walk(path):
        rows = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                index = 0
                while True:
                    try:
                        name, value, kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    rows[f"{path}\\{name}"] = (repr(value), kind)
                    index += 1
                index = 0
                while True:
                    try:
                        child = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    rows.update(walk(f"{path}\\{child}"))
                    index += 1
        except FileNotFoundError:
            return {}
        return rows

    return walk(r"Software\CrimsonDesertModWorkbench")
