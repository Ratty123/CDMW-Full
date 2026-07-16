"""Dependency-free workspace path policy.

The services layer owns migration and settings side effects.  Lower layers can
use these deterministic path calculations without importing services.
"""

from __future__ import annotations

from pathlib import Path


WORKSPACE_DIRNAME = "workspace"


def workspace_root(app_root: Path) -> Path:
    return Path(app_root).expanduser().resolve() / WORKSPACE_DIRNAME


def workspace_path(app_root: Path, relative_path: str) -> Path:
    return workspace_root(app_root) / Path(relative_path)


def workspace_paths(app_root: Path) -> dict[str, Path]:
    root = workspace_root(app_root)
    tools_root = root / "tools"
    ncnn_dir = tools_root / "realesrgan_ncnn"
    return {
        "workspace_root": root,
        "original_dds_root": root / "original_dds",
        "png_root": root / "staging" / "upscaled_png",
        "texture_editor_png_root": root / "staging" / "texture_editor_png",
        "dds_staging_root": root / "staging" / "dds_input_png",
        "output_root": root / "outputs" / "rebuilt_textures",
        "mod_ready_export_root": root / "outputs" / "mod_packages",
        "replace_assistant_output_root": root / "outputs" / "texture_replacer",
        "text_search_export_root": root / "outputs" / "text_search",
        "archive_extract_root": root / "extracts",
        "texture_editor_workspace_root": root / "texture_editor_projects",
        "item_icon_library_root": root / "libraries" / "item_icons",
        "model_catalogue_root": root / "libraries" / "models",
        "paa_research_root": root / "paa_research",
        "modify_original_sessions_root": root / "modify_original_sessions",
        "archive_cache_root": root / "cache",
        "crash_reports_dir": root / "logs",
        "tools_root": tools_root,
        "chainner_dir": tools_root / "chaiNNer",
        "chainner_exe_path": tools_root / "chaiNNer" / "chaiNNer.exe",
        "ncnn_dir": ncnn_dir,
        "ncnn_exe_path": ncnn_dir / "realesrgan-ncnn-vulkan.exe",
        "ncnn_model_dir": ncnn_dir / "models",
        "csv_log_path": root / "logs" / "build_log.csv",
    }


def default_mod_package_export_root(output_root: Path) -> Path:
    output = Path(output_root).expanduser()
    if output.name == "rebuilt_textures" and output.parent.name == "outputs":
        return output.parent / "mod_packages"
    return output.parent / "mod_packages"


def app_root_from_workspace_member(path: Path) -> Path | None:
    parts = Path(path).parts
    lowered = [part.lower() for part in parts]
    if WORKSPACE_DIRNAME not in lowered:
        return None
    workspace_index = len(lowered) - 1 - lowered[::-1].index(WORKSPACE_DIRNAME)
    if workspace_index <= 0:
        return None
    return Path(*parts[:workspace_index])


__all__ = [
    "WORKSPACE_DIRNAME",
    "app_root_from_workspace_member",
    "default_mod_package_export_root",
    "workspace_path",
    "workspace_paths",
    "workspace_root",
]
