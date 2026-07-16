from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Mapping

from cdmw.domain.workspace import (
    WORKSPACE_DIRNAME,
    app_root_from_workspace_member,
    default_mod_package_export_root,
    workspace_path,
    workspace_paths,
    workspace_root,
)


WORKSPACE_MIGRATION_SETTINGS_KEY = "workspace/layout_migration_v1_done"


LEGACY_WORKSPACE_DIRS: Mapping[str, str] = {
    "input_dds": "original_dds",
    "png_upscaled": "staging/upscaled_png",
    "png_texture_editor": "staging/texture_editor_png",
    "png_staged_input": "staging/dds_input_png",
    "dds_final": "outputs/rebuilt_textures",
    "dds_final_mod_ready_loose_export": "outputs/mod_packages",
    "mod_ready_loose_export": "outputs/mod_packages",
    "archive_extract": "extracts",
    "texture_editor_workspace": "texture_editor_projects",
    "item_icon_library": "libraries/item_icons",
    "model_catalogue": "libraries/models",
    "paa_research": "paa_research",
    "modify_original_sessions": "modify_original_sessions",
    "archive_cache": "cache",
    "crash_reports": "logs",
    "replace_assistant_export": "outputs/texture_replacer",
    "text_search_export": "outputs/text_search",
    "tools": "tools",
}


SETTINGS_PATH_DEFAULTS: Mapping[str, tuple[str, str]] = {
    "paths/original_dds_root": ("input_dds", "original_dds_root"),
    "paths/png_root": ("png_upscaled", "png_root"),
    "paths/texture_editor_png_root": ("png_texture_editor", "texture_editor_png_root"),
    "paths/dds_staging_root": ("png_staged_input", "dds_staging_root"),
    "paths/output_root": ("dds_final", "output_root"),
    "archive/extract_root": ("archive_extract", "archive_extract_root"),
    "upscale/mod_ready_export_root": ("dds_final_mod_ready_loose_export", "mod_ready_export_root"),
    "settings/csv_log_path": ("build_log.csv", "csv_log_path"),
    "chainner/exe_path": ("tools/chaiNNer/chaiNNer.exe", "chainner_exe_path"),
    "ncnn/exe_path": ("tools/realesrgan_ncnn/realesrgan-ncnn-vulkan.exe", "ncnn_exe_path"),
    "ncnn/model_dir": ("tools/realesrgan_ncnn/models", "ncnn_model_dir"),
    "replace_assistant/package_output_root": ("replace_assistant_export", "replace_assistant_output_root"),
    "text_search/export_root": ("text_search_export", "text_search_export_root"),
}


@dataclass(slots=True)
class WorkspaceMigrationReport:
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    skipped: list[tuple[Path, Path, str]] = field(default_factory=list)
    settings_updated: list[str] = field(default_factory=list)


def legacy_direct_child_path(app_root: Path, name: str) -> Path:
    return Path(app_root).expanduser().resolve() / name


def is_legacy_direct_child(path: Path, app_root: Path, legacy_name: str) -> bool:
    try:
        resolved = Path(path).expanduser().resolve()
        root = Path(app_root).expanduser().resolve()
    except OSError:
        return False
    return resolved.parent == root and resolved.name.lower() == legacy_name.lower()


def migrate_legacy_workspace_layout(app_root: Path, settings: object | None = None) -> WorkspaceMigrationReport:
    root = Path(app_root).expanduser().resolve()
    report = WorkspaceMigrationReport()
    source_checkout = (root / ".git").exists() and (root / "cdmw").is_dir()

    for legacy_name, new_relative in LEGACY_WORKSPACE_DIRS.items():
        source = root / legacy_name
        destination = workspace_path(root, new_relative)
        if not source.exists() or not source.is_dir():
            continue
        if legacy_name == "tools" and source_checkout:
            report.skipped.append((source, destination, "source checkout"))
            continue
        if source.parent != root:
            report.skipped.append((source, destination, "not direct child"))
            continue
        if destination.exists():
            report.skipped.append((source, destination, "destination exists"))
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            report.moved.append((source, destination))
        except OSError as exc:
            report.skipped.append((source, destination, str(exc)))

    if settings is not None:
        paths = workspace_paths(root)
        for key, (legacy_name, path_key) in SETTINGS_PATH_DEFAULTS.items():
            old_value = ""
            try:
                old_value = str(settings.value(key, "") or "").strip()
            except Exception:
                old_value = ""
            should_update = not old_value
            if old_value:
                should_update = is_legacy_direct_child(Path(old_value), root, legacy_name)
            if not should_update:
                continue
            try:
                settings.setValue(key, str(paths[path_key]))
                report.settings_updated.append(key)
            except Exception:
                continue
        try:
            settings.setValue(WORKSPACE_MIGRATION_SETTINGS_KEY, True)
            settings.sync()
        except Exception:
            pass

    return report


__all__ = [
    "LEGACY_WORKSPACE_DIRS",
    "SETTINGS_PATH_DEFAULTS",
    "WORKSPACE_DIRNAME",
    "WORKSPACE_MIGRATION_SETTINGS_KEY",
    "WorkspaceMigrationReport",
    "app_root_from_workspace_member",
    "default_mod_package_export_root",
    "is_legacy_direct_child",
    "legacy_direct_child_path",
    "migrate_legacy_workspace_layout",
    "workspace_path",
    "workspace_paths",
    "workspace_root",
]
