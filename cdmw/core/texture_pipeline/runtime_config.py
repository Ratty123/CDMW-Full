from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple

from cdmw.constants import (
    DEFAULT_DDS_CUSTOM_FORMAT,
    DEFAULT_DDS_FORMAT_MODE,
    DEFAULT_DDS_MIP_MODE,
    DEFAULT_DDS_SIZE_MODE,
    DEFAULT_UPSCALE_POST_CORRECTION,
    DEFAULT_UPSCALE_TEXTURE_PRESET,
    DDS_FORMAT_MODE_CUSTOM,
    DDS_FORMAT_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_CUSTOM,
    DDS_MIP_MODE_FULL_CHAIN,
    DDS_MIP_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_SINGLE,
    DDS_SIZE_MODE_CUSTOM,
    DDS_SIZE_MODE_ORIGINAL,
    DDS_SIZE_MODE_PNG,
    ENABLE_AUTOMATIC_TEXTURE_RULES,
    ENABLE_MOD_READY_LOOSE_EXPORT,
    ENABLE_UNSAFE_TECHNICAL_OVERRIDE,
    MOD_READY_CREATE_NO_ENCRYPT,
    MOD_READY_PACKAGE_AUTHOR,
    MOD_READY_PACKAGE_DESCRIPTION,
    MOD_READY_PACKAGE_NEXUS_URL,
    MOD_READY_PACKAGE_TITLE,
    MOD_READY_PACKAGE_VERSION,
    REALESRGAN_NCNN_EXTRA_ARGS,
    REALESRGAN_NCNN_SCALE,
    REALESRGAN_NCNN_TILE_SIZE,
    RETRY_SMALLER_TILE_ON_FAILURE,
    SUPPORTED_DDS_FORMAT_CHOICES,
    UPSCALE_BACKEND_CHAINNER,
    UPSCALE_BACKEND_NONE,
    UPSCALE_BACKEND_REALESRGAN_NCNN,
    UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM,
    UPSCALE_POST_CORRECTION_MATCH_LEVELS,
    UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA,
    UPSCALE_POST_CORRECTION_NONE,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED,
    UPSCALE_TEXTURE_PRESET_ALL,
    UPSCALE_TEXTURE_PRESET_BALANCED,
    UPSCALE_TEXTURE_PRESET_COLOR_UI,
    UPSCALE_TEXTURE_PRESET_COLOR_UI_EMISSIVE,
)
from cdmw.core.realesrgan_ncnn import discover_realesrgan_ncnn_models, resolve_ncnn_model_dir
from cdmw.core.texture_pipeline.config import (
    ensure_existing_dir,
    ensure_existing_file,
    normalize_optional_path,
    normalize_required_path,
    parse_filter_patterns,
    require_existing_file,
    validate_choice as _validate_choice,
)
from cdmw.core.texture_pipeline.manifest import resolve_default_staging_png_root
from cdmw.core.texture_pipeline.package_export import (
    build_mod_package_export_options_from_config,
    resolve_default_mod_ready_export_root,
)
from cdmw.domain.textures.profiles import (
    build_default_texture_workflow_profiles,
    build_default_texture_workflow_rules,
    should_seed_default_texture_workflow_state,
    upgrade_default_texture_workflow_state,
)
from cdmw.domain.textures.rules import (
    coerce_texture_workflow_profiles,
    coerce_texture_workflow_rules,
    migrate_legacy_texture_rules_to_structured,
)
from cdmw.models import AppConfig, ModPackageInfo, NormalizedConfig, TextureRule, TextureWorkflowProfile


def _resolve_workflow_profiles_and_rules_from_config(
    config: AppConfig,
) -> Tuple[str, Tuple[TextureWorkflowProfile, ...], Tuple[TextureRule, ...]]:
    raw_text = str(getattr(config, "texture_rules_text", "") or "")
    workflow_profiles = coerce_texture_workflow_profiles(getattr(config, "workflow_profiles", ()))
    texture_rules = coerce_texture_workflow_rules(getattr(config, "texture_rules", ()))
    if not workflow_profiles and not texture_rules and raw_text.strip():
        workflow_profiles, texture_rules = migrate_legacy_texture_rules_to_structured(raw_text)
    elif should_seed_default_texture_workflow_state(workflow_profiles, texture_rules):
        workflow_profiles = build_default_texture_workflow_profiles()
        texture_rules = build_default_texture_workflow_rules()
    workflow_profiles, texture_rules = upgrade_default_texture_workflow_state(workflow_profiles, texture_rules)
    return raw_text, workflow_profiles, texture_rules


def _validate_workflow_rule_profile_links(
    workflow_profiles: Sequence[TextureWorkflowProfile],
    texture_rules: Sequence[TextureRule],
) -> None:
    valid_ids = {profile.profile_id for profile in workflow_profiles}
    for rule in texture_rules:
        target_id = str(getattr(rule, "workflow_profile_id", "") or "").strip()
        if target_id and target_id not in valid_ids:
            raise ValueError(f"Texture workflow rule '{rule.pattern}' references unknown workflow profile id '{target_id}'.")


def normalize_config_for_planning(config: AppConfig) -> NormalizedConfig:
    upscale_backend = str(getattr(config, "upscale_backend", "") or "").strip().lower()
    if upscale_backend not in {
        UPSCALE_BACKEND_NONE,
        UPSCALE_BACKEND_CHAINNER,
        UPSCALE_BACKEND_REALESRGAN_NCNN,
    }:
        upscale_backend = UPSCALE_BACKEND_CHAINNER if config.enable_chainner else UPSCALE_BACKEND_NONE
    texture_rules_text, workflow_profiles, texture_rules = _resolve_workflow_profiles_and_rules_from_config(config)
    _validate_workflow_rule_profile_links(workflow_profiles, texture_rules)

    original_dds_root = ensure_existing_dir(
        normalize_required_path(config.original_dds_root, "Original DDS root"),
        "Original DDS root",
    )
    png_root = normalize_required_path(config.png_root, "PNG root")
    texture_editor_png_root = normalize_optional_path(getattr(config, "texture_editor_png_root", ""))
    output_root = normalize_required_path(config.output_root, "Output root")
    dds_staging_root = normalize_optional_path(config.dds_staging_root)
    csv_log_path = normalize_optional_path(config.csv_log_path) if config.csv_log_enabled else None
    chainner_exe_path = normalize_optional_path(config.chainner_exe_path)
    chainner_chain_path = normalize_optional_path(config.chainner_chain_path)
    ncnn_exe_path = normalize_optional_path(config.ncnn_exe_path)
    explicit_model_dir = normalize_optional_path(config.ncnn_model_dir)
    ncnn_model_dir = resolve_ncnn_model_dir(ncnn_exe_path, explicit_model_dir) or explicit_model_dir
    mod_ready_export_root = normalize_optional_path(config.mod_ready_export_root)
    mod_ready_package_info = ModPackageInfo(
        title=str(getattr(config, "mod_ready_package_title", MOD_READY_PACKAGE_TITLE) or "").strip() or MOD_READY_PACKAGE_TITLE,
        version=str(getattr(config, "mod_ready_package_version", MOD_READY_PACKAGE_VERSION) or "").strip() or MOD_READY_PACKAGE_VERSION,
        author=str(getattr(config, "mod_ready_package_author", MOD_READY_PACKAGE_AUTHOR) or "").strip(),
        description=str(getattr(config, "mod_ready_package_description", MOD_READY_PACKAGE_DESCRIPTION) or "").strip(),
        nexus_url=str(getattr(config, "mod_ready_package_nexus_url", MOD_READY_PACKAGE_NEXUS_URL) or "").strip(),
    )
    mod_ready_export_options = build_mod_package_export_options_from_config(config)

    return NormalizedConfig(
        original_dds_root=original_dds_root,
        png_root=png_root,
        texture_editor_png_root=texture_editor_png_root,
        output_root=output_root,
        dds_staging_root=dds_staging_root,
        dds_format_mode=str(config.dds_format_mode or DEFAULT_DDS_FORMAT_MODE).strip().lower() or DEFAULT_DDS_FORMAT_MODE,
        dds_custom_format=str(config.dds_custom_format or DEFAULT_DDS_CUSTOM_FORMAT).strip() or DEFAULT_DDS_CUSTOM_FORMAT,
        dds_size_mode=str(config.dds_size_mode or DEFAULT_DDS_SIZE_MODE).strip().lower() or DEFAULT_DDS_SIZE_MODE,
        dds_custom_width=int(config.dds_custom_width),
        dds_custom_height=int(config.dds_custom_height),
        dds_mip_mode=str(config.dds_mip_mode or DEFAULT_DDS_MIP_MODE).strip().lower() or DEFAULT_DDS_MIP_MODE,
        dds_custom_mip_count=int(config.dds_custom_mip_count),
        enable_dds_staging=bool(config.enable_dds_staging),
        enable_incremental_resume=bool(config.enable_incremental_resume),
        texture_rules_text=texture_rules_text,
        texture_rules=texture_rules,
        workflow_profiles=workflow_profiles,
        dry_run=bool(config.dry_run),
        csv_log_path=csv_log_path,
        allow_unique_basename_fallback=bool(config.allow_unique_basename_fallback),
        overwrite_existing_dds=bool(config.overwrite_existing_dds),
        include_filter_patterns=parse_filter_patterns(str(config.include_filters or "")),
        upscale_backend=upscale_backend,
        enable_chainner=upscale_backend == UPSCALE_BACKEND_CHAINNER,
        chainner_exe_path=chainner_exe_path,
        chainner_chain_path=chainner_chain_path,
        chainner_override_json=str(config.chainner_override_json or ""),
        ncnn_exe_path=ncnn_exe_path,
        ncnn_model_dir=ncnn_model_dir,
        ncnn_model_name=str(config.ncnn_model_name or "").strip(),
        ncnn_scale=int(getattr(config, "ncnn_scale", REALESRGAN_NCNN_SCALE)),
        ncnn_tile_size=int(getattr(config, "ncnn_tile_size", REALESRGAN_NCNN_TILE_SIZE)),
        ncnn_extra_args=str(getattr(config, "ncnn_extra_args", REALESRGAN_NCNN_EXTRA_ARGS) or "").strip(),
        upscale_post_correction_mode=str(getattr(config, "upscale_post_correction_mode", DEFAULT_UPSCALE_POST_CORRECTION) or "").strip().lower() or DEFAULT_UPSCALE_POST_CORRECTION,
        upscale_texture_preset=str(getattr(config, "upscale_texture_preset", DEFAULT_UPSCALE_TEXTURE_PRESET) or "").strip().lower() or DEFAULT_UPSCALE_TEXTURE_PRESET,
        enable_automatic_texture_rules=bool(getattr(config, "enable_automatic_texture_rules", ENABLE_AUTOMATIC_TEXTURE_RULES)),
        enable_unsafe_technical_override=bool(getattr(config, "enable_unsafe_technical_override", ENABLE_UNSAFE_TECHNICAL_OVERRIDE)),
        retry_smaller_tile_on_failure=bool(getattr(config, "retry_smaller_tile_on_failure", RETRY_SMALLER_TILE_ON_FAILURE)),
        enable_mod_ready_loose_export=bool(getattr(config, "enable_mod_ready_loose_export", ENABLE_MOD_READY_LOOSE_EXPORT)),
        mod_ready_export_root=mod_ready_export_root,
        mod_ready_create_no_encrypt_file=bool(getattr(config, "mod_ready_create_no_encrypt_file", MOD_READY_CREATE_NO_ENCRYPT)),
        mod_ready_package_info=mod_ready_package_info,
        mod_ready_export_options=mod_ready_export_options,
    )


def normalize_config(config: AppConfig, *, validate_backend_runtime: bool = True) -> NormalizedConfig:
    upscale_backend = str(getattr(config, "upscale_backend", "") or "").strip().lower()
    if upscale_backend not in {
        UPSCALE_BACKEND_NONE,
        UPSCALE_BACKEND_CHAINNER,
        UPSCALE_BACKEND_REALESRGAN_NCNN,
    }:
        upscale_backend = UPSCALE_BACKEND_CHAINNER if config.enable_chainner else UPSCALE_BACKEND_NONE
    use_chainner = upscale_backend == UPSCALE_BACKEND_CHAINNER
    use_ncnn = upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN
    texture_rules_text, workflow_profiles, texture_rules = _resolve_workflow_profiles_and_rules_from_config(config)
    _validate_workflow_rule_profile_links(workflow_profiles, texture_rules)

    original_dds_root = ensure_existing_dir(
        normalize_required_path(config.original_dds_root, "Original DDS root"),
        "Original DDS root",
    )
    png_root = normalize_required_path(config.png_root, "PNG root")
    texture_editor_png_root = normalize_optional_path(getattr(config, "texture_editor_png_root", ""))
    if not config.enable_dds_staging and (
        upscale_backend == UPSCALE_BACKEND_NONE
        or (validate_backend_runtime and upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN)
    ):
        ensure_existing_dir(png_root, "PNG root")
    output_root = normalize_required_path(config.output_root, "Output root")

    csv_log_path: Optional[Path] = None
    if config.csv_log_enabled:
        csv_log_path = normalize_optional_path(config.csv_log_path)
        if csv_log_path is None:
            raise ValueError("CSV log is enabled, but the CSV log path is empty.")

    chainner_exe_path: Optional[Path] = None
    chainner_chain_path: Optional[Path] = None
    if use_chainner:
        if validate_backend_runtime:
            chainner_exe_path = ensure_existing_file(
                normalize_required_path(config.chainner_exe_path, "chaiNNer executable path"),
                "chaiNNer executable path",
            )
            chainner_chain_path = ensure_existing_file(
                normalize_required_path(config.chainner_chain_path, "chaiNNer chain path"),
                "chaiNNer chain path",
            )
        else:
            chainner_exe_path = normalize_optional_path(config.chainner_exe_path)
            chainner_chain_path = normalize_optional_path(config.chainner_chain_path)

    ncnn_exe_path: Optional[Path] = None
    ncnn_model_dir: Optional[Path] = None
    ncnn_model_name = ""
    ncnn_scale = int(getattr(config, "ncnn_scale", REALESRGAN_NCNN_SCALE))
    ncnn_tile_size = int(getattr(config, "ncnn_tile_size", REALESRGAN_NCNN_TILE_SIZE))
    ncnn_extra_args = str(getattr(config, "ncnn_extra_args", REALESRGAN_NCNN_EXTRA_ARGS) or "").strip()
    upscale_post_correction_mode = str(
        getattr(config, "upscale_post_correction_mode", DEFAULT_UPSCALE_POST_CORRECTION) or ""
    ).strip().lower() or DEFAULT_UPSCALE_POST_CORRECTION
    upscale_texture_preset = str(getattr(config, "upscale_texture_preset", DEFAULT_UPSCALE_TEXTURE_PRESET) or "").strip().lower() or DEFAULT_UPSCALE_TEXTURE_PRESET
    upscale_post_correction_mode = _validate_choice(
        upscale_post_correction_mode,
        (
            UPSCALE_POST_CORRECTION_NONE,
            UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA,
            UPSCALE_POST_CORRECTION_MATCH_LEVELS,
            UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM,
            UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
            UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED,
            UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL,
        ),
        "post-upscale correction mode",
    )
    if use_ncnn:
        explicit_model_dir = normalize_optional_path(config.ncnn_model_dir)
        if validate_backend_runtime:
            ncnn_exe_path = ensure_existing_file(
                normalize_required_path(config.ncnn_exe_path, "Real-ESRGAN NCNN executable path"),
                "Real-ESRGAN NCNN executable path",
            )
            resolved_model_dir = resolve_ncnn_model_dir(ncnn_exe_path, explicit_model_dir)
            if resolved_model_dir is None:
                raise ValueError(
                    "Real-ESRGAN NCNN model folder is not set and no default 'models' folder was found beside the executable."
                )
            ncnn_model_dir = ensure_existing_dir(resolved_model_dir, "Real-ESRGAN NCNN model folder")
            discovered_models = discover_realesrgan_ncnn_models(ncnn_exe_path, ncnn_model_dir)
            if not discovered_models:
                raise ValueError(f"No Real-ESRGAN NCNN models (.param + .bin) were found in {ncnn_model_dir}.")
            available_model_names = {name for name, _ in discovered_models}
            ncnn_model_name = config.ncnn_model_name.strip() or next(iter(sorted(available_model_names)))
            if ncnn_model_name not in available_model_names:
                raise ValueError(
                    f"Real-ESRGAN NCNN model '{ncnn_model_name}' was not found in {ncnn_model_dir}."
                )
            for workflow_profile in workflow_profiles:
                if workflow_profile.ncnn_model_name and workflow_profile.ncnn_model_name not in available_model_names:
                    raise ValueError(
                        f"Workflow profile '{workflow_profile.label}' references missing Real-ESRGAN NCNN model '{workflow_profile.ncnn_model_name}'."
                    )
        else:
            ncnn_exe_path = normalize_optional_path(config.ncnn_exe_path)
            ncnn_model_dir = resolve_ncnn_model_dir(ncnn_exe_path, explicit_model_dir) or explicit_model_dir
            ncnn_model_name = config.ncnn_model_name.strip()
        if ncnn_scale not in {2, 3, 4}:
            raise ValueError("Real-ESRGAN NCNN scale must be 2, 3, or 4.")
        if ncnn_tile_size < 0:
            raise ValueError("Real-ESRGAN NCNN tile size must be 0 or greater.")
        if upscale_texture_preset not in {
            UPSCALE_TEXTURE_PRESET_BALANCED,
            UPSCALE_TEXTURE_PRESET_COLOR_UI,
            UPSCALE_TEXTURE_PRESET_COLOR_UI_EMISSIVE,
            UPSCALE_TEXTURE_PRESET_ALL,
        }:
            raise ValueError(f"Unknown upscale texture preset: {upscale_texture_preset}")

    enable_automatic_texture_rules = bool(getattr(config, "enable_automatic_texture_rules", ENABLE_AUTOMATIC_TEXTURE_RULES))
    enable_unsafe_technical_override = bool(getattr(config, "enable_unsafe_technical_override", ENABLE_UNSAFE_TECHNICAL_OVERRIDE))
    retry_smaller_tile_on_failure = bool(getattr(config, "retry_smaller_tile_on_failure", RETRY_SMALLER_TILE_ON_FAILURE))
    enable_mod_ready_loose_export = bool(getattr(config, "enable_mod_ready_loose_export", ENABLE_MOD_READY_LOOSE_EXPORT))
    mod_ready_export_root: Optional[Path] = None
    if enable_mod_ready_loose_export:
        explicit_mod_ready_export_root = normalize_optional_path(getattr(config, "mod_ready_export_root", ""))
        mod_ready_export_root = explicit_mod_ready_export_root or resolve_default_mod_ready_export_root(output_root)
        if mod_ready_export_root.resolve() == output_root.resolve():
            raise ValueError("Mod-ready export root must be different from the main output root.")
    mod_ready_package_info = ModPackageInfo(
        title=str(getattr(config, "mod_ready_package_title", MOD_READY_PACKAGE_TITLE) or "").strip() or MOD_READY_PACKAGE_TITLE,
        version=str(getattr(config, "mod_ready_package_version", MOD_READY_PACKAGE_VERSION) or "").strip() or MOD_READY_PACKAGE_VERSION,
        author=str(getattr(config, "mod_ready_package_author", MOD_READY_PACKAGE_AUTHOR) or "").strip(),
        description=str(getattr(config, "mod_ready_package_description", MOD_READY_PACKAGE_DESCRIPTION) or "").strip(),
        nexus_url=str(getattr(config, "mod_ready_package_nexus_url", MOD_READY_PACKAGE_NEXUS_URL) or "").strip(),
    )
    mod_ready_export_options = build_mod_package_export_options_from_config(config)

    dds_staging_root: Optional[Path] = None
    if config.enable_dds_staging:
        if config.dds_staging_root.strip():
            dds_staging_root = normalize_required_path(config.dds_staging_root, "DDS staging root")
        else:
            dds_staging_root = resolve_default_staging_png_root(png_root, use_chainner or use_ncnn).resolve()
        if validate_backend_runtime and (use_chainner or use_ncnn) and dds_staging_root.resolve() == png_root.resolve():
            raise ValueError("DDS staging root must be different from the final PNG root when an upscaling backend is enabled.")

    dds_format_mode = _validate_choice(
        config.dds_format_mode,
        (DDS_FORMAT_MODE_MATCH_ORIGINAL, DDS_FORMAT_MODE_CUSTOM),
        "DDS format mode",
    )
    dds_size_mode = _validate_choice(
        config.dds_size_mode,
        (DDS_SIZE_MODE_PNG, DDS_SIZE_MODE_ORIGINAL, DDS_SIZE_MODE_CUSTOM),
        "DDS size mode",
    )
    dds_mip_mode = _validate_choice(
        config.dds_mip_mode,
        (DDS_MIP_MODE_MATCH_ORIGINAL, DDS_MIP_MODE_FULL_CHAIN, DDS_MIP_MODE_SINGLE, DDS_MIP_MODE_CUSTOM),
        "DDS mip mode",
    )

    dds_custom_format = config.dds_custom_format.strip() or DEFAULT_DDS_CUSTOM_FORMAT
    if dds_format_mode == DDS_FORMAT_MODE_CUSTOM and dds_custom_format not in SUPPORTED_DDS_FORMAT_CHOICES:
        raise ValueError(f"Unsupported custom DDS format: {dds_custom_format}")

    dds_custom_width = int(config.dds_custom_width)
    dds_custom_height = int(config.dds_custom_height)
    dds_custom_mip_count = int(config.dds_custom_mip_count)
    if dds_size_mode == DDS_SIZE_MODE_CUSTOM:
        if dds_custom_width < 1 or dds_custom_height < 1:
            raise ValueError("Custom DDS size must be at least 1x1.")
    if dds_mip_mode == DDS_MIP_MODE_CUSTOM and dds_custom_mip_count < 1:
        raise ValueError("Custom DDS mip count must be at least 1.")

    return NormalizedConfig(
        original_dds_root=original_dds_root,
        png_root=png_root,
        texture_editor_png_root=texture_editor_png_root,
        output_root=output_root,
        dds_staging_root=dds_staging_root,
        dds_format_mode=dds_format_mode,
        dds_custom_format=dds_custom_format,
        dds_size_mode=dds_size_mode,
        dds_custom_width=dds_custom_width,
        dds_custom_height=dds_custom_height,
        dds_mip_mode=dds_mip_mode,
        dds_custom_mip_count=dds_custom_mip_count,
        enable_dds_staging=config.enable_dds_staging,
        enable_incremental_resume=config.enable_incremental_resume,
        texture_rules_text=texture_rules_text,
        dry_run=config.dry_run,
        csv_log_path=csv_log_path,
        allow_unique_basename_fallback=config.allow_unique_basename_fallback,
        overwrite_existing_dds=config.overwrite_existing_dds,
        include_filter_patterns=parse_filter_patterns(config.include_filters),
        upscale_backend=upscale_backend,
        enable_chainner=use_chainner,
        chainner_exe_path=chainner_exe_path,
        chainner_chain_path=chainner_chain_path,
        chainner_override_json=config.chainner_override_json,
        ncnn_exe_path=ncnn_exe_path,
        ncnn_model_dir=ncnn_model_dir,
        ncnn_model_name=ncnn_model_name,
        ncnn_scale=ncnn_scale,
        ncnn_tile_size=ncnn_tile_size,
        ncnn_extra_args=ncnn_extra_args,
        upscale_post_correction_mode=upscale_post_correction_mode,
        upscale_texture_preset=upscale_texture_preset,
        enable_automatic_texture_rules=enable_automatic_texture_rules,
        enable_unsafe_technical_override=enable_unsafe_technical_override,
        retry_smaller_tile_on_failure=retry_smaller_tile_on_failure,
        enable_mod_ready_loose_export=enable_mod_ready_loose_export,
        mod_ready_export_root=mod_ready_export_root,
        mod_ready_create_no_encrypt_file=bool(getattr(config, "mod_ready_create_no_encrypt_file", MOD_READY_CREATE_NO_ENCRYPT)),
        mod_ready_package_info=mod_ready_package_info,
        mod_ready_export_options=mod_ready_export_options,
        texture_rules=texture_rules,
        workflow_profiles=workflow_profiles,
    )


def validate_backend_runtime_requirements(normalized: NormalizedConfig) -> NormalizedConfig:
    backend = normalized.upscale_backend
    if backend == UPSCALE_BACKEND_NONE:
        return normalized

    if normalized.enable_dds_staging and normalized.dds_staging_root is not None:
        if normalized.dds_staging_root.resolve() == normalized.png_root.resolve():
            raise ValueError("DDS staging root must be different from the final PNG root when an upscaling backend is enabled.")

    if backend == UPSCALE_BACKEND_CHAINNER:
        normalized.chainner_exe_path = require_existing_file(normalized.chainner_exe_path, "chaiNNer executable path")
        normalized.chainner_chain_path = require_existing_file(normalized.chainner_chain_path, "chaiNNer chain path")
        return normalized

    if backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
        normalized.ncnn_exe_path = require_existing_file(normalized.ncnn_exe_path, "Real-ESRGAN NCNN executable path")
        if not normalized.enable_dds_staging:
            ensure_existing_dir(normalized.png_root, "PNG root")
        resolved_model_dir = resolve_ncnn_model_dir(normalized.ncnn_exe_path, normalized.ncnn_model_dir)
        if resolved_model_dir is None:
            raise ValueError(
                "Real-ESRGAN NCNN model folder is not set and no default 'models' folder was found beside the executable."
            )
        normalized.ncnn_model_dir = ensure_existing_dir(resolved_model_dir, "Real-ESRGAN NCNN model folder")
        discovered_models = discover_realesrgan_ncnn_models(normalized.ncnn_exe_path, normalized.ncnn_model_dir)
        if not discovered_models:
            raise ValueError(f"No Real-ESRGAN NCNN models (.param + .bin) were found in {normalized.ncnn_model_dir}.")
        available_model_names = {name for name, _ in discovered_models}
        normalized.ncnn_model_name = normalized.ncnn_model_name.strip() or next(iter(sorted(available_model_names)))
        if normalized.ncnn_model_name not in available_model_names:
            raise ValueError(
                f"Real-ESRGAN NCNN model '{normalized.ncnn_model_name}' was not found in {normalized.ncnn_model_dir}."
            )
        return normalized

    return normalized
