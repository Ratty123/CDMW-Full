from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sys
from typing import Any

from cdmw.constants import APP_NAME, LEGACY_APP_NAMES
from cdmw.core.classification_registry import configure_texture_classification_registry
from cdmw.services.workspace_layout import WORKSPACE_MIGRATION_SETTINGS_KEY, migrate_legacy_workspace_layout


@dataclass(slots=True)
class SettingsService:
    settings: object | None = None


def resolve_settings_file_path(*, app_name: str = APP_NAME, base_dir: Path | None = None) -> Path:
    if base_dir is None:
        if getattr(sys, "frozen", False):
            base_dir = Path(sys.executable).resolve().parent
        else:
            base_dir = Path(__file__).resolve().parents[2]
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
    return settings


__all__ = [
    "SettingsService",
    "create_settings",
    "prepare_settings_file",
    "resolve_settings_file_path",
]
