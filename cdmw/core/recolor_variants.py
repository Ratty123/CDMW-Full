from __future__ import annotations

import dataclasses
import fnmatch
import json
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

import numpy as np
from PIL import Image

from cdmw.core.common import raise_if_cancelled, run_process_with_cancellation
from cdmw.core.mod_package import (
    ModPackageExportOptions,
    normalize_mod_package_payload_path,
    resolve_mod_package_root,
    write_mod_package_manifest,
)
from cdmw.core.texture_pipeline.inspection import parse_dds, read_png_dimensions
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.texture_pipeline.texconv import build_texconv_command
from cdmw.domain.textures.output import max_mips_for_size
from cdmw.core.texture_editor import apply_texture_editor_recolor, save_rgba_array_png
from cdmw.core.texture_native import encode_dds_with_directxtex
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.core.upscale_profiles import copy_mod_ready_loose_tree, infer_texture_semantics, is_technical_texture_type
from cdmw.modding.working_mod_recipe import analyze_working_mod_package
from cdmw.models import ModPackageInfo, RunCancelled, TextureEditorToolSettings


_KNOWN_PAYLOAD_ROOTS = frozenset(
    {
        "character",
        "effect",
        "gamedata",
        "leveldata",
        "meta",
        "object",
        "tree",
        "ui",
        "vehicle",
        "world",
    }
)
_VISIBLE_TEXTURE_TYPES = frozenset({"color", "ui", "emissive", "impostor"})
_SAFE_TEXTURE_SLOT_KINDS = frozenset({"base", "emissive"})
_TECHNICAL_TEXTURE_SUFFIXES = ("_n.dds", "_wn.dds", "_ma.dds", "_mg.dds", "_sp.dds", "_m.dds", "_disp.dds")
_VALUE_ATTR_RE = re.compile(r"(?P<name>Value|_value|value)\s*=\s*\"(?P<value>[^\"]*)\"", re.IGNORECASE)
_ATTR_RE = re.compile(r"([A-Za-z0-9_:.-]+)\s*=\s*\"([^\"]*)\"", re.IGNORECASE)
_COLOR_PARAM_RE = re.compile(
    r"<MaterialParameterColor\b(?P<attrs>[^>]*)/?>",
    re.IGNORECASE | re.DOTALL,
)


@dataclasses.dataclass(frozen=True, slots=True)
class RecolorVariantRule:
    rule_id: str = ""
    label: str = ""
    enabled: bool = True
    target_kind: str = "texture_slot"
    slot_kind: str = "base"
    filename_glob: str = "*.dds"
    parameter_name: str = "*"
    operation: str = "tint"
    source_color: str = "#808080"
    target_color: str = "#C85A30"
    tolerance: int = 48
    strength: int = 100
    preserve_luminance: bool = True


@dataclasses.dataclass(frozen=True, slots=True)
class RecolorVariantTemplate:
    template_id: str = ""
    name: str = ""
    description: str = ""
    rules: tuple[RecolorVariantRule, ...] = ()
    created_utc: str = ""
    updated_utc: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class RecolorVariantTarget:
    target_id: str
    target_kind: str
    game_path: str
    member_path: str = ""
    label: str = ""
    slot_kind: str = ""
    parameter_name: str = ""
    current_value: str = ""
    texture_type: str = "unknown"
    semantic_subtype: str = "unknown"
    editable: bool = False
    locked_reason: str = ""
    width: int = 0
    height: int = 0
    mip_count: int = 0
    texconv_format: str = ""
    consumers: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class RecolorVariantAnalysis:
    package_path: str
    package_kind: str
    package_info: ModPackageInfo
    payload_paths: tuple[str, ...] = ()
    targets: tuple[RecolorVariantTarget, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def editable_targets(self) -> tuple[RecolorVariantTarget, ...]:
        return tuple(target for target in self.targets if target.editable)


@dataclasses.dataclass(frozen=True, slots=True)
class RecolorVariantOutputProfile:
    profile_id: str = "dmm"
    label: str = "Definitive Mod Manager"
    enabled: bool = True
    package_title_suffix: str = ""
    package_info: Optional[ModPackageInfo] = None
    export_options: Optional[ModPackageExportOptions] = None


@dataclasses.dataclass(frozen=True, slots=True)
class RecolorVariantBuildResult:
    source_package_path: str
    output_roots: tuple[Path, ...] = ()
    changed_texture_paths: tuple[str, ...] = ()
    changed_material_paths: tuple[str, ...] = ()
    copied_payload_paths: tuple[str, ...] = ()
    skipped_targets: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return bool(self.output_roots) and not self.errors


@dataclasses.dataclass(frozen=True, slots=True)
class RecolorVariantPreview:
    matched_target_ids: tuple[str, ...] = ()
    matched_texture_paths: tuple[str, ...] = ()
    matched_material_paths: tuple[str, ...] = ()
    skipped_targets: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class RecolorVariantPreviewImage:
    target_id: str
    source_dds_path: Path
    source_png: Path
    preview_png: Path
    warnings: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class _PackageMember:
    member_path: str
    payload_path: str
    source_path: Optional[Path] = None


def default_recolor_variant_templates() -> tuple[RecolorVariantTemplate, ...]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        RecolorVariantTemplate(
            template_id="basecolor_tint",
            name="Basecolor Tint",
            description="Tint safe visible base/overlay textures while preserving source shading.",
            created_utc=now,
            updated_utc=now,
            rules=(
                RecolorVariantRule(
                    rule_id="base_slot_tint",
                    label="Safe base texture tint",
                    target_kind="texture_slot",
                    slot_kind="base",
                    filename_glob="*.dds",
                    operation="tint",
                    target_color="#C85A30",
                    strength=100,
                    preserve_luminance=True,
                ),
            ),
        ),
    )


def recolor_variant_templates_path(base_dir: Path) -> Path:
    return Path(base_dir).expanduser().resolve() / "recolor_variant_templates.json"


def load_recolor_variant_templates(base_dir: Path) -> tuple[RecolorVariantTemplate, ...]:
    path = recolor_variant_templates_path(base_dir)
    if not path.is_file():
        return default_recolor_variant_templates()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_recolor_variant_templates()
    items = payload.get("templates") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return default_recolor_variant_templates()
    templates = tuple(_template_from_dict(item) for item in items if isinstance(item, Mapping))
    return templates or default_recolor_variant_templates()


def save_recolor_variant_templates(base_dir: Path, templates: Sequence[RecolorVariantTemplate]) -> Path:
    path = recolor_variant_templates_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "templates": [_template_to_dict(template) for template in templates],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def export_recolor_variant_templates(base_dir: Path, export_path: Path) -> Path:
    path = Path(export_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "templates": [_template_to_dict(template) for template in load_recolor_variant_templates(base_dir)],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def import_recolor_variant_templates(
    base_dir: Path,
    import_path: Path,
    *,
    merge: bool = True,
) -> tuple[RecolorVariantTemplate, ...]:
    payload = json.loads(Path(import_path).expanduser().read_text(encoding="utf-8"))
    items = payload.get("templates") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("Template import must contain a JSON array or a templates array.")
    imported = tuple(_template_from_dict(item) for item in items if isinstance(item, Mapping))
    if not merge:
        save_recolor_variant_templates(base_dir, imported)
        return imported

    merged: list[RecolorVariantTemplate] = list(load_recolor_variant_templates(base_dir))
    by_id = {template.template_id: index for index, template in enumerate(merged)}
    for template in imported:
        if template.template_id in by_id:
            merged[by_id[template.template_id]] = template
        else:
            by_id[template.template_id] = len(merged)
            merged.append(template)
    save_recolor_variant_templates(base_dir, merged)
    return tuple(merged)


def analyze_recolor_variant_package(
    package_path: Path | str,
    *,
    stop_event: Optional[threading.Event] = None,
) -> RecolorVariantAnalysis:
    resolved = Path(package_path).expanduser()
    raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
    recipe_analysis = analyze_working_mod_package(resolved, stop_event=stop_event)
    raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
    warnings = list(recipe_analysis.warnings)
    members = _list_package_members(resolved, warnings, stop_event=stop_event)
    package_members = _payload_members(resolved, members, stop_event=stop_event)
    payload_paths = tuple(sorted({member.payload_path for member in package_members.values()}))
    member_by_payload = {member.payload_path.casefold(): member for member in package_members.values()}
    dds_member_by_basename: dict[str, _PackageMember] = {}
    for member in package_members.values():
        raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
        if PurePosixPath(member.payload_path).suffix.lower() == ".dds":
            dds_member_by_basename.setdefault(PurePosixPath(member.payload_path).name.lower(), member)

    package_info = _package_info_from_analysis(resolved, recipe_analysis.manifest, recipe_analysis.modinfo)
    targets: list[RecolorVariantTarget] = []
    texture_state: dict[str, RecolorVariantTarget] = {}

    for recipe in recipe_analysis.recipes:
        raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
        consumer = recipe.submesh_name or recipe.material_name or recipe.sidecar_path
        for binding in recipe.texture_bindings:
            raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
            payload_path = normalize_mod_package_payload_path(binding.texture_path).as_posix().strip("/")
            member = member_by_payload.get(payload_path.casefold())
            if member is None and binding.source_member_path:
                normalized_member_payload = normalize_mod_package_payload_path(binding.source_member_path).as_posix().strip("/")
                member = member_by_payload.get(normalized_member_payload.casefold())
            if member is None:
                member = dds_member_by_basename.get(PurePosixPath(binding.texture_path).name.lower())
            state_key = payload_path.casefold() if payload_path else binding.texture_path.casefold()
            existing = texture_state.get(state_key)
            consumers = tuple(dict.fromkeys((*(existing.consumers if existing is not None else ()), consumer)))
            if existing is not None:
                texture_state[state_key] = dataclasses.replace(existing, consumers=consumers)
                continue

            target_path = member.payload_path if member is not None else payload_path
            texture_type, semantic_subtype, editable, locked_reason = _classify_texture_target(
                target_path or binding.texture_path,
                binding.slot_kind,
                sidecar_text=recipe.sidecar_text,
                included=member is not None,
            )
            width = height = mip_count = 0
            texconv_format = ""
            if member is not None:
                try:
                    dds_info = _parse_member_dds_info(resolved, member)
                    width = int(dds_info.width)
                    height = int(dds_info.height)
                    mip_count = int(dds_info.mip_count)
                    texconv_format = dds_info.texconv_format
                except Exception as exc:
                    editable = False
                    locked_reason = f"DDS metadata could not be read: {exc}"
            target = RecolorVariantTarget(
                target_id=_target_id("texture_slot", target_path or binding.texture_path, binding.slot_kind),
                target_kind="texture_slot",
                game_path=target_path or binding.texture_path,
                member_path=member.member_path if member is not None else "",
                label=PurePosixPath(target_path or binding.texture_path).name,
                slot_kind=binding.slot_kind,
                parameter_name=binding.parameter_name,
                texture_type=texture_type,
                semantic_subtype=semantic_subtype,
                editable=editable,
                locked_reason=locked_reason,
                width=width,
                height=height,
                mip_count=mip_count,
                texconv_format=texconv_format,
                consumers=consumers,
            )
            texture_state[state_key] = target

    targets.extend(sorted(texture_state.values(), key=lambda target: (not target.editable, target.game_path.lower())))
    targets.extend(_material_color_targets(resolved, recipe_analysis.sidecar_paths, stop_event=stop_event))

    if not any(target.editable for target in targets):
        warnings.append("No safe editable recolor targets were detected.")

    return RecolorVariantAnalysis(
        package_path=str(resolved),
        package_kind=recipe_analysis.package_kind,
        package_info=package_info,
        payload_paths=payload_paths,
        targets=tuple(targets),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def preview_recolor_variant_template(
    analysis: RecolorVariantAnalysis,
    template: RecolorVariantTemplate,
) -> RecolorVariantPreview:
    matched_ids: list[str] = []
    texture_paths: list[str] = []
    material_paths: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    for target in analysis.targets:
        rule = _matching_rule(target, template.rules)
        if rule is None:
            continue
        if not target.editable:
            skipped.append(f"{target.label or target.game_path}: {target.locked_reason or 'locked'}")
            continue
        matched_ids.append(target.target_id)
        if target.target_kind == "texture_slot":
            texture_paths.append(target.game_path)
        elif target.target_kind == "material_color":
            material_paths.append(f"{target.game_path}:{target.parameter_name}")
    if not matched_ids:
        warnings.append("Template does not match any editable targets in this package.")
    return RecolorVariantPreview(
        matched_target_ids=tuple(matched_ids),
        matched_texture_paths=tuple(dict.fromkeys(texture_paths)),
        matched_material_paths=tuple(dict.fromkeys(material_paths)),
        skipped_targets=tuple(skipped),
        warnings=tuple(warnings),
    )


def matching_recolor_variant_rule(
    target: RecolorVariantTarget,
    rules: Sequence[RecolorVariantRule],
) -> Optional[RecolorVariantRule]:
    return _matching_rule(target, rules)


def texture_editor_settings_for_recolor_variant_rule(rule: RecolorVariantRule) -> TextureEditorToolSettings:
    return _texture_editor_settings_for_recolor_rule(rule)


def preview_recolor_variant_target_image(
    analysis: RecolorVariantAnalysis,
    template: RecolorVariantTemplate,
    target_id: str,
    *,
    texconv_path: Optional[Path] = None,
    max_dimension: int = 1024,
    stop_event: Optional[threading.Event] = None,
) -> RecolorVariantPreviewImage:
    target = next((candidate for candidate in analysis.targets if candidate.target_id == target_id), None)
    if target is None:
        raise ValueError("Recolor preview target was not found in the current analysis.")
    if target.target_kind != "texture_slot":
        raise ValueError("Only DDS texture targets can be opened in the visual recolor preview.")
    if not target.editable:
        raise ValueError(target.locked_reason or "Selected target is locked for safe recolor variants.")
    rule = _matching_rule(target, template.rules)
    if rule is None:
        raise ValueError("Current recolor template does not match the selected texture target.")

    preview_root = app_temp_cache_path("preview_cache", "recolor_variants", uuid.uuid4().hex)
    preview_root.mkdir(parents=True, exist_ok=True)
    try:
        raise_if_cancelled(stop_event, "Recolor target preview cancelled.")
        source_dds = _materialize_target_dds_for_preview(analysis, target, preview_root)
        raise_if_cancelled(stop_event, "Recolor target preview cancelled.")

        dds_info = parse_dds(source_dds)
        source_display_png = ensure_dds_display_preview_png(
            texconv_path if texconv_path is not None and texconv_path.is_file() else None,
            source_dds,
            dds_info=dds_info,
            max_dimension=max(1, int(max_dimension)),
            slot_kind=target.slot_kind or "base",
            stop_event=stop_event,
        )
        source_png = preview_root / "source.png"
        preview_png = preview_root / "preview.png"
        with Image.open(source_display_png) as image:
            rgba = image.convert("RGBA")
            pixels = np.asarray(rgba, dtype=np.uint8).copy()
            rgba.save(source_png)
        raise_if_cancelled(stop_event, "Recolor target preview cancelled.")
        edited = apply_texture_editor_recolor(pixels, _texture_editor_settings_for_recolor_rule(rule))
        raise_if_cancelled(stop_event, "Recolor target preview cancelled.")
        save_rgba_array_png(edited, preview_png)
    except BaseException:
        shutil.rmtree(preview_root, ignore_errors=True)
        raise
    request_app_temp_cache_prune()
    return RecolorVariantPreviewImage(
        target_id=target.target_id,
        source_dds_path=source_dds,
        source_png=source_png,
        preview_png=preview_png,
    )


def _remove_recolor_output_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _publish_recolor_output_paths(
    paths: Sequence[tuple[Path, Path]],
    *,
    stop_event: Optional[threading.Event],
) -> None:
    published: list[tuple[Path, Optional[Path]]] = []
    try:
        for staged_path, final_path in paths:
            raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
            backup_path: Optional[Path] = None
            if final_path.exists() or final_path.is_symlink():
                backup_path = final_path.with_name(f"cdmw-recolor-backup-{uuid.uuid4().hex}-{final_path.name}")
                final_path.replace(backup_path)
            try:
                staged_path.replace(final_path)
            except BaseException:
                if backup_path is not None and backup_path.exists():
                    backup_path.replace(final_path)
                raise
            published.append((final_path, backup_path))
    except BaseException:
        for final_path, backup_path in reversed(published):
            _remove_recolor_output_path(final_path)
            if backup_path is not None and backup_path.exists():
                backup_path.replace(final_path)
        raise
    else:
        for _final_path, backup_path in published:
            if backup_path is not None and backup_path.exists():
                _remove_recolor_output_path(backup_path)


def build_recolor_variant_outputs(
    analysis: RecolorVariantAnalysis,
    template: RecolorVariantTemplate,
    output_root: Path,
    output_profiles: Sequence[RecolorVariantOutputProfile],
    *,
    texconv_path: Optional[Path] = None,
    overwrite_existing: bool = False,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> RecolorVariantBuildResult:
    raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
    enabled_profiles = tuple(profile for profile in output_profiles if profile.enabled)
    if not enabled_profiles:
        return RecolorVariantBuildResult(
            source_package_path=analysis.package_path,
            errors=("At least one output profile must be enabled.",),
        )
    preview = preview_recolor_variant_template(analysis, template)
    if not preview.matched_target_ids:
        return RecolorVariantBuildResult(
            source_package_path=analysis.package_path,
            skipped_targets=preview.skipped_targets,
            warnings=preview.warnings,
            errors=("Template does not match any editable targets.",),
        )

    source_package = Path(analysis.package_path).expanduser()
    resolved_output_root = Path(output_root).expanduser().resolve()
    if source_package.exists():
        try:
            source_resolved = source_package.resolve()
            if resolved_output_root == source_resolved or source_resolved in resolved_output_root.parents:
                return RecolorVariantBuildResult(
                    source_package_path=analysis.package_path,
                    errors=("Output root cannot be inside the source mod package.",),
                )
        except OSError:
            pass

    scratch_root = Path(tempfile.mkdtemp(prefix="cdmw_recolor_variant_work_"))
    staged_output_paths: list[Path] = []
    output_roots: list[Path] = []
    changed_texture_paths: list[str] = []
    changed_material_paths: list[str] = []
    copied_paths: list[str] = []
    warnings = list(preview.warnings)
    errors: list[str] = []

    try:
        source_stage = scratch_root / "source_payloads"
        source_stage.mkdir(parents=True, exist_ok=True)
        _copy_source_payloads_to_stage(
            source_package,
            analysis.payload_paths,
            source_stage,
            stop_event=stop_event,
            on_log=on_log,
        )
        copied_paths.extend(analysis.payload_paths)

        matched_targets = {target.target_id: target for target in analysis.targets if target.target_id in set(preview.matched_target_ids)}
        texture_targets = [target for target in matched_targets.values() if target.target_kind == "texture_slot"]
        material_targets = [target for target in matched_targets.values() if target.target_kind == "material_color"]
        total_steps = len(texture_targets) + len(material_targets) + len(enabled_profiles)
        completed_steps = 0

        for target in texture_targets:
            raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
            rule = _matching_rule(target, template.rules)
            if rule is None:
                continue
            source_dds = source_stage / Path(PurePosixPath(target.game_path).as_posix())
            if not source_dds.is_file():
                warnings.append(f"Skipped missing texture payload: {target.game_path}")
                continue
            try:
                _apply_texture_rule_to_dds(
                    source_dds,
                    rule,
                    texconv_path=texconv_path,
                    scratch_root=scratch_root / "textures" / _safe_slug(target.target_id),
                    stop_event=stop_event,
                    on_log=on_log,
                )
                changed_texture_paths.append(target.game_path)
            except Exception as exc:
                errors.append(f"{target.game_path}: {exc}")
            completed_steps += 1
            if on_progress:
                on_progress(completed_steps, total_steps, f"{completed_steps} / {total_steps} steps")

        sidecar_targets_by_path: dict[str, list[tuple[RecolorVariantTarget, RecolorVariantRule]]] = {}
        for target in material_targets:
            rule = _matching_rule(target, template.rules)
            if rule is None:
                continue
            sidecar_targets_by_path.setdefault(target.game_path, []).append((target, rule))

        for sidecar_path, entries in sidecar_targets_by_path.items():
            raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
            sidecar_file = source_stage / Path(PurePosixPath(sidecar_path).as_posix())
            if not sidecar_file.is_file():
                warnings.append(f"Skipped missing material sidecar payload: {sidecar_path}")
                continue
            try:
                text = sidecar_file.read_text(encoding="utf-8-sig", errors="replace")
                updated_text, changed_names = _apply_material_color_rules(text, entries)
                if changed_names:
                    sidecar_file.write_text(updated_text, encoding="utf-8")
                    changed_material_paths.extend(f"{sidecar_path}:{name}" for name in changed_names)
            except Exception as exc:
                errors.append(f"{sidecar_path}: {exc}")
            completed_steps += len(entries)
            if on_progress:
                on_progress(min(completed_steps, total_steps), total_steps, f"{min(completed_steps, total_steps)} / {total_steps} steps")

        if errors:
            return RecolorVariantBuildResult(
                source_package_path=analysis.package_path,
                changed_texture_paths=tuple(dict.fromkeys(changed_texture_paths)),
                changed_material_paths=tuple(dict.fromkeys(changed_material_paths)),
                copied_payload_paths=tuple(dict.fromkeys(copied_paths)),
                skipped_targets=preview.skipped_targets,
                warnings=tuple(dict.fromkeys(warnings)),
                errors=tuple(errors),
            )

        profile_plans: list[tuple[RecolorVariantOutputProfile, ModPackageInfo, Path, ModPackageExportOptions]] = []
        seen_output_roots: set[str] = set()
        for profile in enabled_profiles:
            raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
            package_info = _profile_package_info(analysis.package_info, template, profile)
            final_root = _profile_output_root(resolved_output_root, package_info, profile)
            output_key = str(final_root.absolute()).casefold()
            if output_key in seen_output_roots:
                errors.append(f"Multiple output profiles resolve to the same folder: {final_root}")
                continue
            seen_output_roots.add(output_key)
            if final_root.exists() and not final_root.is_dir():
                errors.append(f"Output path exists and is not a folder: {final_root}")
                continue
            if not overwrite_existing and final_root.exists() and any(final_root.iterdir()):
                errors.append(f"Output already exists and is not empty: {final_root}")
                continue
            export_options = profile.export_options or recolor_export_options_for_manager(profile.profile_id)
            profile_plans.append((profile, package_info, final_root, export_options))

        if errors:
            return RecolorVariantBuildResult(
                source_package_path=analysis.package_path,
                changed_texture_paths=tuple(dict.fromkeys(changed_texture_paths)),
                changed_material_paths=tuple(dict.fromkeys(changed_material_paths)),
                copied_payload_paths=tuple(dict.fromkeys(copied_paths)),
                skipped_targets=preview.skipped_targets,
                warnings=tuple(dict.fromkeys(warnings)),
                errors=tuple(errors),
            )

        publication_paths: list[tuple[Path, Path]] = []
        for profile, package_info, final_root, export_options in profile_plans:
            raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
            final_root.parent.mkdir(parents=True, exist_ok=True)
            staging_parent = Path(tempfile.mkdtemp(prefix="cdmw-recolor-stage-", dir=final_root.parent))
            staged_output_paths.append(staging_parent)
            staged_root = staging_parent / final_root.name
            copy_result = copy_mod_ready_loose_tree(
                source_stage,
                staged_root,
                overwrite=True,
                dry_run=False,
                on_log=on_log,
                stop_event=stop_event,
            )
            if copy_result.failed_files:
                raise OSError(f"Could not stage {copy_result.failed_files} recolor output file(s).")
            write_mod_package_manifest(
                staged_root,
                package_info,
                kind="mesh_loose_mod" if any(path.lower().endswith((".pac", ".pam", ".pamlod")) for path in analysis.payload_paths) else "dds_loose_mod",
                extra_fields={
                    "recolor_variant": {
                        "source_package": analysis.package_path,
                        "template_id": template.template_id,
                        "template_name": template.name,
                        "changed_textures": tuple(dict.fromkeys(changed_texture_paths)),
                        "changed_material_values": tuple(dict.fromkeys(changed_material_paths)),
                    },
                    "file_count": len(analysis.payload_paths),
                },
                all_payload_paths=analysis.payload_paths,
                export_options=export_options,
                create_no_encrypt_file=export_options.create_no_encrypt_file,
            )
            if profile.profile_id.strip().lower() == "jmm":
                _write_jmm_mod_json(staged_root, package_info, analysis.payload_paths)
            publication_paths.append((staged_root, final_root))
            if export_options.create_zip:
                staged_zip = staged_root.with_suffix(".zip")
                if not staged_zip.is_file():
                    raise OSError(f"Recolor output ZIP was not staged: {staged_zip}")
                publication_paths.append((staged_zip, final_root.with_suffix(".zip")))
            completed_steps += 1
            if on_progress:
                on_progress(min(completed_steps, total_steps), total_steps, f"{min(completed_steps, total_steps)} / {total_steps} steps")

        raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
        _publish_recolor_output_paths(publication_paths, stop_event=stop_event)
        output_roots.extend(final_root for _profile, _package_info, final_root, _export_options in profile_plans)
        for final_root in output_roots:
            if on_log:
                on_log(f"Wrote recolor variant output: {final_root}")

        return RecolorVariantBuildResult(
            source_package_path=analysis.package_path,
            output_roots=tuple(output_roots),
            changed_texture_paths=tuple(dict.fromkeys(changed_texture_paths)),
            changed_material_paths=tuple(dict.fromkeys(changed_material_paths)),
            copied_payload_paths=tuple(dict.fromkeys(copied_paths)),
            skipped_targets=preview.skipped_targets,
            warnings=tuple(dict.fromkeys(warnings)),
            errors=tuple(errors),
        )
    except RunCancelled:
        raise
    finally:
        for staged_path in staged_output_paths:
            shutil.rmtree(staged_path, ignore_errors=True)
        shutil.rmtree(scratch_root, ignore_errors=True)


def recolor_export_options_for_manager(profile_id: str) -> ModPackageExportOptions:
    normalized = str(profile_id or "dmm").strip().lower()
    if normalized == "jmm":
        return ModPackageExportOptions(
            manager_targets=("jmm",),
            structure="game_relative",
            create_manifest_json=False,
            create_mod_json=False,
            create_modinfo_json=False,
            create_info_json=False,
            create_no_encrypt_file=False,
            create_zip=False,
        )
    from cdmw.core.mod_package import mod_package_export_options_for_manager

    return mod_package_export_options_for_manager(normalized)


def default_recolor_output_profiles() -> tuple[RecolorVariantOutputProfile, ...]:
    return (
        RecolorVariantOutputProfile(
            profile_id="dmm",
            label="Definitive Mod Manager",
            enabled=True,
            export_options=recolor_export_options_for_manager("dmm"),
        ),
        RecolorVariantOutputProfile(
            profile_id="cdumm",
            label="CDUMM",
            enabled=False,
            package_title_suffix="CDUMM",
            export_options=recolor_export_options_for_manager("cdumm"),
        ),
        RecolorVariantOutputProfile(
            profile_id="jmm",
            label="JMM JSON",
            enabled=False,
            package_title_suffix="JMM",
            export_options=recolor_export_options_for_manager("jmm"),
        ),
    )


def _template_to_dict(template: RecolorVariantTemplate) -> dict[str, object]:
    return {
        "template_id": template.template_id,
        "name": template.name,
        "description": template.description,
        "created_utc": template.created_utc,
        "updated_utc": template.updated_utc,
        "rules": [dataclasses.asdict(rule) for rule in template.rules],
    }


def _template_from_dict(data: Mapping[str, object]) -> RecolorVariantTemplate:
    rules = []
    for item in data.get("rules") or []:
        if isinstance(item, Mapping):
            rules.append(_rule_from_dict(item))
    return RecolorVariantTemplate(
        template_id=str(data.get("template_id") or uuid.uuid4().hex[:12]),
        name=str(data.get("name") or "Recolor Template"),
        description=str(data.get("description") or ""),
        created_utc=str(data.get("created_utc") or ""),
        updated_utc=str(data.get("updated_utc") or ""),
        rules=tuple(rules),
    )


def _rule_from_dict(data: Mapping[str, object]) -> RecolorVariantRule:
    return RecolorVariantRule(
        rule_id=str(data.get("rule_id") or uuid.uuid4().hex[:12]),
        label=str(data.get("label") or "Rule"),
        enabled=_json_bool(data.get("enabled", True), True),
        target_kind=str(data.get("target_kind") or "texture_slot"),
        slot_kind=str(data.get("slot_kind") or ""),
        filename_glob=str(data.get("filename_glob") or "*.dds"),
        parameter_name=str(data.get("parameter_name") or "*"),
        operation=str(data.get("operation") or "tint"),
        source_color=_normalize_hex_color(str(data.get("source_color") or "#808080"), "#808080"),
        target_color=_normalize_hex_color(str(data.get("target_color") or "#C85A30"), "#C85A30"),
        tolerance=max(0, min(255, int(data.get("tolerance") or 48))),
        strength=max(1, min(100, int(data.get("strength") or 100))),
        preserve_luminance=_json_bool(data.get("preserve_luminance", True), True),
    )


def _list_package_members(
    package_path: Path,
    warnings: list[str],
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[str, ...]:
    if package_path.is_dir():
        names = []
        for child in package_path.rglob("*"):
            raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
            if child.is_file():
                try:
                    names.append(child.relative_to(package_path).as_posix())
                except ValueError:
                    continue
        return tuple(sorted(names))
    if package_path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(package_path) as archive:
                members: list[str] = []
                for info in archive.infolist():
                    raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
                    if not info.is_dir():
                        members.append(info.filename.replace("\\", "/"))
                return tuple(sorted(members))
        except (OSError, zipfile.BadZipFile) as exc:
            warnings.append(f"Zip member scan failed: {exc}")
            return ()
    return ()


def _payload_members(
    package_path: Path,
    member_names: Sequence[str],
    *,
    stop_event: Optional[threading.Event] = None,
) -> dict[str, _PackageMember]:
    members: dict[str, _PackageMember] = {}
    for member_name in member_names:
        raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
        payload = normalize_mod_package_payload_path(member_name).as_posix().strip("/")
        if not payload:
            continue
        first_part = PurePosixPath(payload).parts[0].lower() if PurePosixPath(payload).parts else ""
        if first_part not in _KNOWN_PAYLOAD_ROOTS:
            continue
        source_path = package_path / Path(member_name) if package_path.is_dir() else None
        member = _PackageMember(member_path=member_name, payload_path=payload, source_path=source_path if source_path and source_path.is_file() else None)
        members.setdefault(payload.casefold(), member)
    return members


def _parse_member_dds_info(package_path: Path, member: _PackageMember):
    if member.source_path is not None:
        return parse_dds(member.source_path)
    if package_path.suffix.lower() != ".zip":
        raise ValueError("DDS metadata is only available for loose files or zip members.")
    temp_path: Optional[Path] = None
    try:
        with zipfile.ZipFile(package_path) as archive:
            header = _read_zip_member_bytes(archive, member.member_path, member.payload_path)[:148]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as handle:
            handle.write(header)
            temp_path = Path(handle.name)
        return parse_dds(temp_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _package_info_from_analysis(package_path: Path, manifest: Mapping[str, object], modinfo: Mapping[str, object]) -> ModPackageInfo:
    title = _metadata_text(manifest, "title") or _metadata_text(manifest, "name") or _metadata_text(modinfo, "name") or package_path.stem
    return ModPackageInfo(
        title=title,
        version=_metadata_text(manifest, "version") or _metadata_text(modinfo, "version") or "1.0",
        author=_metadata_text(manifest, "author") or _metadata_text(modinfo, "author"),
        description=_metadata_text(manifest, "description") or _metadata_text(modinfo, "description"),
        nexus_url=_metadata_text(manifest, "nexus_url"),
    )


def _metadata_text(metadata: Mapping[str, object], key: str) -> str:
    value = metadata.get(key)
    return str(value or "").strip() if value is not None else ""


def _classify_texture_target(
    path_value: str,
    slot_kind: str,
    *,
    sidecar_text: str = "",
    included: bool = True,
) -> tuple[str, str, bool, str]:
    if not included:
        return "unknown", "unknown", False, "Referenced texture is not included in this mod package."
    semantic = infer_texture_semantics(path_value, sidecar_texts=(sidecar_text,))
    texture_type = semantic.texture_type
    semantic_subtype = semantic.semantic_subtype
    lowered = str(path_value or "").lower()
    normalized_slot = str(slot_kind or "").strip().lower()
    if normalized_slot not in _SAFE_TEXTURE_SLOT_KINDS:
        return texture_type, semantic_subtype, False, f"{slot_kind or 'unknown'} slot is not a visible color slot."
    if lowered.endswith(_TECHNICAL_TEXTURE_SUFFIXES):
        return texture_type, semantic_subtype, False, "Technical-map suffix is locked for safe recolor variants."
    if is_technical_texture_type(texture_type) or texture_type not in _VISIBLE_TEXTURE_TYPES:
        return texture_type, semantic_subtype, False, f"{texture_type}/{semantic_subtype} is not a safe visible texture."
    return texture_type, semantic_subtype, True, ""


def _material_color_targets(
    package_path: Path,
    sidecar_paths: Sequence[str],
    *,
    stop_event: Optional[threading.Event] = None,
) -> list[RecolorVariantTarget]:
    targets: list[RecolorVariantTarget] = []
    for sidecar_path in sidecar_paths:
        raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
        normalized_path = normalize_mod_package_payload_path(sidecar_path).as_posix().strip("/")
        if not normalized_path:
            continue
        try:
            if package_path.is_dir():
                source = _source_path_for_payload(package_path, sidecar_path, normalized_path)
                if source is None:
                    continue
                text = source.read_text(encoding="utf-8-sig", errors="replace")
            elif package_path.suffix.lower() == ".zip":
                with zipfile.ZipFile(package_path) as archive:
                    text = _read_zip_member_text(archive, sidecar_path, normalized_path)
            else:
                continue
        except Exception:
            continue
        occurrence = 0
        for match in _COLOR_PARAM_RE.finditer(text):
            raise_if_cancelled(stop_event, "Recolor analysis cancelled.")
            attrs = _attrs_dict(match.group("attrs"))
            parameter_name = _first_attr(attrs, "_name", "StringItemID", "Name", "ItemID")
            raw_value = _first_attr(attrs, "Value", "_value", "value")
            if not raw_value:
                continue
            occurrence += 1
            editable = bool(_parse_hex_rgba(raw_value))
            targets.append(
                RecolorVariantTarget(
                    target_id=_target_id("material_color", normalized_path, parameter_name, occurrence),
                    target_kind="material_color",
                    game_path=normalized_path,
                    member_path=sidecar_path,
                    label=f"{PurePosixPath(normalized_path).name}:{parameter_name}",
                    parameter_name=parameter_name,
                    current_value=raw_value,
                    editable=editable,
                    locked_reason="" if editable else "Only hex MaterialParameterColor values are supported in v1.",
                )
            )
    return targets


def _matching_rule(target: RecolorVariantTarget, rules: Sequence[RecolorVariantRule]) -> Optional[RecolorVariantRule]:
    for rule in rules:
        if not rule.enabled:
            continue
        rule_kind = str(rule.target_kind or "").strip().lower()
        if rule_kind not in {"", "any", target.target_kind.lower()}:
            continue
        if target.target_kind == "texture_slot":
            rule_slot = str(rule.slot_kind or "").strip().lower()
            if rule_slot and rule_slot not in {"any", target.slot_kind.lower()}:
                continue
            pattern = str(rule.filename_glob or "*.dds").strip() or "*.dds"
            if not _path_glob_matches(target.game_path, pattern):
                continue
            return rule
        if target.target_kind == "material_color":
            pattern = str(rule.parameter_name or "*").strip() or "*"
            if not fnmatch.fnmatch(target.parameter_name.lower(), pattern.lower()):
                continue
            return rule
    return None


def _path_glob_matches(path_value: str, pattern: str) -> bool:
    lowered_path = str(path_value or "").replace("\\", "/").lower()
    lowered_name = PurePosixPath(lowered_path).name.lower()
    lowered_pattern = str(pattern or "*").replace("\\", "/").lower()
    return fnmatch.fnmatch(lowered_path, lowered_pattern) or fnmatch.fnmatch(lowered_name, lowered_pattern)


def _copy_source_payloads_to_stage(
    source_package: Path,
    payload_paths: Sequence[str],
    stage_root: Path,
    *,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> None:
    stage_root.mkdir(parents=True, exist_ok=True)
    if source_package.is_dir():
        for payload_path in payload_paths:
            raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
            source = _source_path_for_payload(source_package, payload_path, payload_path)
            if source is None:
                continue
            target = stage_root / Path(PurePosixPath(payload_path).as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            if stop_event is None:
                shutil.copy2(source, target)
            else:
                with source.open("rb") as source_handle, target.open("wb") as target_handle:
                    while chunk := source_handle.read(1024 * 1024):
                        raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
                        target_handle.write(chunk)
                shutil.copystat(source, target)
            if on_log:
                on_log(f"COPY {payload_path}")
        return
    if source_package.suffix.lower() == ".zip":
        requested = {str(path).replace("\\", "/").strip().casefold(): str(path).replace("\\", "/").strip() for path in payload_paths}
        with zipfile.ZipFile(source_package) as archive:
            seen: set[str] = set()
            for info in archive.infolist():
                raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
                if info.is_dir():
                    continue
                normalized = normalize_mod_package_payload_path(info.filename).as_posix().strip("/")
                if normalized.casefold() not in requested or normalized.casefold() in seen:
                    continue
                target = stage_root / Path(PurePosixPath(normalized).as_posix())
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source_handle, target.open("wb") as target_handle:
                    while chunk := source_handle.read(1024 * 1024):
                        raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
                        target_handle.write(chunk)
                seen.add(normalized.casefold())
                if on_log:
                    on_log(f"COPY {normalized}")


def _materialize_target_dds_for_preview(
    analysis: RecolorVariantAnalysis,
    target: RecolorVariantTarget,
    preview_root: Path,
) -> Path:
    source_package = Path(analysis.package_path).expanduser()
    normalized = normalize_mod_package_payload_path(target.game_path).as_posix().strip("/")
    member_path = target.member_path or target.game_path
    if source_package.is_dir():
        source = _source_path_for_payload(source_package, member_path, normalized)
        if source is None:
            raise FileNotFoundError(f"Recolor preview source texture was not found: {target.game_path}")
        return source
    if source_package.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_package) as archive:
            payload = _read_zip_member_bytes(archive, member_path, normalized)
        if not payload:
            raise FileNotFoundError(f"Recolor preview source texture was not found in zip: {target.game_path}")
        extracted = preview_root / "source.dds"
        extracted.write_bytes(payload)
        return extracted
    raise ValueError(f"Unsupported recolor preview source package: {source_package}")


def _texture_editor_settings_for_recolor_rule(rule: RecolorVariantRule) -> TextureEditorToolSettings:
    return TextureEditorToolSettings(
        tool="recolor",
        recolor_mode="replace_color" if rule.operation == "replace_color" else "tint",
        recolor_source_hex=rule.source_color,
        recolor_target_hex=rule.target_color,
        recolor_tolerance=max(0, min(255, int(rule.tolerance))),
        recolor_strength=max(1, min(100, int(rule.strength))),
        recolor_preserve_luminance=bool(rule.preserve_luminance),
    )


def _apply_texture_rule_to_dds(
    dds_path: Path,
    rule: RecolorVariantRule,
    *,
    texconv_path: Optional[Path],
    scratch_root: Path,
    stop_event: Optional[threading.Event],
    on_log: Optional[Callable[[str], None]],
) -> None:
    raise_if_cancelled(stop_event, "Recolor variant build cancelled.")
    scratch_root.mkdir(parents=True, exist_ok=True)
    dds_info = parse_dds(dds_path)
    source_png = ensure_dds_display_preview_png(
        texconv_path if texconv_path is not None and texconv_path.is_file() else None,
        dds_path,
        dds_info=dds_info,
        max_dimension=0,
        slot_kind="base",
        stop_event=stop_event,
    )
    with Image.open(source_png) as image:
        rgba = image.convert("RGBA")
        pixels = np.asarray(rgba, dtype=np.uint8).copy()
    edited = apply_texture_editor_recolor(pixels, _texture_editor_settings_for_recolor_rule(rule))
    edited_png = scratch_root / f"{dds_path.stem}_recolor.png"
    save_rgba_array_png(edited, edited_png)
    output_width, output_height = read_png_dimensions(edited_png)
    mip_count = max(1, int(dds_info.mip_count or max_mips_for_size(output_width, output_height)))
    native_report = encode_dds_with_directxtex(
        edited_png,
        dds_path,
        dds_format=dds_info.texconv_format,
        width=dds_info.width,
        height=dds_info.height,
        mip_count=mip_count,
        stop_event=stop_event,
    )
    if native_report and dds_path.exists() and dds_path.stat().st_size > 0:
        if on_log:
            on_log(f"RECOLOR {dds_path.name} with DirectXTex native encode")
        return
    if texconv_path is None or not texconv_path.is_file():
        raise RuntimeError("DirectXTex native DDS encode failed and no texconv fallback is configured.")
    cmd = build_texconv_command(
        texconv_path=texconv_path,
        png_path=edited_png,
        output_dir=dds_path.parent,
        fmt=dds_info.texconv_format,
        mip_count=mip_count,
        width=dds_info.width,
        height=dds_info.height,
        overwrite_existing_dds=True,
    )
    return_code, _stdout, stderr = run_process_with_cancellation(cmd, stop_event=stop_event)
    if return_code != 0:
        raise RuntimeError(stderr.strip() or f"texconv failed with exit code {return_code}")
    built = dds_path.parent / f"{edited_png.stem}.dds"
    if built != dds_path and built.is_file():
        if dds_path.exists():
            dds_path.unlink()
        built.replace(dds_path)


def _apply_material_color_rules(
    text: str,
    entries: Sequence[tuple[RecolorVariantTarget, RecolorVariantRule]],
) -> tuple[str, tuple[str, ...]]:
    requested: dict[str, RecolorVariantRule] = {target.parameter_name.lower(): rule for target, rule in entries}
    changed: list[str] = []

    def replace_match(match: re.Match[str]) -> str:
        attrs_text = match.group("attrs")
        attrs = _attrs_dict(attrs_text)
        parameter_name = _first_attr(attrs, "_name", "StringItemID", "Name", "ItemID")
        rule = requested.get(parameter_name.lower())
        if rule is None:
            return match.group(0)
        value_match = _VALUE_ATTR_RE.search(attrs_text)
        if value_match is None:
            return match.group(0)
        alpha = _parse_hex_rgba(value_match.group("value"))[3] if _parse_hex_rgba(value_match.group("value")) else ""
        new_color = _normalize_hex_color(rule.target_color, "#C85A30", alpha=alpha)
        changed.append(parameter_name)
        start, end = value_match.span("value")
        updated_attrs = attrs_text[:start] + new_color + attrs_text[end:]
        return match.group(0).replace(attrs_text, updated_attrs, 1)

    return _COLOR_PARAM_RE.sub(replace_match, text), tuple(dict.fromkeys(changed))


def _profile_package_info(
    base_info: ModPackageInfo,
    template: RecolorVariantTemplate,
    profile: RecolorVariantOutputProfile,
) -> ModPackageInfo:
    if profile.package_info is not None:
        return profile.package_info
    suffix_parts = [template.name or "Recolor"]
    if profile.package_title_suffix:
        suffix_parts.append(profile.package_title_suffix)
    title = f"{base_info.title} - {' '.join(suffix_parts)}"
    description = base_info.description or f"Recolor variant generated with template: {template.name or template.template_id}"
    return ModPackageInfo(
        title=title,
        version=base_info.version or "1.0",
        author=base_info.author,
        description=description,
        nexus_url=base_info.nexus_url,
    )


def _profile_output_root(output_root: Path, package_info: ModPackageInfo, profile: RecolorVariantOutputProfile) -> Path:
    root = resolve_mod_package_root(output_root, package_info)
    if profile.profile_id and profile.profile_id.strip().lower() not in {"", "dmm"}:
        return root.with_name(f"{root.name}_{_safe_slug(profile.profile_id)}")
    return root


def _write_jmm_mod_json(root: Path, package_info: ModPackageInfo, payload_paths: Sequence[str]) -> Path:
    target = next((path for path in payload_paths if path.lower().endswith((".pac", ".pam", ".pamlod"))), "")
    payload = {
        "name": package_info.title,
        "title": package_info.title,
        "version": package_info.version or "1.0",
        "author": package_info.author,
        "game": "Crimson Desert",
        "description": package_info.description,
        "kind": "mesh_loose_mod" if target else "dds_loose_mod",
        "category": _infer_jmm_category(target or (payload_paths[0] if payload_paths else "")),
        "target": target or (payload_paths[0] if payload_paths else ""),
        "files": list(payload_paths),
        "new_paths": [path for path in payload_paths if path.lower().endswith(".dds")],
    }
    compact = {key: value for key, value in payload.items() if value not in ("", None, [], {})}
    path = root / "mod.json"
    path.write_text(json.dumps(compact, indent=2), encoding="utf-8")
    return path


def _infer_jmm_category(path_value: str) -> str:
    lowered = str(path_value or "").replace("\\", "/").lower()
    if "/weapon/" in lowered:
        return "weapon"
    if "/armor/" in lowered:
        return "armor"
    if "/tools/" in lowered:
        return "tool"
    if lowered.startswith("ui/"):
        return "ui"
    return "replacement"


def _source_path_for_payload(source_root: Path, payload_path: str, normalized: str) -> Optional[Path]:
    candidates = (
        source_root.joinpath(*PurePosixPath(payload_path).parts),
        source_root / "files" / Path(*PurePosixPath(normalized).parts),
        source_root.joinpath(*PurePosixPath(normalized).parts),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _read_zip_member_text(archive: zipfile.ZipFile, sidecar_path: str, normalized: str) -> str:
    candidates = (sidecar_path, f"files/{normalized}", normalized)
    for candidate in candidates:
        try:
            return archive.read(candidate).decode("utf-8-sig", errors="replace")
        except KeyError:
            continue
    basename = PurePosixPath(normalized).name.lower()
    for info in archive.infolist():
        if PurePosixPath(info.filename.replace("\\", "/")).name.lower() == basename:
            return archive.read(info).decode("utf-8-sig", errors="replace")
    return ""


def _read_zip_member_bytes(archive: zipfile.ZipFile, member_path: str, normalized: str) -> bytes:
    candidates = (member_path, f"files/{normalized}", normalized)
    for candidate in candidates:
        try:
            return archive.read(candidate)
        except KeyError:
            continue
    basename = PurePosixPath(normalized).name.lower()
    for info in archive.infolist():
        if PurePosixPath(info.filename.replace("\\", "/")).name.lower() == basename:
            return archive.read(info)
    return b""


def _target_id(kind: str, path_value: str, label: str = "", occurrence: int | str = "") -> str:
    raw = "|".join(str(part or "") for part in (kind, path_value, label, occurrence))
    return _safe_slug(raw)[:96]


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value).strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "recolor_variant"


def _attrs_dict(text: str) -> dict[str, str]:
    return {match.group(1).lower(): match.group(2) for match in _ATTR_RE.finditer(str(text or ""))}


def _first_attr(attrs: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = str(attrs.get(name.lower(), "") or "").strip()
        if value:
            return value
    return ""


def _parse_hex_rgba(value: str) -> tuple[int, int, int, str] | tuple[()]:
    text = str(value or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", text):
        return ()
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), text[6:8].lower()


def _normalize_hex_color(value: str, fallback: str, *, alpha: str = "") -> str:
    text = str(value or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", text):
        text = str(fallback or "#000000").strip().lstrip("#")
    rgb = text[:6].lower()
    normalized_alpha = str(alpha or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{2}", normalized_alpha):
        return f"#{rgb}{normalized_alpha}"
    if len(text) >= 8:
        return f"#{rgb}{text[6:8].lower()}"
    return f"#{rgb}"


def _json_bool(value: object, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(default)
