from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtGui import QImage

from cdmw.models import PreviewMaterialTextureInput
from cdmw.rendering.crimson_shader_registry import AUTHORITY_GUESS
from cdmw.rendering.material_combiner_rules import (
    MaterialPreviewCombinerResult,
    MaterialPreviewCombinerSettings,
    _LAYER_CHANNEL_INDEX,
    _NONMETAL_RESPONSE_LIMITS,
    _SHADER_RULE_PARAMETER_NOTES,
    _TECHNICAL_BASE_TOKENS,
    _VISIBLE_BASE_TOKENS,
    _apply_nonmetal_response_limits,
    _apply_sidecar_material_hints,
    _authoritative_color_blending_tint_seed,
    _byte4_channels,
    _clamp,
    _color_blending_channel_enabled,
    _color_blending_disabled,
    _descriptor_contains_token,
    _finite_float,
    _first_input_by_parameter,
    _global_material_base_tint,
    _height_amount_multiplier,
    _is_layer_only_base_color,
    _is_low_authority_base,
    _is_visible_color_input,
    _layer_channel,
    _layer_tint,
    _layer_weight_from_parameters,
    _looks_like_technical_base,
    _looks_like_visible_base,
    _mask_inputs_for_albedo,
    _material_candidate_match_score,
    _material_compact_key,
    _material_core_tokens,
    _material_layer_mask_for_input,
    _material_parameter_channel_hint,
    _material_parameter_channels,
    _material_parameter_color,
    _material_parameter_color_luma,
    _material_parameter_count,
    _material_parameter_hint,
    _material_parameter_integer,
    _material_parameter_numeric,
    _material_parameter_record_for_key,
    _material_parameters,
    _material_surface_category,
    _material_surface_descriptor,
    _material_token_match_score,
    _neutral_metal_base_color,
    _neutral_metal_tint_from_tokens,
    _nonmetal_response_limits,
    _normalize_texture_key,
    _normalized_key,
    _parameter_key,
    _payload_vertex_base_color,
    _registry_decode_for_input,
    _registry_decode_mode_for_input,
    _select_visible_layer_inputs,
    _semantic_text,
    _shader_rule_for_inputs,
    _should_seed_neutral_metal_base,
    _stem_tokens,
    _strong_metallic_override,
    _texture_label,
    _texture_rule_for_input,
    _visible_layer_role,
)
from cdmw.rendering.material_combiner_decode import (
    _apply_external_material_factors,
    _decode_mode_for_input,
    _material_candidate_group,
    _material_decode_output_flags,
    _material_parameter_index,
    _material_slot_priority,
    _material_slot_priority_for_input,
    _select_material_candidates_for_payload,
    decode_material_sample,
)
from cdmw.rendering.material_combiner_images import (
    _byte,
    _combine_material_slot_maps,
    _generate_material_maps,
    _generate_spec_gloss_preview_albedo_map,
    _generate_synthesized_albedo_map,
    _image_exceeds_dimension,
    _image_luma_range,
    _image_reader,
    _image_rgb888_write_view,
    _image_rgba8888_view,
    _local_file_url,
    _mask_alpha,
    _prepare_image,
    _read_generated_map,
    _raise_if_material_combiner_cancelled,
    _rgba8888_mask_alpha,
    _source_url_local_path,
    _support_source_image,
)
from cdmw.rendering.material_combiner_support_maps import (
    _derive_normal_from_height,
    _generate_height_map,
    _generate_legacy_pbr_response_map,
    _generate_normal_map,
    _generate_synthesized_normal_map,
    _is_layer_normal_input,
)


def synthesize_material_texture_inputs(batch: object) -> Tuple[PreviewMaterialTextureInput, ...]:
    explicit = tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
    if explicit:
        return explicit
    material_name = str(getattr(batch, "material_name", "") or "").strip()
    texture_name = str(getattr(batch, "texture_name", "") or "").strip()
    inputs: list[PreviewMaterialTextureInput] = []
    base_path = str(getattr(batch, "preview_texture_path", "") or "").strip()
    if base_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="base",
                texture_name=texture_name,
                preview_texture_path=base_path,
                source_texture_path=texture_name or base_path,
                source_dds_path=str(getattr(batch, "preview_texture_dds_path", "") or ""),
                semantic_type="color",
                semantic_subtype="albedo",
                material_name=material_name,
                confidence="legacy",
                visualized=True,
            )
        )
    normal_path = str(getattr(batch, "preview_normal_texture_path", "") or "").strip()
    if normal_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="normal",
                texture_name=str(getattr(batch, "preview_normal_texture_name", "") or "") or normal_path,
                preview_texture_path=normal_path,
                source_texture_path=str(getattr(batch, "preview_normal_texture_name", "") or "") or normal_path,
                source_dds_path=str(getattr(batch, "preview_normal_texture_dds_path", "") or ""),
                semantic_type="normal",
                semantic_subtype="normal",
                material_name=material_name,
                confidence="legacy",
                visualized=True,
            )
        )
    material_path = str(getattr(batch, "preview_material_texture_path", "") or "").strip()
    if material_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="material",
                texture_name=str(getattr(batch, "preview_material_texture_name", "") or "") or material_path,
                preview_texture_path=material_path,
                source_texture_path=str(getattr(batch, "preview_material_texture_name", "") or "") or material_path,
                source_dds_path=str(getattr(batch, "preview_material_texture_dds_path", "") or ""),
                semantic_type=str(getattr(batch, "preview_material_texture_type", "") or "material").strip().lower(),
                semantic_subtype=str(getattr(batch, "preview_material_texture_subtype", "") or "").strip().lower(),
                packed_channels=tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ()),
                material_name=material_name,
                confidence="legacy",
                visualized=True,
            )
        )
    height_path = str(getattr(batch, "preview_height_texture_path", "") or "").strip()
    if height_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="height",
                texture_name=str(getattr(batch, "preview_height_texture_name", "") or "") or height_path,
                preview_texture_path=height_path,
                source_texture_path=str(getattr(batch, "preview_height_texture_name", "") or "") or height_path,
                source_dds_path=str(getattr(batch, "preview_height_texture_dds_path", "") or ""),
                semantic_type="height",
                semantic_subtype="displacement",
                material_name=material_name,
                confidence="legacy",
                visualized=True,
            )
        )
    return tuple(inputs)


def _apply_spec_gloss_albedo(
    inputs: Sequence[PreviewMaterialTextureInput],
    *,
    selected_base_image: QImage,
    output_dir: Path,
    batch_index: int,
    flip_vertical: bool,
    base_map_max_dimension: int,
    preserve_base_alpha: bool,
    base_source: str,
    base_note: str,
    notes: list[str],
    outputs: list[str],
    cancelled: Callable[[], bool] | None,
) -> tuple[str, str]:
    item = next(
        (
            candidate
            for candidate in inputs
            if _decode_mode_for_input(candidate) == "specular_glossiness"
            and (
                _material_parameter_color_luma(candidate, "specularfactor", "specularcolorfactor") is None
                or (_material_parameter_color_luma(candidate, "specularfactor", "specularcolorfactor") or 0.0) > 0.02
            )
        ),
        None,
    )
    if item is None:
        return base_source, base_note
    _raise_if_material_combiner_cancelled(cancelled)
    image = _image_reader(str(item.preview_texture_path or ""), max_dimension=base_map_max_dimension)
    if image.isNull():
        return base_source, base_note
    generated_source, generated_note = _generate_spec_gloss_preview_albedo_map(
        selected_base_image,
        image,
        output_dir,
        f"batch_{batch_index:03d}",
        flip_vertical=flip_vertical,
        max_dimension=min(base_map_max_dimension, 512),
        preserve_base_alpha=preserve_base_alpha,
        cancelled=cancelled,
    )
    if not generated_source:
        return base_source, base_note
    if "albedo" not in outputs:
        outputs.append("albedo")
    notes.append(generated_note)
    return generated_source, generated_note


def _prepare_normal_source(
    payload: object,
    inputs: Sequence[PreviewMaterialTextureInput],
    *,
    settings: MaterialPreviewCombinerSettings,
    output_dir: Path,
    batch_index: int,
    tangents_usable: bool,
    flip_vertical: bool,
    support_map_max_dimension: int,
    notes: list[str],
    outputs: list[str],
    cancelled: Callable[[], bool] | None,
) -> tuple[str, float]:
    candidates = [item for item in inputs if str(item.slot_kind or "").strip().lower() == "normal"]
    if candidates and not tangents_usable:
        notes.append("missing tangents")
    if not tangents_usable:
        return "", 0.0
    (
        synthesized_source,
        synthesized_average_strength,
        synthesized_roles,
        synthesized_unreadable_inputs,
    ) = (
        _generate_synthesized_normal_map(
            candidates,
            _mask_inputs_for_albedo(inputs),
            output_dir,
            f"batch_{batch_index:03d}",
            flip_vertical=flip_vertical,
            max_dimension=support_map_max_dimension,
            cancelled=cancelled,
        )
    )
    notes.extend(synthesized_unreadable_inputs)
    if synthesized_source:
        configured_strength = _finite_float(getattr(payload, "normal_texture_strength", 0.0), 0.0)
        if configured_strength <= 0.0:
            configured_strength = max(settings.normal_strength_floor, synthesized_average_strength)
        strength = _clamp(configured_strength, settings.normal_strength_floor, settings.normal_strength_cap)
        outputs.append("normal")
        notes.append("normal green inverted")
        notes.append("normal layers synthesized:" + ",".join(synthesized_roles[:6]))
        return synthesized_source, strength
    # A layer-only normal is not a valid whole-surface fallback when its mask
    # disables synthesis or its base normal is missing.
    for item in (candidate for candidate in candidates if not _is_layer_normal_input(candidate)):
        _raise_if_material_combiner_cancelled(cancelled)
        image = _image_reader(str(item.preview_texture_path or ""), max_dimension=support_map_max_dimension)
        if image.isNull():
            notes.append(f"normal unreadable:{_texture_label(item.preview_texture_path, item.texture_name)}")
            continue
        if _image_exceeds_dimension(image, support_map_max_dimension):
            notes.append(f"support maps capped:{support_map_max_dimension}px")
        source, average_strength = _generate_normal_map(
            image,
            output_dir,
            f"batch_{batch_index:03d}",
            flip_vertical=flip_vertical,
            max_dimension=support_map_max_dimension,
            cancelled=cancelled,
        )
        if not source:
            continue
        configured_strength = _finite_float(getattr(payload, "normal_texture_strength", 0.0), 0.0)
        if configured_strength <= 0.0:
            configured_strength = max(settings.normal_strength_floor, average_strength)
        strength = _clamp(configured_strength, settings.normal_strength_floor, settings.normal_strength_cap)
        outputs.append("normal")
        notes.append("normal green inverted")
        return source, strength
    return "", 0.0


def combine_preview_material(
    payload: object,
    output_dir: Path,
    batch_index: int,
    *,
    settings: MaterialPreviewCombinerSettings,
    cancelled: Callable[[], bool] | None = None,
) -> MaterialPreviewCombinerResult:
    _raise_if_material_combiner_cancelled(cancelled)
    notes: list[str] = []
    outputs: list[str] = []
    decode_modes: list[str] = []
    flip_vertical = bool(getattr(payload, "texture_flip_vertical", False))
    prepare_flip_vertical = bool(
        flip_vertical and not settings.preserve_texture_orientation
    )
    alpha_mode = str(getattr(payload, "alpha_mode", "") or "").strip().casefold()
    preserve_base_alpha = alpha_mode in {
        "alpha_blend",
        "alpha_cutout",
        "blend",
        "cutout",
        "mask",
        "transparent",
    }
    inputs = tuple(getattr(payload, "material_texture_inputs", ()) or ())
    shader_rule = _shader_rule_for_inputs(inputs, payload)
    shader_families = tuple(
        dict.fromkeys(
            str(getattr(item, "shader_family", "") or "").strip()
            for item in inputs
            if str(getattr(item, "shader_family", "") or "").strip()
        )
    )
    if shader_rule != "generic":
        notes.append(f"shader rule:{shader_rule}")
        registry_note = _SHADER_RULE_PARAMETER_NOTES.get(shader_rule, "")
        if registry_note:
            notes.append(registry_note)
    if shader_families:
        notes.append("shader family:" + ",".join(shader_families[:3]))
    parameter_count = sum(_material_parameter_count(item) for item in inputs)
    if parameter_count > 0:
        notes.append(f"sidecar parameters:{parameter_count}")
    support_map_max_dimension = max(96, min(256, int(settings.support_map_max_dimension or 256)))
    base_map_max_dimension = max(512, min(1024, support_map_max_dimension * 4))

    base_source = ""
    base_note = ""
    selected_base_item: Optional[PreviewMaterialTextureInput] = None
    selected_base_image = QImage()
    selected_base_low_authority = False
    # PAC emissive/intensity inputs are additive controls, never full albedo.
    # Only exact color/base bindings may seed the whole base surface.
    base_candidates = [
        item
        for item in inputs
        if str(item.slot_kind or "").strip().lower() in {"base", "color"}
        and _visible_layer_role(item) != "emissive"
    ]
    for item in base_candidates:
        _raise_if_material_combiner_cancelled(cancelled)
        if _is_layer_only_base_color(item):
            notes.append(f"layer-only base rejected:{_texture_label(item.source_texture_path, item.texture_name)}")
            continue
        if _looks_like_technical_base(item):
            notes.append(f"technical base rejected:{_texture_label(item.source_texture_path, item.texture_name)}")
            continue
        if not _looks_like_visible_base(item):
            notes.append(f"non-color base rejected:{_texture_label(item.source_texture_path, item.texture_name)}")
            continue
        image = _image_reader(str(item.preview_texture_path or ""), max_dimension=base_map_max_dimension)
        if image.isNull():
            notes.append(f"base unreadable:{_texture_label(item.preview_texture_path, item.texture_name)}")
            continue
        if _image_exceeds_dimension(image, base_map_max_dimension):
            notes.append(f"base maps capped:{base_map_max_dimension}px")
        selected_base_item = item
        selected_base_image = image
        selected_base_low_authority = _is_low_authority_base(item)
        base_source, base_note = _prepare_image(
            image,
            output_dir,
            f"batch_{batch_index:03d}_base",
            flip_vertical=prepare_flip_vertical,
            force_opaque=not preserve_base_alpha,
            max_dimension=base_map_max_dimension,
        )
        _raise_if_material_combiner_cancelled(cancelled)
        if base_source:
            outputs.append("albedo")
            if preserve_base_alpha:
                notes.append(f"base alpha preserved:{alpha_mode}")
            break

    visible_layer_inputs = _select_visible_layer_inputs(inputs, selected_base=selected_base_item)
    force_layer_synthesis = bool(
        shader_rule == "static_multitextured"
        and any(_visible_layer_role(item) == "layer" for item in visible_layer_inputs)
    )
    should_synthesize_albedo = bool(visible_layer_inputs and (not base_source or selected_base_low_authority or force_layer_synthesis))
    if should_synthesize_albedo:
        _raise_if_material_combiner_cancelled(cancelled)
        neutral_base_color = ()
        neutral_metal_base = _should_seed_neutral_metal_base(
            payload,
            inputs,
            visible_layer_inputs,
            selected_base_low_authority=selected_base_low_authority,
            selected_base_item=selected_base_item,
        )
        if neutral_metal_base:
            neutral_base_color = _neutral_metal_base_color(payload, inputs)
            notes.append("neutral_metal_base_synthesized")
            notes.append("no_reliable_full_base_albedo")
            for layer_item in visible_layer_inputs:
                label = _texture_label(layer_item.source_texture_path, layer_item.texture_name)
                role = _visible_layer_role(layer_item)
                channel = _layer_channel(layer_item)
                role_label = role if not channel else f"{role}:{channel}"
                notes.append(f"texturelayer_kept_masked:{role_label}:{label}")
        (
            color_blending_mask,
            color_blending_tints,
            color_blending_palette_source,
        ) = _authoritative_color_blending_tint_seed(inputs)
        if color_blending_palette_source:
            notes.append(f"pac color blending palette:{color_blending_palette_source}")
        synthesized_source, synthesized_note = _generate_synthesized_albedo_map(
            QImage() if neutral_metal_base else selected_base_image,
            visible_layer_inputs,
            _mask_inputs_for_albedo(inputs),
            output_dir,
            f"batch_{batch_index:03d}",
            flip_vertical=prepare_flip_vertical,
            max_dimension=min(base_map_max_dimension, 512),
            neutral_base_color=neutral_base_color,
            color_blending_mask_input=color_blending_mask,
            color_blending_tints=color_blending_tints,
            preserve_base_alpha=preserve_base_alpha,
            cancelled=cancelled,
        )
        if synthesized_source:
            base_source = synthesized_source
            base_note = synthesized_note
            if "albedo" not in outputs:
                outputs.append("albedo")
            notes.append(synthesized_note)
        elif not base_source:
            notes.append("albedo synthesis failed")
    if not base_source and base_candidates:
        notes.append("no reliable base DDS")

    base_source, base_note = _apply_spec_gloss_albedo(
        inputs,
        selected_base_image=selected_base_image,
        output_dir=output_dir,
        batch_index=batch_index,
        flip_vertical=prepare_flip_vertical,
        base_map_max_dimension=base_map_max_dimension,
        preserve_base_alpha=preserve_base_alpha,
        base_source=base_source,
        base_note=base_note,
        notes=notes,
        outputs=outputs,
        cancelled=cancelled,
    )

    tangents_usable = bool(getattr(payload, "tangents_usable", False))
    normal_source, normal_strength = _prepare_normal_source(
        payload,
        inputs,
        settings=settings,
        output_dir=output_dir,
        batch_index=batch_index,
        tangents_usable=tangents_usable,
        flip_vertical=prepare_flip_vertical,
        support_map_max_dimension=support_map_max_dimension,
        notes=notes,
        outputs=outputs,
        cancelled=cancelled,
    )

    occlusion_source = ""
    roughness_source = ""
    metalness_source = ""
    specular_source = ""
    material_slot_priorities = {
        "occlusion": -1,
        "roughness": -1,
        "metalness": -1,
        "specular": -1,
    }
    material_slot_modes: dict[str, str] = {}
    material_slot_layers: dict[str, list[Tuple[int, str, str]]] = {
        "occlusion": [],
        "roughness": [],
        "metalness": [],
        "specular": [],
    }
    raw_material_candidates = [
        item
        for item in inputs
        if (
            str(item.slot_kind or "").strip().lower()
            in {"material", "material_mask", "detail_mask", "occlusion", "ao", "roughness", "metalness", "specular", "glossiness"}
        )
        and not _is_visible_color_input(item)
    ]
    material_candidates, culled_material_count = _select_material_candidates_for_payload(raw_material_candidates, payload)
    if culled_material_count > 0:
        notes.append(f"material inputs culled:{len(raw_material_candidates)}->{len(material_candidates)}")
    material_candidate_decode_modes = tuple(_decode_mode_for_input(candidate) for candidate in material_candidates)
    registry_authority_notes = []
    for candidate, mode in zip(material_candidates, material_candidate_decode_modes):
        _raise_if_material_combiner_cancelled(cancelled)
        decode = _registry_decode_for_input(candidate)
        authority = str(decode.get("authority", "") or AUTHORITY_GUESS)
        source_kind = str(decode.get("source_kind", "") or "")
        if authority != AUTHORITY_GUESS and source_kind not in {"unknown_crimson_texture", ""}:
            registry_authority_notes.append(f"{mode}:{authority}:{source_kind}")
    if registry_authority_notes:
        notes.append("registry authority:" + ",".join(dict.fromkeys(registry_authority_notes)))
    suppress_standard_v2_specular_metalness = any(
        mode in {"standard_v2_mask", "standard_v2_material"}
        for mode in material_candidate_decode_modes
    )
    for material_index, item in enumerate(material_candidates):
        _raise_if_material_combiner_cancelled(cancelled)
        mode = material_candidate_decode_modes[material_index] if material_index < len(material_candidate_decode_modes) else _decode_mode_for_input(item)
        if mode == "opacity":
            notes.append(f"opacity ignored:{_texture_label(item.source_texture_path, item.texture_name)}")
            continue
        image = _image_reader(str(item.preview_texture_path or ""), max_dimension=support_map_max_dimension)
        if image.isNull():
            notes.append(f"material unreadable:{_texture_label(item.preview_texture_path, item.texture_name)}")
            continue
        if _image_exceeds_dimension(image, support_map_max_dimension):
            notes.append(f"support maps capped:{support_map_max_dimension}px")
        decode_modes.append(mode)
        hint_labels: list[str] = []
        if any(_material_decode_output_flags(mode)):
            channel = _layer_channel(item)
            if _material_parameter_channel_hint(item, channel, "metallic", "metalness", "scratchmetallic") > 0.02:
                hint_labels.append("metallic")
            if _material_parameter_channel_hint(item, channel, "roughness", "scratchroughness") > 0.02:
                hint_labels.append("roughness")
            if _material_parameter_hint(item, "specular", "specularamount") > 0.02:
                hint_labels.append("specular")
        if hint_labels:
            notes.append(f"sidecar material hints:{'+'.join(dict.fromkeys(hint_labels))}")
        surface_category = _material_surface_category(item, payload)
        force_nonmetal_material_response = bool(
            surface_category in _NONMETAL_RESPONSE_LIMITS
            and not _strong_metallic_override(item, payload)
        )
        if (
            force_nonmetal_material_response
            and any(_material_decode_output_flags(mode))
        ):
            notes.append(
                "nonmetal material response clamp:"
                f"{surface_category}:{_texture_label(item.source_texture_path, item.texture_name)}"
            )
        layer_mask_image = QImage()
        layer_mask_channel = ""
        layer_weight = 1.0
        mask_item, mask_channel, mask_label = _material_layer_mask_for_input(item, inputs)
        if mask_item is not None:
            layer_mask_channel = mask_channel or "r"
            layer_weight = _layer_weight_from_parameters(item, has_base=bool(base_source))
            if layer_weight <= 0.001:
                notes.append(f"material layer disabled by colorBlendingFlag:{mask_label}")
            layer_mask_image = _image_reader(
                str(getattr(mask_item, "preview_texture_path", "") or ""),
                max_dimension=support_map_max_dimension,
            )
            if layer_mask_image.isNull():
                notes.append(f"material layer mask unreadable:{mask_label}")
            else:
                notes.append(f"material layer mask applied:{mask_label}")
        generated_slots, generated_paths = _generate_material_maps(
            image,
            output_dir,
            f"batch_{batch_index:03d}_{material_index:02d}_{mode}",
            decode_mode=mode,
            input_item=item,
            surface_category=surface_category,
            force_nonmetal_surface=force_nonmetal_material_response,
            layer_mask=layer_mask_image if not layer_mask_image.isNull() else None,
            layer_mask_channel=layer_mask_channel,
            layer_weight=layer_weight,
            flip_vertical=prepare_flip_vertical,
            max_dimension=support_map_max_dimension,
            cancelled=cancelled,
        )
        if generated_slots:
            source_by_slot = {
                "occlusion": generated_paths[0],
                "roughness": generated_paths[1],
                "metalness": generated_paths[2],
                "specular": generated_paths[3],
            }
            if mode == "standard_v2_specular" and suppress_standard_v2_specular_metalness:
                generated_slots = tuple(slot for slot in generated_slots if slot != "metalness")
                source_by_slot["metalness"] = ""
            for slot_name in generated_slots:
                slot_source = source_by_slot.get(slot_name, "")
                if not slot_source:
                    continue
                priority = _material_slot_priority_for_input(item, mode, slot_name)
                if priority <= material_slot_priorities.get(slot_name, -1):
                    material_slot_layers.setdefault(slot_name, []).append((priority, mode, slot_source))
                else:
                    material_slot_priorities[slot_name] = priority
                    material_slot_modes[slot_name] = mode
                    material_slot_layers.setdefault(slot_name, []).append((priority, mode, slot_source))
            outputs.extend(slot for slot in generated_slots if slot not in outputs)

    if any(material_slot_layers.values()) and shader_rule in {"standard_v2", "emissive_v2", "cloth_v2", "cloth"}:
        notes.append("material blend order: sidecar parameter order + grime/detail channel masks")

    blended_slots: list[str] = []
    for slot_name in ("occlusion", "roughness", "metalness", "specular"):
        _raise_if_material_combiner_cancelled(cancelled)
        layers = material_slot_layers.get(slot_name, [])
        if not layers:
            continue
        combined_source, combined_mode = _combine_material_slot_maps(
            slot_name,
            layers,
            output_dir,
            f"batch_{batch_index:03d}_combined",
            cancelled=cancelled,
        )
        if not combined_source:
            continue
        if slot_name == "occlusion":
            occlusion_source = combined_source
        elif slot_name == "roughness":
            roughness_source = combined_source
        elif slot_name == "metalness":
            metalness_source = combined_source
        elif slot_name == "specular":
            specular_source = combined_source
        if combined_mode:
            material_slot_modes[slot_name] = combined_mode
        if len(layers) > 1:
            blended_slots.append(f"{slot_name}:{len(layers)}")

    material_sources = {
        "occlusion": occlusion_source,
        "roughness": roughness_source,
        "metalness": metalness_source,
        "specular": specular_source,
    }
    slots = tuple(slot_name for slot_name in ("occlusion", "roughness", "metalness", "specular") if material_sources[slot_name])
    legacy_material_source = ""
    if slots:
        legacy_material_source = _generate_legacy_pbr_response_map(
            output_dir,
            f"batch_{batch_index:03d}_combined",
            occlusion_source=occlusion_source,
            roughness_source=roughness_source,
            metalness_source=metalness_source,
            specular_source=specular_source,
            cancelled=cancelled,
        )
        if legacy_material_source:
            outputs.append("legacy_material")
    if len(tuple(dict.fromkeys(decode_modes))) > 1 and slots:
        slot_mode_text = ", ".join(
            f"{slot_name}={material_slot_modes.get(slot_name, 'unknown')}"
            for slot_name in slots
            if material_slot_modes.get(slot_name)
        )
        if slot_mode_text:
            notes.append(f"material inputs combined:{slot_mode_text}")
    if blended_slots:
        notes.append(f"material slots blended:{', '.join(blended_slots)}")

    height_source = ""
    height_amount = 0.0
    height_image = QImage()
    height_candidates = [item for item in inputs if str(item.slot_kind or "").strip().lower() == "height"]
    best_height_contrast = -1.0
    best_height_index = -1
    selected_height_source = ""
    selected_height_item: Optional[PreviewMaterialTextureInput] = None
    for height_index, item in enumerate(height_candidates):
        _raise_if_material_combiner_cancelled(cancelled)
        image = _image_reader(str(item.preview_texture_path or ""), max_dimension=support_map_max_dimension)
        if image.isNull():
            notes.append(f"height unreadable:{_texture_label(item.preview_texture_path, item.texture_name)}")
            continue
        if _image_exceeds_dimension(image, support_map_max_dimension):
            notes.append(f"support maps capped:{support_map_max_dimension}px")
        height_image = image
        height_source, contrast = _generate_height_map(
            image,
            output_dir,
            f"batch_{batch_index:03d}_{height_index:02d}",
            flip_vertical=prepare_flip_vertical,
            max_dimension=support_map_max_dimension,
            cancelled=cancelled,
        )
        if not height_source:
            notes.append(f"height flat:{contrast:.3f}")
            continue
        if contrast > best_height_contrast:
            best_height_contrast = contrast
            best_height_index = height_index
            height_image = image
            selected_height_source = height_source
            selected_height_item = item
    if best_height_contrast >= 0.0:
        height_source = selected_height_source
        height_multiplier = 1.0
        height_parameter = ""
        if selected_height_item is not None:
            height_multiplier, height_parameter = _height_amount_multiplier(selected_height_item)
        height_amount = _clamp(
            settings.height_amount * _clamp(0.65 + (best_height_contrast * 1.40), 0.65, 1.0) * height_multiplier,
            0.0,
            0.12,
        )
        outputs.append("height")
        if height_parameter:
            notes.append(f"height scale:{height_multiplier:.2f} from {height_parameter}")
        if len(height_candidates) > 1:
            notes.append(f"height selected:{best_height_index} contrast={best_height_contrast:.3f}")
    if not normal_source and tangents_usable and not height_image.isNull():
        derived_normal_source, contrast = _derive_normal_from_height(
            height_image,
            output_dir,
            f"batch_{batch_index:03d}",
            flip_vertical=prepare_flip_vertical,
            max_dimension=support_map_max_dimension,
            cancelled=cancelled,
        )
        if derived_normal_source:
            normal_source = derived_normal_source
            normal_strength = _clamp(settings.normal_strength_floor * 0.55, 0.15, settings.normal_strength_cap)
            outputs.append("normal-from-height")
            notes.append("normal derived from height")
        elif height_candidates:
            notes.append(f"height normal derivation skipped:{contrast:.3f}")

    _raise_if_material_combiner_cancelled(cancelled)
    return MaterialPreviewCombinerResult(
        base_source=base_source,
        base_note=base_note,
        normal_source=normal_source,
        normal_strength=normal_strength,
        occlusion_source=occlusion_source,
        roughness_source=roughness_source,
        metalness_source=metalness_source,
        specular_source=specular_source,
        height_source=height_source,
        height_amount=height_amount,
        legacy_material_source=legacy_material_source,
        legacy_material_decode_mode="pbr_combined" if legacy_material_source else "",
        material_slots=slots,
        decode_modes=tuple(dict.fromkeys(decode_modes)),
        notes=tuple(dict.fromkeys(notes)),
        outputs=tuple(dict.fromkeys(outputs)),
        active=bool(outputs or notes),
        texture_flip_vertical=(
            flip_vertical
            if settings.preserve_texture_orientation
            else (False if outputs else flip_vertical)
        ),
    )


__all__ = [
    "MaterialPreviewCombinerResult",
    "MaterialPreviewCombinerSettings",
    "combine_preview_material",
    "decode_material_sample",
    "synthesize_material_texture_inputs",
]
