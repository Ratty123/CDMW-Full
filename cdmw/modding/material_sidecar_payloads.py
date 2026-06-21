"""Material sidecar payload planning for static texture replacement."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from .material_profiles import CDMaterialRuntimeProfile
from .material_sidecar_patching import (
    _escape_xml_attr,
    _find_sidecar_material_wrapper,
    _find_sidecar_material_wrapper_by_texture_paths,
    _find_sidecar_material_wrapper_exact,
    _material_tokens,
    _normalize_sidecar_material_name,
    _normalize_texture_path,
    _sidecar_material_names_match,
    _sidecar_parameter_name,
)


_VISIBLE_GEM_SENSITIVE_WRAPPER_TOKENS = {"acc", "accessory", "blade", "flag", "guard", "handle", "hilt"}


def _replace_source_driven_texture_parameter(*args: object, **kwargs: object) -> tuple[str, bool]:
    from .material_source_driven import _replace_source_driven_texture_parameter as impl

    return impl(*args, **kwargs)


def _visible_gem_sensitive_wrappers_touched(sidecar_text: str, changed_wrapper_names: Sequence[str]) -> tuple[str, ...]:
    if not sidecar_text or not changed_wrapper_names:
        return ()
    from .material_source_driven import _sanitize_texture_component

    compact_sidecar = _sanitize_texture_component(sidecar_text)
    has_visible_gem_evidence = (
        "gem" in compact_sidecar
        or "jewel" in compact_sidecar
        or "crystal" in compact_sidecar
        or "emissive" in compact_sidecar
        or "_emissivecolor" in compact_sidecar
        or "_emissiveintensity" in compact_sidecar
    )
    if not has_visible_gem_evidence:
        return ()
    risky: list[str] = []
    seen: set[str] = set()
    for wrapper_name in tuple(changed_wrapper_names or ()):
        name = str(wrapper_name or "").strip()
        if not name:
            continue
        tokens = _material_tokens(name)
        if not (tokens & _VISIBLE_GEM_SENSITIVE_WRAPPER_TOKENS):
            continue
        key = _normalize_sidecar_material_name(name)
        if key in seen:
            continue
        seen.add(key)
        risky.append(name)
    return tuple(risky)




def _build_base_color_injection_for_target(
    *,
    target_name: str,
    texture_set: ReplacementTextureSet,
    original_texture_refs: Sequence[object],
    material_refs: Sequence[object],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    texture_output_size_mode: str,
) -> tuple[list[TextureReplacementPayload], list[SidecarTextureParameterInjection]]:
    from .material_replacer import (
        SidecarTextureParameterInjection,
        TextureReplacementPayload,
        TextureSlotMapping,
        _base_color_template_reference,
        _build_texture_payload,
        _infer_base_color_path_for_material,
        _reference_target_parent,
        _reference_target_path,
    )

    base_slot = texture_set.slots.get("base")
    if base_slot is None:
        return [], []
    template_reference = _base_color_template_reference(material_refs) or _base_color_template_reference(original_texture_refs)
    if template_reference is None or getattr(template_reference, "resolved_entry", None) is None:
        report.warnings.append(
            f"{target_name}: cannot inject _overlayColorTexture because no compatible base texture template was found."
        )
        return [], []
    output_texture_path = _infer_base_color_path_for_material(
        original_texture_refs,
        target_name,
        fallback_parent=_reference_target_parent(template_reference),
    )
    if not output_texture_path:
        report.warnings.append(f"{target_name}: could not infer output path for injected base color texture.")
        return [], []
    try:
        payload_data = _build_texture_payload(
            base_slot,
            target_entry=getattr(template_reference, "resolved_entry", None),
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
        )
    except Exception as exc:
        report.errors.append(f"Failed to build injected base-color texture for {target_name}: {exc}")
        return [], []
    payload = TextureReplacementPayload(
        target_path=output_texture_path,
        payload_data=payload_data,
        kind="texture_generated",
        source_path=base_slot.source_path,
        note=f"PAC-driven injected _overlayColorTexture for {target_name}",
    )
    report.slot_mappings.append(
        TextureSlotMapping(
            target_material_name=target_name,
            target_texture_path="(injected _overlayColorTexture)",
            slot_kind="base",
            source_material_name=base_slot.material_name,
            source_path=base_slot.source_path,
            output_texture_path=output_texture_path,
            normal_space=base_slot.normal_space,
        )
    )
    report.warnings.append(
        f"PAC XML rebuild: added _overlayColorTexture for {target_name} using {base_slot.source_path.name}."
    )
    return [payload], [
        SidecarTextureParameterInjection(
            target_material_name=target_name,
            parameter_name="_overlayColorTexture",
            texture_path=output_texture_path,
            anchor_texture_paths=tuple(
                _reference_target_path(reference)
                for reference in material_refs
                if _reference_target_path(reference)
            ),
        )
    ]


def _sidecar_keep_rules_from_slot_mappings(
    slot_mappings: Sequence[TextureSlotMapping],
    references_by_target_path: Mapping[str, object],
) -> list[tuple[str, str]]:
    keep_rules: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for mapping in slot_mappings:
        output_path = _normalize_texture_path(mapping.output_texture_path)
        if not output_path:
            continue
        parameter_name = ""
        target_path = str(mapping.target_texture_path or "").replace("\\", "/").strip()
        if target_path.startswith("("):
            parameter_match = re.search(r"source-driven\s+([^)\s]+)", target_path, flags=re.IGNORECASE)
            parameter_name = parameter_match.group(1) if parameter_match is not None else "_overlayColorTexture"
        else:
            reference = references_by_target_path.get(_normalize_texture_path(target_path))
            parameter_name = str(getattr(reference, "sidecar_parameter_name", "") or "").strip()
            if (
                str(mapping.slot_kind or "").strip().lower() == "base"
                and parameter_name.lower() == "_colorblendingmasktexture"
            ):
                parameter_name = "_overlayColorTexture"
        if not _should_keep_rebuilt_sidecar_texture_parameter(parameter_name, mapping.slot_kind):
            continue
        key = (parameter_name.strip().lower(), output_path)
        if key in seen:
            continue
        seen.add(key)
        keep_rules.append(key)
    return keep_rules


def _should_keep_rebuilt_sidecar_texture_parameter(parameter_name: str, slot_kind: str) -> bool:
    normalized_parameter = str(parameter_name or "").strip().lower()
    normalized_slot = str(slot_kind or "").strip().lower()
    if normalized_parameter in {
        "_overlaycolortexture",
        "_basecolortexture",
        "_diffusetexture",
        "_albedotexture",
        "_normaltexture",
        "_heighttexture",
        "_emissiveintensitytexture",
        "_emissivetexture",
        "_emissiveprogresstexture",
    }:
        return True
    if normalized_slot in {"material", "material_mask", "detail_mask"} and normalized_parameter in {
        "_colorblendingmasktexture",
        "_detailmasktexture",
        "_overlaycolortexture",
    }:
        return True
    return False


def _build_patched_sidecar_payloads(
    *,
    original_sidecars: Sequence[tuple[object, str]],
    sidecar_replacements_by_path: Mapping[str, str],
    sidecar_parameter_injections: Sequence[SidecarTextureParameterInjection],
    sidecar_parameter_renames: Sequence[SidecarTextureParameterRename] = (),
    material_wrapper_clones: Sequence[SidecarMaterialWrapperClone] = (),
    texture_parameter_keep_rules: Sequence[tuple[str, str]] = (),
    prune_unmapped_texture_parameters: bool = False,
    prune_material_names: Sequence[str] = (),
    neutralize_inherited_material_layers: bool = False,
    complete_external_material_reset: bool = False,
    neutralize_material_names: Sequence[str] = (),
    report: TextureReplacementReport,
    include_unchanged_clone: bool = False,
) -> list[TextureReplacementPayload]:
    from .material_replacer import SidecarPatchPlan, TextureReplacementPayload, patch_material_sidecar_text

    if not original_sidecars or not (
        include_unchanged_clone
        or sidecar_replacements_by_path
        or sidecar_parameter_injections
        or sidecar_parameter_renames
        or material_wrapper_clones
        or prune_unmapped_texture_parameters
        or neutralize_inherited_material_layers
    ):
        return []
    sidecar_payloads: list[TextureReplacementPayload] = []
    for sidecar_entry, sidecar_text in original_sidecars:
        sidecar_path = str(getattr(sidecar_entry, "path", "") or "").strip()
        patched_text, sidecar_report = patch_material_sidecar_text(
            sidecar_text,
            SidecarPatchPlan(
                sidecar_path=sidecar_path,
                texture_path_replacements=dict(sidecar_replacements_by_path),
                texture_parameter_injections=list(sidecar_parameter_injections),
                texture_parameter_renames=list(sidecar_parameter_renames),
                material_wrapper_clones=list(material_wrapper_clones),
                texture_parameter_keep_rules=list(texture_parameter_keep_rules),
                prune_unmapped_texture_parameters=bool(prune_unmapped_texture_parameters),
                prune_material_names=list(prune_material_names),
                neutralize_inherited_material_layers=bool(neutralize_inherited_material_layers),
                complete_external_material_reset=bool(complete_external_material_reset),
                neutralize_material_names=list(neutralize_material_names),
            ),
        )
        report.sidecar_reports.append(sidecar_report)
        for warning in sidecar_report.warnings:
            if (
                ("unmapped original texture parameter" in warning or "Neutralized inherited material layers" in warning)
                and warning not in report.warnings
            ):
                report.warnings.append(warning)
        if sidecar_report.replaced_count <= 0 and prune_unmapped_texture_parameters:
            report.warnings.append(
                f"Skipped unchanged rebuilt sidecar {PurePosixPath(sidecar_path).name}; no texture parameters were patched or pruned."
            )
            continue
        if sidecar_report.replaced_count <= 0 and not include_unchanged_clone:
            report.warnings.append(
                f"Patched sidecar {PurePosixPath(sidecar_path).name} did not apply any texture path or parameter changes."
            )
            continue
        payload_note = (
            "PAC-driven material sidecar cloned from original archive entry."
            if sidecar_report.replaced_count <= 0
            else "PAC-driven material sidecar patched from original archive entry."
        )
        sidecar_payloads.append(
            TextureReplacementPayload(
                target_path=sidecar_path,
                payload_data=patched_text.encode("utf-8"),
                kind="sidecar_generated",
                source_path=Path(PurePosixPath(sidecar_path).name),
                note=payload_note,
            )
        )
    return sidecar_payloads


def _build_removed_target_prune_sidecar_payloads(
    *,
    original_sidecars: Sequence[tuple[object, str]],
    removed_target_material_names: Sequence[str],
    keep_rules: Sequence[tuple[str, str]],
    report: TextureReplacementReport,
) -> list[TextureReplacementPayload]:
    removed_names = [
        str(name or "").strip()
        for name in tuple(removed_target_material_names or ())
        if str(name or "").strip()
    ]
    if not original_sidecars or not removed_names:
        return []
    payloads = _build_patched_sidecar_payloads(
        original_sidecars=original_sidecars,
        sidecar_replacements_by_path={},
        sidecar_parameter_injections=(),
        texture_parameter_keep_rules=keep_rules,
        prune_unmapped_texture_parameters=True,
        prune_material_names=removed_names,
        report=report,
    )
    if payloads:
        report.warnings.append(
            "Removed original target texture parameters from patched material sidecar for: "
            + ", ".join(removed_names[:8])
            + ("..." if len(removed_names) > 8 else "")
        )
    return payloads


def _overlay_original_sidecars_with_payloads(
    original_sidecars: Sequence[tuple[object, str]],
    generated_payloads: Sequence[TextureReplacementPayload],
) -> tuple[tuple[object, str], ...]:
    generated_sidecar_text_by_path: dict[str, str] = {}
    for payload in tuple(generated_payloads or ()):
        if str(getattr(payload, "kind", "") or "") != "sidecar_generated":
            continue
        target_path = _normalize_texture_path(getattr(payload, "target_path", ""))
        if not target_path or not getattr(payload, "payload_data", b""):
            continue
        try:
            generated_sidecar_text_by_path[target_path] = bytes(payload.payload_data).decode("utf-8", errors="ignore")
        except Exception:
            continue
    if not generated_sidecar_text_by_path:
        return tuple(original_sidecars or ())
    overlaid: list[tuple[object, str]] = []
    for sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        sidecar_path = _normalize_texture_path(str(getattr(sidecar_entry, "path", "") or ""))
        overlaid.append((sidecar_entry, generated_sidecar_text_by_path.get(sidecar_path, sidecar_text)))
    return tuple(overlaid)


def _replace_sidecar_payloads(
    generated_payloads: Sequence[TextureReplacementPayload],
    replacement_sidecar_payloads: Sequence[TextureReplacementPayload],
) -> list[TextureReplacementPayload]:
    replacement_targets = {
        _normalize_texture_path(getattr(payload, "target_path", ""))
        for payload in tuple(replacement_sidecar_payloads or ())
        if _normalize_texture_path(getattr(payload, "target_path", ""))
    }
    if not replacement_targets:
        return list(generated_payloads or ())
    return [
        payload
        for payload in tuple(generated_payloads or ())
        if not (
            str(getattr(payload, "kind", "") or "") == "sidecar_generated"
            and _normalize_texture_path(getattr(payload, "target_path", "")) in replacement_targets
        )
    ] + list(replacement_sidecar_payloads or ())


def _build_donor_material_texture_payloads(
    donor_material_plans: Sequence[object],
    *,
    existing_payloads: Sequence[TextureReplacementPayload] = (),
    report: TextureReplacementReport,
) -> list[TextureReplacementPayload]:
    from .material_replacer import TextureReplacementPayload

    payloads: list[TextureReplacementPayload] = []
    emitted = {
        _normalize_texture_path(getattr(payload, "target_path", ""))
        for payload in tuple(existing_payloads or ())
        if _normalize_texture_path(getattr(payload, "target_path", ""))
    }
    missing_count = 0
    for plan in tuple(donor_material_plans or ()):
        if not bool(getattr(plan, "enabled", True)):
            continue
        for binding in tuple(getattr(plan, "texture_bindings", ()) or ()):
            target_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
            source_path_text = str(getattr(binding, "source_path", "") or "").strip()
            if not target_path or not source_path_text:
                continue
            normalized_target = _normalize_texture_path(target_path)
            if not normalized_target or normalized_target in emitted:
                continue
            try:
                source_path = Path(source_path_text).expanduser()
            except OSError:
                missing_count += 1
                continue
            if not source_path.is_file():
                missing_count += 1
                continue
            try:
                payload_data = source_path.read_bytes()
            except OSError as exc:
                report.warnings.append(f"Donor material texture could not be read: {source_path.name}: {exc}")
                continue
            payloads.append(
                TextureReplacementPayload(
                    target_path=target_path,
                    payload_data=payload_data,
                    kind="texture_donor_material",
                    source_path=source_path,
                    note="Donor material recipe texture included for patched sidecar.",
                )
            )
            emitted.add(normalized_target)
    if payloads:
        report.warnings.append(f"Included {len(payloads):,} donor material recipe texture file(s).")
    if missing_count:
        report.warnings.append(
            f"{missing_count:,} donor material texture reference(s) had no readable local DDS source; "
            "the patched sidecar may rely on files already present in the target archive."
        )
    return payloads


def _sidecar_kind_from_path(path_value: object) -> str:
    normalized = str(path_value or "").replace("\\", "/").strip().lower()
    if normalized.endswith(".pac_xml") or normalized.endswith(".pac.xml"):
        return "pac_xml"
    if normalized.endswith(".pami"):
        return "pami"
    if normalized.endswith(".pam_xml") or normalized.endswith(".pam.xml"):
        return "pam_xml"
    if normalized.endswith(".pamlod_xml") or normalized.endswith(".pamlod.xml"):
        return "pamlod_xml"
    if normalized.endswith(".xml"):
        return "xml"
    return ""


def _donor_plan_texture_bindings(plan: object) -> tuple[tuple[str, str, str, str], ...]:
    from .material_replacer import _infer_slot_kind

    rows: list[tuple[str, str, str, str]] = []
    for binding in tuple(getattr(plan, "texture_bindings", ()) or ()):
        parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
        texture_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
        if not texture_path:
            continue
        slot_kind = str(getattr(binding, "slot_kind", "") or "").strip().lower()
        semantic_subtype = str(getattr(binding, "semantic_subtype", "") or "").strip().lower()
        if not slot_kind:
            slot_kind = _infer_slot_kind(parameter_name, texture_path)
        rows.append((parameter_name, texture_path, slot_kind, semantic_subtype))
    return tuple(rows)


def _donor_plan_anchor_texture_paths(plan: object) -> tuple[str, ...]:
    paths: list[str] = []
    for raw_path in tuple(getattr(plan, "donor_anchor_texture_paths", ()) or ()):
        path_text = str(raw_path or "").replace("\\", "/").strip()
        if path_text and path_text not in paths:
            paths.append(path_text)
    for _parameter_name, texture_path, _slot_kind, _semantic_subtype in _donor_plan_texture_bindings(plan):
        if texture_path and texture_path not in paths:
            paths.append(texture_path)
    return tuple(paths)


def _donor_binding_is_emissive(parameter_name: str, texture_path: str, semantic_subtype: str = "") -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", f"{parameter_name} {texture_path} {semantic_subtype}".lower())
    return any(token in compact for token in ("emissive", "glow", "illum", "emit"))


def _donor_parameter_candidates(parameter_name: str, slot_kind: str, texture_path: str, semantic_subtype: str = "") -> tuple[str, ...]:
    candidates: list[str] = []

    def add(value: str) -> None:
        key = str(value or "").strip()
        if key and key.lower() not in {candidate.lower() for candidate in candidates}:
            candidates.append(key)

    add(parameter_name)
    normalized_slot = str(slot_kind or "").strip().lower()
    if _donor_binding_is_emissive(parameter_name, texture_path, semantic_subtype):
        for name in ("_emissiveTexture", "_emissiveIntensityTexture", "_emissiveProgressTexture"):
            add(name)
        return tuple(candidates)
    if normalized_slot == "base":
        for name in ("_overlayColorTexture", "_baseColorTexture", "_diffuseTexture", "_albedoTexture"):
            add(name)
    elif normalized_slot == "normal":
        add("_normalTexture")
    elif normalized_slot == "height":
        add("_heightTexture")
    elif normalized_slot in {"material", "material_mask"}:
        for name in ("_colorBlendingMaskTexture", "_detailMaskTexture"):
            add(name)
    elif normalized_slot == "detail_mask":
        add("_detailMaskTexture")
    return tuple(candidates)


def _patch_donor_texture_bindings_into_wrapper(
    wrapper_text: str,
    plan: object,
) -> tuple[str, bool, set[str]]:
    patched = wrapper_text
    changed = False
    used_paths: set[str] = set()
    for parameter_name, texture_path, slot_kind, semantic_subtype in _donor_plan_texture_bindings(plan):
        exact_candidates = (parameter_name,) if parameter_name else ()
        did_change = False
        if exact_candidates:
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                exact_candidates,
                texture_path,
                allow_unclassified_parameter=True,
            )
        if not did_change:
            preferred_existing_roles: tuple[str, ...] = ()
            if not _donor_binding_is_emissive(parameter_name, texture_path, semantic_subtype) and slot_kind:
                preferred_existing_roles = (slot_kind,)
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                _donor_parameter_candidates(parameter_name, slot_kind, texture_path, semantic_subtype),
                texture_path,
                preferred_existing_roles=preferred_existing_roles,
                allow_unclassified_parameter=True,
            )
        if did_change:
            changed = True
            used_paths.add(texture_path)
    return patched, changed, used_paths


def _texture_parameter_paths_by_name(
    wrapper_text: str,
    parameter_names: Sequence[str],
) -> dict[str, str]:
    wanted = {str(name or "").strip().lower() for name in tuple(parameter_names or ()) if str(name or "").strip()}
    if not wanted:
        return {}
    paths: dict[str, str] = {}
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in texture_pattern.finditer(str(wrapper_text or "")):
        block = match.group(0)
        parameter_name = _sidecar_parameter_name(block).strip().lower()
        if parameter_name not in wanted or parameter_name in paths:
            continue
        path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
        texture_path = str(path_match.group(1) if path_match else "").replace("\\", "/").strip()
        if texture_path:
            paths[parameter_name] = texture_path
    return paths


def _restore_texture_parameter_paths(
    wrapper_text: str,
    texture_paths_by_parameter: Mapping[str, str],
) -> tuple[str, int]:
    patched = wrapper_text
    changed_count = 0
    for parameter_name, texture_path in texture_paths_by_parameter.items():
        patched, changed = _replace_source_driven_texture_parameter(
            patched,
            (parameter_name,),
            texture_path,
            allow_unclassified_parameter=True,
        )
        if changed:
            changed_count += 1
    return patched, changed_count


def _donor_texture_patch_covers_selected_bindings(plan: object, used_paths: set[str]) -> bool:
    required_paths = {
        _normalize_texture_path(texture_path)
        for _parameter_name, texture_path, _slot_kind, _semantic_subtype in _donor_plan_texture_bindings(plan)
        if _normalize_texture_path(texture_path)
    }
    if not required_paths:
        return False
    normalized_used_paths = {_normalize_texture_path(path) for path in used_paths if _normalize_texture_path(path)}
    return required_paths <= normalized_used_paths


def _wrapper_open_close(wrapper_text: str) -> tuple[Optional[re.Match[str]], Optional[re.Match[str]]]:
    open_match = re.match(r"\s*<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>", wrapper_text, flags=re.IGNORECASE | re.DOTALL)
    if open_match is None:
        return None, None
    close_matches = list(
        re.finditer(rf"</{re.escape(open_match.group('tag'))}>\s*$", wrapper_text, flags=re.IGNORECASE | re.DOTALL)
    )
    return open_match, close_matches[-1] if close_matches else None


def _retarget_wrapper_submesh_attrs(wrapper_text: str, target_name: str) -> str:
    escaped_target = _escape_xml_attr(target_name)
    patched = wrapper_text
    for attr in ("_subMeshName", "subMeshName", "SubMeshName", "PrimitiveName", "primitiveName", "MaterialName", "materialName"):
        patched = re.sub(
            rf'((?<![A-Za-z0-9_:.-]){attr}=")[^"]*(")',
            lambda match: f"{match.group(1)}{escaped_target}{match.group(2)}",
            patched,
            flags=re.IGNORECASE,
        )
    return patched


def _material_wrapper_clones_for_output_draw_sections(
    output_draw_sections: Sequence[StaticOutputDrawSection],
) -> tuple[SidecarMaterialWrapperClone, ...]:
    from .material_replacer import SidecarMaterialWrapperClone

    clones: list[SidecarMaterialWrapperClone] = []
    seen: set[str] = set()
    for section in tuple(output_draw_sections or ()):
        if not bool(getattr(section, "is_cloned_section", False)):
            continue
        target_name = _source_owned_material_name_for_output_section(section)
        donor_name = str(getattr(section, "donor_material_name", "") or "").strip()
        if not target_name or not donor_name:
            continue
        target_key = _normalize_sidecar_material_name(target_name)
        if not target_key or target_key in seen:
            continue
        seen.add(target_key)
        clones.append(SidecarMaterialWrapperClone(target_material_name=target_name, donor_material_name=donor_name))
    return tuple(clones)


def _source_owned_keep_material_names_for_output_draw_sections(
    output_draw_sections: Sequence[StaticOutputDrawSection],
) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for section in tuple(output_draw_sections or ()):
        target_name = _source_owned_material_name_for_output_section(section)
        key = _normalize_sidecar_material_name(target_name)
        if not target_name or not key or key in seen:
            continue
        names.append(target_name)
        seen.add(key)
    return tuple(names)


def _source_owned_material_name_for_output_section(section: StaticOutputDrawSection) -> str:
    from .material_replacer import is_static_replacement_helper_material_name

    target_name = str(getattr(section, "target_submesh_name", "") or "").strip()
    if not target_name or not is_static_replacement_helper_material_name(target_name):
        return target_name
    for attr_name in ("runtime_slot_name", "runtime_material_name", "donor_material_name"):
        candidate = str(getattr(section, attr_name, "") or "").strip()
        if candidate and not is_static_replacement_helper_material_name(candidate):
            return candidate
    return target_name


def _profile_suppresses_runtime_placeholder_material_bindings(
    material_profile: Optional[CDMaterialRuntimeProfile],
) -> bool:
    return bool(getattr(material_profile, "suppress_runtime_placeholder_material_bindings", False))


def _source_owned_active_material_names_for_output_draw_sections(
    output_draw_sections: Sequence[StaticOutputDrawSection],
    *,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    skip_placeholders = _profile_suppresses_runtime_placeholder_material_bindings(material_profile)
    for section in tuple(output_draw_sections or ()):
        if skip_placeholders and not tuple(getattr(section, "source_submesh_indices", ()) or ()):
            continue
        target_name = _source_owned_material_name_for_output_section(section)
        key = _normalize_sidecar_material_name(target_name)
        if not target_name or not key or key in seen:
            continue
        names.append(target_name)
        seen.add(key)
    return tuple(names)


def _apply_sidecar_material_wrapper_clones(
    sidecar_text: str,
    clones: Sequence[SidecarMaterialWrapperClone],
    report: SidecarPatchReport,
) -> str:
    patched = str(sidecar_text or "")
    next_item_id = _next_sidecar_material_wrapper_item_id(patched)
    cloned_names: list[str] = []
    for clone in tuple(clones or ()):
        target_name = str(clone.target_material_name or "").strip()
        donor_name = str(clone.donor_material_name or "").strip()
        if not target_name or not donor_name:
            continue
        if _find_sidecar_material_wrapper_exact(patched, target_name) is not None:
            report.unchanged_count += 1
            continue
        donor_match = _find_sidecar_material_wrapper_exact(patched, donor_name)
        if donor_match is None:
            donor_match = _find_sidecar_material_wrapper(patched, donor_name)
        if donor_match is None:
            report.warnings.append(
                f"Could not clone material wrapper for source-owned section {target_name}; donor wrapper {donor_name} was not found."
            )
            continue
        cloned_wrapper = _retarget_wrapper_submesh_attrs(donor_match.group(0), target_name)
        cloned_wrapper = _retarget_wrapper_item_id(cloned_wrapper, next_item_id)
        next_item_id += 1
        patched = _insert_sidecar_material_wrapper_clone_after_donor(
            patched,
            donor_match,
            cloned_wrapper,
        )
        cloned_names.append(target_name)
        report.replaced_count += 1
    if cloned_names:
        report.warnings.append(
            "PAC XML wrapper rebuild: cloned source-owned material wrapper(s) in-place: "
            + ", ".join(cloned_names[:8])
            + (" ..." if len(cloned_names) > 8 else "")
        )
    return patched


def _next_sidecar_material_wrapper_item_id(sidecar_text: str) -> int:
    max_item_id: Optional[int] = None
    wrapper_pattern = re.compile(
        r"<[A-Za-z0-9_:.-]*MaterialWrapper\b[^>]*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in wrapper_pattern.finditer(str(sidecar_text or "")):
        item_match = re.search(r'\bItemID="(\d+)"', match.group(0), flags=re.IGNORECASE)
        if item_match is None:
            continue
        try:
            value = int(item_match.group(1))
        except ValueError:
            continue
        max_item_id = value if max_item_id is None else max(max_item_id, value)
    if max_item_id is None:
        return 1
    return max_item_id + 1


def _retarget_wrapper_item_id(wrapper_text: str, item_id: int) -> str:
    item_id_text = str(int(item_id))

    def replace_open(match: re.Match[str]) -> str:
        open_tag = match.group(0)
        if re.search(r'\bItemID="[^"]*"', open_tag, flags=re.IGNORECASE):
            return re.sub(r'\bItemID="[^"]*"', f'ItemID="{item_id_text}"', open_tag, count=1, flags=re.IGNORECASE)
        return open_tag[:-1] + f' ItemID="{item_id_text}">'

    return re.sub(
        r"<[A-Za-z0-9_:.-]*MaterialWrapper\b[^>]*>",
        replace_open,
        str(wrapper_text or ""),
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _insert_sidecar_material_wrapper_clone_after_donor(
    sidecar_text: str,
    donor_match: re.Match[str],
    wrapper_text: str,
) -> str:
    original = str(sidecar_text or "")
    donor_text = donor_match.group(0)
    indent_match = re.match(r"([ \t]*)<", donor_text)
    indent = indent_match.group(1) if indent_match else ""
    stripped_wrapper = str(wrapper_text or "").strip()
    cloned_lines = stripped_wrapper.splitlines() or [stripped_wrapper]
    reindented = "\n".join(
        (indent + line.lstrip()) if line.strip() else line
        for line in cloned_lines
    )
    insertion = "\n" + reindented
    return original[: donor_match.end()] + insertion + original[donor_match.end() :]


def _graft_donor_wrapper_payload(target_wrapper_text: str, donor_wrapper_text: str, target_name: str) -> tuple[str, bool]:
    target_open, target_close = _wrapper_open_close(target_wrapper_text)
    donor_open, donor_close = _wrapper_open_close(donor_wrapper_text)
    if target_open is None or target_close is None or donor_open is None or donor_close is None:
        return target_wrapper_text, False
    donor_inner = donor_wrapper_text[donor_open.end() : donor_close.start()]
    patched = (
        target_wrapper_text[: target_open.start()]
        + target_open.group(0)
        + donor_inner
        + target_close.group(0)
        + target_wrapper_text[target_close.end() :]
    )
    patched = _retarget_wrapper_submesh_attrs(patched, target_name)
    return patched, patched != target_wrapper_text


def _target_wrapper_for_donor_plan(sidecar_text: str, plan: object) -> Optional[re.Match[str]]:
    target_name = str(getattr(plan, "target_material_name", "") or "").strip()
    if target_name:
        wrapper_match = _find_sidecar_material_wrapper(sidecar_text, target_name)
        if wrapper_match is not None:
            return wrapper_match
    return _find_sidecar_material_wrapper_by_texture_paths(
        sidecar_text,
        tuple(getattr(plan, "target_anchor_texture_paths", ()) or ()),
    )


def _donor_wrapper_for_plan(plan: object) -> Optional[re.Match[str]]:
    donor_text = str(getattr(plan, "donor_sidecar_text", "") or "")
    if not donor_text.strip():
        return None
    for candidate in (
        str(getattr(plan, "donor_submesh_name", "") or "").strip(),
        str(getattr(plan, "donor_material_name", "") or "").strip(),
    ):
        if not candidate:
            continue
        wrapper_match = _find_sidecar_material_wrapper(donor_text, candidate)
        if wrapper_match is not None:
            return wrapper_match
    return _find_sidecar_material_wrapper_by_texture_paths(donor_text, _donor_plan_anchor_texture_paths(plan))


def _apply_donor_material_plan_to_sidecar(
    sidecar_text: str,
    *,
    sidecar_path: str,
    plan: object,
    report: TextureReplacementReport,
) -> tuple[str, bool, bool]:
    from .material_source_driven import _source_driven_wrapper_name

    wrapper_match = _target_wrapper_for_donor_plan(sidecar_text, plan)
    if wrapper_match is None:
        return sidecar_text, False, False
    target_name = str(getattr(plan, "target_material_name", "") or "").strip()
    patch_mode = str(getattr(plan, "patch_mode", "") or "material_behavior").strip().lower()
    target_kind = _sidecar_kind_from_path(sidecar_path)
    donor_kind = str(getattr(plan, "donor_sidecar_kind", "") or "").strip().lower()
    if not donor_kind:
        donor_kind = _sidecar_kind_from_path(getattr(plan, "donor_sidecar_path", ""))

    if patch_mode in {
        "authoritative_recipe",
        "donor_authoritative_recipe",
        "authoritative_material_recipe",
        "full_recipe",
        "full_donor_recipe",
    }:
        if target_kind != "pac_xml" or donor_kind != "pac_xml":
            report.warnings.append(
                f"Authoritative donor material recipe for {target_name or 'target wrapper'} needs matching .pac_xml wrappers "
                f"({donor_kind or 'unknown'} -> {target_kind or 'unknown'})."
            )
            return sidecar_text, False, True
        donor_wrapper_match = _donor_wrapper_for_plan(plan)
        if donor_wrapper_match is None:
            report.warnings.append(
                f"Authoritative donor material recipe could not find donor wrapper for {target_name or 'target wrapper'}."
            )
            return sidecar_text, False, True
        new_wrapper, grafted = _graft_donor_wrapper_payload(
            wrapper_match.group(0),
            donor_wrapper_match.group(0),
            target_name or _source_driven_wrapper_name(wrapper_match.group(0)),
        )
        if grafted:
            patched = sidecar_text[: wrapper_match.start()] + new_wrapper + sidecar_text[wrapper_match.end() :]
            report.warnings.append(
                f"Authoritative donor material recipe grafted: "
                f"{getattr(plan, 'donor_material_name', '') or getattr(plan, 'donor_submesh_name', '')} -> "
                f"{target_name or 'target wrapper'}; donor texture/shader parameters replaced inherited target material bindings."
            )
            return patched, True, True
        report.warnings.append(
            f"Authoritative donor material recipe graft made no changes for {target_name or 'target wrapper'}."
        )
        return sidecar_text, False, True

    if patch_mode in {"material_profile", "donor_material_profile", "profile", "profile_graft"}:
        if target_kind != "pac_xml" or donor_kind != "pac_xml":
            report.warnings.append(
                f"Donor material profile for {target_name or 'target wrapper'} needs matching .pac_xml wrappers "
                f"({donor_kind or 'unknown'} -> {target_kind or 'unknown'})."
            )
            return sidecar_text, False, True
        donor_wrapper_match = _donor_wrapper_for_plan(plan)
        if donor_wrapper_match is None:
            report.warnings.append(f"Donor material profile could not find donor wrapper for {target_name or 'target wrapper'}.")
            return sidecar_text, False, True
        preserved_paths = _texture_parameter_paths_by_name(
            wrapper_match.group(0),
            (
                "_overlayColorTexture",
                "_baseColorTexture",
                "_diffuseTexture",
                "_albedoTexture",
                "_normalTexture",
            ),
        )
        new_wrapper, grafted = _graft_donor_wrapper_payload(
            wrapper_match.group(0),
            donor_wrapper_match.group(0),
            target_name or _source_driven_wrapper_name(wrapper_match.group(0)),
        )
        if grafted and preserved_paths:
            new_wrapper, restored_count = _restore_texture_parameter_paths(new_wrapper, preserved_paths)
        else:
            restored_count = 0
        if grafted:
            patched = sidecar_text[: wrapper_match.start()] + new_wrapper + sidecar_text[wrapper_match.end() :]
            report.warnings.append(
                f"Donor material profile grafted: "
                f"{getattr(plan, 'donor_material_name', '') or getattr(plan, 'donor_submesh_name', '')} -> "
                f"{target_name or 'target wrapper'}; preserved {restored_count:,} target base/normal texture binding(s)."
            )
            return patched, True, True
        report.warnings.append(f"Donor material profile graft made no changes for {target_name or 'target wrapper'}.")
        return sidecar_text, False, True

    if patch_mode in {"material_behavior", "donor_material_behavior", "graft", "wrapper_graft"}:
        if target_kind == "pac_xml" and donor_kind == "pac_xml":
            texture_patched_wrapper, texture_changed, used_paths = _patch_donor_texture_bindings_into_wrapper(wrapper_match.group(0), plan)
            if texture_changed and _donor_texture_patch_covers_selected_bindings(plan, used_paths):
                patched = sidecar_text[: wrapper_match.start()] + texture_patched_wrapper + sidecar_text[wrapper_match.end() :]
                report.warnings.append(
                    f"Donor material behavior used target-compatible texture parameters: "
                    f"{getattr(plan, 'donor_material_name', '') or getattr(plan, 'donor_submesh_name', '')} -> {target_name or 'target wrapper'}."
                )
                return patched, True, True
            donor_wrapper_match = _donor_wrapper_for_plan(plan)
            if donor_wrapper_match is not None:
                new_wrapper, grafted = _graft_donor_wrapper_payload(
                    wrapper_match.group(0),
                    donor_wrapper_match.group(0),
                    target_name or _source_driven_wrapper_name(wrapper_match.group(0)),
                )
                if grafted:
                    patched = sidecar_text[: wrapper_match.start()] + new_wrapper + sidecar_text[wrapper_match.end() :]
                    report.warnings.append(
                        f"Donor material behavior grafted: {getattr(plan, 'donor_material_name', '') or getattr(plan, 'donor_submesh_name', '')} -> {target_name or 'target wrapper'}."
                    )
                    return patched, True, True
                report.warnings.append(f"Donor material behavior graft made no changes for {target_name or 'target wrapper'}.")
                return sidecar_text, False, True
            report.warnings.append(f"Donor material behavior could not find donor wrapper for {target_name or 'target wrapper'}.")
            return sidecar_text, False, True
        report.warnings.append(
            f"Donor material behavior for {target_name or 'target wrapper'} needs matching .pac_xml wrappers; "
            f"falling back to donor texture binding ({donor_kind or 'unknown'} -> {target_kind or 'unknown'})."
        )

    new_wrapper, changed, _used_paths = _patch_donor_texture_bindings_into_wrapper(wrapper_match.group(0), plan)
    if not changed:
        report.warnings.append(f"Donor texture binding found no compatible target parameters for {target_name or 'target wrapper'}.")
        return sidecar_text, False, True
    patched = sidecar_text[: wrapper_match.start()] + new_wrapper + sidecar_text[wrapper_match.end() :]
    report.warnings.append(f"Donor texture binding patched target material wrapper: {target_name or 'target wrapper'}.")
    return patched, True, True


def _build_donor_material_sidecar_payloads(
    *,
    original_sidecars: Sequence[tuple[object, str]],
    donor_material_plans: Sequence[object],
    report: TextureReplacementReport,
) -> list[TextureReplacementPayload]:
    plans = tuple(plan for plan in tuple(donor_material_plans or ()) if bool(getattr(plan, "enabled", True)))
    if not plans:
        return []
    if not original_sidecars:
        report.warnings.append("Donor material source could not patch .pac_xml because no target material sidecar was available.")
        return []

    patched_by_path: dict[str, tuple[object, str, bool]] = {}
    for sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        sidecar_path = str(getattr(sidecar_entry, "path", "") or "").strip()
        if sidecar_path:
            patched_by_path[sidecar_path] = (sidecar_entry, str(sidecar_text or ""), False)

    for plan in plans:
        target_name = str(getattr(plan, "target_material_name", "") or "").strip() or "target wrapper"
        plan_applied = False
        plan_matched_target = False
        for sidecar_path in list(patched_by_path):
            sidecar_entry, current_text, changed_before = patched_by_path[sidecar_path]
            patched_text, changed, matched_target = _apply_donor_material_plan_to_sidecar(
                current_text,
                sidecar_path=sidecar_path,
                plan=plan,
                report=report,
            )
            plan_matched_target = plan_matched_target or matched_target
            if changed:
                patched_by_path[sidecar_path] = (sidecar_entry, patched_text, True)
                plan_applied = True
                break
            patched_by_path[sidecar_path] = (sidecar_entry, current_text, changed_before)
        if not plan_matched_target:
            report.warnings.append(f"Donor material source target wrapper was not found: {target_name}.")
        elif not plan_applied:
            report.warnings.append(f"Donor material source did not modify target wrapper: {target_name}.")

    from .material_replacer import TextureReplacementPayload

    sidecar_payloads: list[TextureReplacementPayload] = []
    for sidecar_path, (_sidecar_entry, patched_text, changed) in patched_by_path.items():
        if not changed:
            continue
        sidecar_payloads.append(
            TextureReplacementPayload(
                target_path=sidecar_path,
                payload_data=patched_text.encode("utf-8"),
                kind="sidecar_generated",
                source_path=Path(PurePosixPath(sidecar_path).name),
                note="Donor material sidecar patched from another original mesh.",
            )
        )
    if sidecar_payloads:
        report.warnings.append(f"Generated {len(sidecar_payloads):,} donor material sidecar patch payload(s).")
    return sidecar_payloads
