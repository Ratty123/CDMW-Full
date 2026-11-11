from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

from cdmw.constants import APP_NAME, LEGACY_APP_NAMES
from cdmw.domain.archives.discovery import (
    ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, ARCHIVE_IGNORED_FOLDERS_SETTING,
    BUILTIN_IGNORED_ARCHIVE_FOLDERS,
    normalize_ignored_archive_folders,
)
from cdmw.core.classification_registry import configure_texture_classification_registry
from cdmw.services.workspace_layout import WORKSPACE_MIGRATION_SETTINGS_KEY, migrate_legacy_workspace_layout


MODEL_TEXTURE_ON_DEMAND_MIGRATION_SETTINGS_KEY = "archive/model_texture_on_demand_migration_v2"


def read_ignored_archive_folders(settings: object | None) -> tuple[str, ...]:
    if settings is None:
        return BUILTIN_IGNORED_ARCHIVE_FOLDERS
    value = settings.value(ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, None)
    use_defaults = value is None
    if use_defaults:
        value = settings.value(ARCHIVE_IGNORED_FOLDERS_SETTING, [])
    if isinstance(value, str):
        value = [value] if value else []
    folders = (*BUILTIN_IGNORED_ARCHIVE_FOLDERS, *(value or ())) if use_defaults else (value or ())
    result: dict[str, str] = {}
    for item in folders:
        result.setdefault(str(item).casefold(), str(item))
    return tuple(result.values())


def add_ignored_archive_folder(settings: object, folder: str) -> None:
    from PySide6.QtCore import QSettings

    folders = normalize_ignored_archive_folders((*read_ignored_archive_folders(settings), folder))
    previous = settings.value(ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, None)
    settings.setValue(ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, list(folders))
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        if previous is None:
            settings.remove(ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING)
        else:
            settings.setValue(ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, previous)
        raise OSError("Settings could not be saved.")


def migrate_model_texture_setting_to_on_demand(settings: object) -> bool:
    """Migrate every pre-v2 profile once while preserving later settings opt-in."""

    try:
        marker = str(settings.value(MODEL_TEXTURE_ON_DEMAND_MIGRATION_SETTINGS_KEY, "") or "").strip().lower()
    except Exception:
        return False
    if marker in {"1", "true", "yes", "on"}:
        return False
    try:
        settings.setValue("archive/model_use_textures", False)
        settings.setValue(MODEL_TEXTURE_ON_DEMAND_MIGRATION_SETTINGS_KEY, True)
        sync = getattr(settings, "sync", None)
        if callable(sync):
            sync()
    except Exception:
        return False
    return True


@dataclass(slots=True)
class SettingsService:
    settings: object | None = None


def resolve_settings_file_path(*, app_name: str = APP_NAME, base_dir: Path | None = None) -> Path:
    if base_dir is None:
        from cdmw.app.app_folder import cdmw_folder

        base_dir = cdmw_folder()
    return Path(base_dir) / f"{app_name}.cfg"


def prepare_settings_file(
    settings_file_path: Path,
    *,
    legacy_app_names: tuple[str, ...] = LEGACY_APP_NAMES,
) -> Path:
    settings_file_path = Path(settings_file_path)
    settings_file_path.parent.mkdir(parents=True, exist_ok=True)
    configure_texture_classification_registry(
        settings_file_path.parent / "texture_classification_registry.json"
    )
    if not settings_file_path.exists():
        for legacy_settings_path in [settings_file_path.with_name(f"{name}.cfg") for name in legacy_app_names]:
            if not legacy_settings_path.exists():
                continue
            try:
                shutil.copy2(legacy_settings_path, settings_file_path)
                break
            except OSError:
                continue
    return settings_file_path


def create_settings(
    *,
    settings_file_path: Path | None = None,
    qsettings_cls: Any | None = None,
) -> Any:
    if qsettings_cls is None:
        from PySide6.QtCore import QSettings

        qsettings_cls = QSettings
    resolved_path = prepare_settings_file(settings_file_path or resolve_settings_file_path())
    settings = qsettings_cls(str(resolved_path), qsettings_cls.Format.IniFormat)
    settings.setFallbacksEnabled(False)
    try:
        already_migrated = str(settings.value(WORKSPACE_MIGRATION_SETTINGS_KEY, "") or "").strip().lower()
    except Exception:
        already_migrated = ""
    if already_migrated not in {"1", "true", "yes", "on"}:
        migrate_legacy_workspace_layout(resolved_path.parent, settings)
    migrate_model_texture_setting_to_on_demand(settings)
    return settings



# Create New Item kept a few values in HKCU\Software\CrimsonDesertModWorkbench,
# which every copy of the app on the machine shares. They live in the settings
# file now; the registry key is read once to carry them over and never written
# or deleted, because other copies may still read it.
REGISTRY_SETTINGS_SCOPE = "CrimsonDesertModWorkbench"
REGISTRY_VALUES_COPIED_KEY = "migration/registry_values_copied_v1"
_registry_copy_checked: set[str] = set()


def copy_registry_values_once(settings: Any, *, registry: Any = None) -> int:
    """Copy the registry's CDMW values into ``settings`` once; return how many.

    Keys the settings file already holds win. Under a private profile
    (``CDMW_PROFILE_DIR``) the registry is never read, so a test or harness
    cannot pick up the user's own values.
    """

    marker = str(settings.value(REGISTRY_VALUES_COPIED_KEY, "") or "").strip().lower()
    if marker in {"1", "true", "yes", "on"}:
        return 0
    from cdmw.app.app_folder import profile_override

    copied = 0
    if registry is None and profile_override() is None:
        from PySide6.QtCore import QSettings

        registry = QSettings(REGISTRY_SETTINGS_SCOPE, REGISTRY_SETTINGS_SCOPE)
    if registry is not None:
        for key in registry.allKeys():
            if not settings.contains(key):
                settings.setValue(key, registry.value(key))
                copied += 1
    settings.setValue(REGISTRY_VALUES_COPIED_KEY, True)
    sync = getattr(settings, "sync", None)
    if callable(sync):
        sync()
    return copied


def app_settings() -> Any:
    """The app's settings file, for values that used to live in the registry."""

    from PySide6.QtCore import QSettings

    path = resolve_settings_file_path()
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    key = str(path).casefold()
    if key not in _registry_copy_checked:
        _registry_copy_checked.add(key)
        copy_registry_values_once(settings)
    return settings

__all__ = [
    "SettingsService",
    "app_settings",
    "copy_registry_values_once",
    "create_settings",
    "migrate_model_texture_setting_to_on_demand",
    "MODEL_TEXTURE_ON_DEMAND_MIGRATION_SETTINGS_KEY",
    "prepare_settings_file",
    "resolve_settings_file_path",
]
