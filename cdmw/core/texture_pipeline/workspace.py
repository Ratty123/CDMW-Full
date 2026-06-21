from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from cdmw.models import AppConfig
from cdmw.services.workspace_layout import app_root_from_workspace_member, workspace_paths

def common_workspace_root_from_config(config: AppConfig) -> Optional[Path]:
    candidates: List[Path] = []
    for raw in (
        config.original_dds_root,
        config.png_root,
        getattr(config, "texture_editor_png_root", ""),
        config.output_root,
        config.dds_staging_root,
        config.archive_extract_root,
        config.mod_ready_export_root,
    ):
        text = str(raw).strip()
        if not text:
            continue
        candidates.append(Path(text).expanduser())

    if len(candidates) < 2:
        return None

    try:
        import os

        common = Path(os.path.commonpath([str(path) for path in candidates]))
    except ValueError:
        return None

    app_root = app_root_from_workspace_member(common)
    if app_root is not None:
        return app_root

    if common.name.lower() in {
        "input_dds",
        "png_upscaled",
        "png_texture_editor",
        "dds_final",
        "png_staged_input",
        "archive_extract",
        "dds_final_mod_ready_loose_export",
        "mod_ready_loose_export",
    }:
        return common.parent
    return common


def suggested_workspace_paths(base_dir: Path) -> Dict[str, Path]:
    return workspace_paths(base_dir)


def create_workspace_structure(base_dir: Path) -> Dict[str, Path]:
    paths = suggested_workspace_paths(base_dir)
    for key in (
        "original_dds_root",
        "png_root",
        "texture_editor_png_root",
        "dds_staging_root",
        "output_root",
        "mod_ready_export_root",
        "replace_assistant_output_root",
        "text_search_export_root",
        "archive_extract_root",
        "texture_editor_workspace_root",
        "item_icon_library_root",
        "model_catalogue_root",
        "paa_research_root",
        "modify_original_sessions_root",
        "archive_cache_root",
        "crash_reports_dir",
        "tools_root",
        "chainner_dir",
        "ncnn_dir",
        "ncnn_model_dir",
    ):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def create_missing_directories_for_config(config: AppConfig) -> List[Path]:
    created: List[Path] = []

    def ensure_dir(path: Path) -> None:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)

    for raw in (
        config.original_dds_root,
        config.png_root,
        getattr(config, "texture_editor_png_root", ""),
        config.output_root,
        config.dds_staging_root,
        config.archive_extract_root,
        config.mod_ready_export_root,
        config.ncnn_model_dir,
    ):
        text = str(raw).strip()
        if text:
            ensure_dir(Path(text).expanduser().resolve())

    if config.csv_log_enabled and config.csv_log_path.strip():
        ensure_dir(Path(config.csv_log_path).expanduser().resolve().parent)

    for raw in (
        config.texconv_path,
        config.chainner_exe_path,
        config.chainner_chain_path,
        config.ncnn_exe_path,
    ):
        text = str(raw).strip()
        if text:
            ensure_dir(Path(text).expanduser().resolve().parent)

    return created
