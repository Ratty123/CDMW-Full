"""Raw support-map channels the resident .NET viewport consumes undecoded.

A normal, height, or packed material input whose `.dds` is packaged verbatim is
normally deferred because `_generated_channels` discards the combiner's own
output for that channel. There are two exceptions. A selected macro normal
needed for authored layer composition is decoded for synthesis, but decode
failure falls back to the packaged DDS without publishing a detail-only
replacement. An input the combiner reads as a selector mask (albedo, layered
normal, or material-layer) is decoded even when it is also the raw channel,
because the mask has to be readable for the layer to compose at all. Keeping
that policy and its diagnostic relabelling together stops a deliberate skip
from reading as a hard material-compile failure.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QUrl

from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput


def _input_value(item: object, name: str, fallback: object = "") -> object:
    if isinstance(item, Mapping):
        return item.get(name, fallback)
    return getattr(item, name, fallback)


def _local_synthesis_dds_path(item: object) -> Path | None:
    for field_name in (
        "preview_texture_path",
        "source_dds_path",
        "source_texture_path",
    ):
        raw_path = str(_input_value(item, field_name) or "").strip()
        if not raw_path:
            continue
        if raw_path.casefold().startswith("file:"):
            raw_path = QUrl(raw_path).toLocalFile()
        try:
            path = Path(raw_path).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if path.suffix.casefold() == ".dds" and path.is_file():
            return path
    return None


def _native_support_map_channel(
    item: object,
    raw_channels: Mapping[str, str],
) -> str:
    """Return the raw channel that already covers `item`, or "" when none does."""
    slot = str(_input_value(item, "slot_kind") or "").strip().casefold()
    semantic = str(_input_value(item, "semantic_type") or "").strip().casefold()
    if slot == "normal" or semantic == "normal":
        channel = "normal"
    elif slot in {"height", "displacement"} or semantic in {"height", "displacement"}:
        channel = "height"
    elif slot == "material" or semantic == "material":
        channel = "material"
    else:
        return ""
    item_path = _local_synthesis_dds_path(item)
    raw_path = _local_synthesis_dds_path(
        {"source_dds_path": raw_channels.get(channel, "")}
    )
    if item_path is None or raw_path is None:
        return ""
    return (
        channel
        if os.path.normcase(str(item_path)) == os.path.normcase(str(raw_path))
        else ""
    )


def _has_native_support_map(
    item: object,
    raw_channels: Mapping[str, str],
) -> bool:
    return bool(_native_support_map_channel(item, raw_channels))


class _CallbackStopEvent:
    def __init__(self, cancelled: Callable[[], bool] | None) -> None:
        self._cancelled = cancelled

    def is_set(self) -> bool:
        return bool(self._cancelled is not None and self._cancelled())


def _synthesis_mask_input_ids(
    material_inputs: tuple[PreviewMaterialTextureInput, ...],
) -> tuple[set[int], set[int]]:
    """Return (albedo mask ids, every selector mask id) among `material_inputs`.

    Albedo and layered-normal synthesis read the masks `_mask_inputs_for_albedo`
    picks; material-layer synthesis reads the one `_material_layer_mask_for_input`
    picks per material input. Each is opened through `preview_texture_path`, so a
    mask left as its raw `.dds` reads as `... mask unreadable:` and blocks the
    compile. On a texture-layer weapon PAC the grime selector is also the raw
    material channel, which is exactly the input the deferral would have skipped.
    """
    from cdmw.rendering.material_combiner_rules import (
        _mask_inputs_for_albedo,
        _material_layer_mask_for_input,
    )

    albedo_mask_ids = {id(item) for item in _mask_inputs_for_albedo(material_inputs).values()}
    mask_ids = set(albedo_mask_ids)
    for item in material_inputs:
        mask_item, _channel, _label = _material_layer_mask_for_input(item, material_inputs)
        if mask_item is not None:
            mask_ids.add(id(mask_item))
    return albedo_mask_ids, mask_ids


def _synthesis_preview_profile(
    item: object,
    *,
    high_resolution_mask: bool = False,
) -> tuple[int, str, str, str]:
    slot = str(_input_value(item, "slot_kind") or "").strip().casefold()
    semantic = str(_input_value(item, "semantic_type") or "").strip().casefold()
    color_input = slot in {"base", "color", "emissive"} or semantic in {
        "albedo",
        "base",
        "color",
        "diffuse",
        "emissive",
    }
    normal_input = slot == "normal" or semantic == "normal"
    # This decode is where support-map resolution is actually decided. Nothing
    # downstream can recover detail it drops; support-map preparation only
    # downscales. Sources are overwhelmingly 256 or smaller.
    max_dimension = 512 if color_input or high_resolution_mask else 256
    decode_slot = "base" if color_input else ("normal" if normal_input else "material")
    srgb = str(_input_value(item, "srgb_mode") or "").strip().casefold()
    if not srgb:
        srgb = "srgb" if color_input else "linear"
    normal_space = str(_input_value(item, "normal_space") or "").strip().casefold() or "auto"
    return max_dimension, decode_slot, srgb, normal_space


def _decode_synthesis_input_previews(
    inputs: tuple[object, ...],
    raw_channels: Mapping[str, str],
    *,
    cancelled: Callable[[], bool] | None,
) -> tuple[tuple[object, ...], int, dict[str, set[str]], dict[str, object]]:
    from cdmw.core.texture_native import (
        directxtex_preview_result_key,
        ensure_directxtex_dds_preview_pngs,
    )
    from cdmw.rendering.material_combiner_rules import _texture_label
    from cdmw.rendering.material_combiner_support_maps import _is_layer_normal_input

    jobs: list[dict[str, object]] = []
    job_keys: dict[int, str] = {}
    diagnostics: dict[str, object] = {
        "input_count": len(inputs),
        "dds_candidate_count": 0,
        "decode_job_count": 0,
        "native_channel_deferred_count": 0,
        "raw_channel_mask_decoded_count": 0,
        "missing_dds_input_count": 0,
        "missing_dds_input_sample": [],
        "preview_deferred_by_environment": bool(
            os.environ.get("CDMW_DEFER_TEXTURE_PREVIEW", "").strip()
        ),
    }
    # Raw DDS inputs are normally deferred. Keep their labels so the combiner's
    # unreadable note can be relabelled after its diagnostic pass.
    deferred_raw_channel_labels: dict[str, set[str]] = {}
    material_inputs = tuple(
        item for item in inputs if isinstance(item, PreviewMaterialTextureInput)
    )
    albedo_mask_ids, mask_input_ids = _synthesis_mask_input_ids(material_inputs)
    layered_normal_synthesis = any(
        _is_layer_normal_input(item)
        and (
            str(_input_value(item, "slot_kind") or "").strip().casefold() == "normal"
            or str(_input_value(item, "semantic_type") or "").strip().casefold()
            == "normal"
        )
        for item in material_inputs
    )
    selected_normal_index = next(
        (
            index
            for index, item in enumerate(inputs)
            if isinstance(item, PreviewMaterialTextureInput)
            and not _is_layer_normal_input(item)
            and _native_support_map_channel(item, raw_channels) == "normal"
        ),
        None,
    )
    for index, item in enumerate(inputs):
        dds_path = _local_synthesis_dds_path(item)
        if dds_path is None:
            candidates = {
                field_name: str(_input_value(item, field_name) or "").strip()
                for field_name in (
                    "preview_texture_path",
                    "source_dds_path",
                    "source_texture_path",
                )
                if str(_input_value(item, field_name) or "").strip()
            }
            if any(
                str(value).casefold().endswith(".dds")
                for value in (
                    *candidates.values(),
                    _input_value(item, "texture_name"),
                )
            ):
                diagnostics["missing_dds_input_count"] = int(
                    diagnostics["missing_dds_input_count"]
                ) + 1
                sample = diagnostics["missing_dds_input_sample"]
                if isinstance(sample, list) and len(sample) < 8:
                    sample.append(
                        {
                            "index": index,
                            "slot_kind": str(_input_value(item, "slot_kind") or ""),
                            "semantic_type": str(
                                _input_value(item, "semantic_type") or ""
                            ),
                            "texture_name": str(
                                _input_value(item, "texture_name") or ""
                            ),
                            "candidate_paths": candidates,
                        }
                    )
            continue
        diagnostics["dds_candidate_count"] = int(
            diagnostics["dds_candidate_count"]
        ) + 1
        native_channel = _native_support_map_channel(item, raw_channels)
        if native_channel and id(item) in mask_input_ids:
            diagnostics["raw_channel_mask_decoded_count"] = int(
                diagnostics["raw_channel_mask_decoded_count"]
            ) + 1
        elif native_channel and not (
            native_channel == "normal" and layered_normal_synthesis
        ):
            diagnostics["native_channel_deferred_count"] = int(
                diagnostics["native_channel_deferred_count"]
            ) + 1
            deferred_raw_channel_labels.setdefault(native_channel, set()).add(
                _texture_label(
                    _input_value(item, "preview_texture_path"),
                    _input_value(item, "texture_name"),
                ).casefold()
            )
            continue
        max_dimension, slot_kind, srgb, normal_space = _synthesis_preview_profile(
            item,
            high_resolution_mask=id(item) in albedo_mask_ids,
        )
        jobs.append(
            {
                "dds_path": str(dds_path),
                "max_dimension": max_dimension,
                "slot_kind": slot_kind,
                "srgb": srgb,
                "normal_space": normal_space,
            }
        )
        job_keys[index] = directxtex_preview_result_key(
            dds_path,
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
        )
    diagnostics["decode_job_count"] = len(jobs)
    if not jobs:
        diagnostics["decoded_input_count"] = 0
        return inputs, 0, deferred_raw_channel_labels, diagnostics
    results = ensure_directxtex_dds_preview_pngs(
        jobs,
        include_job_keys=True,
        stop_event=_CallbackStopEvent(cancelled),
    )
    decoded_indices: set[int] = set()
    updated_inputs = list(inputs)
    for index, result_key in job_keys.items():
        preview_path = results.get(result_key)
        if preview_path is None or not preview_path.is_file():
            continue
        item = inputs[index]
        if not isinstance(item, PreviewMaterialTextureInput):
            continue
        updated_inputs[index] = replace(item, preview_texture_path=str(preview_path))
        decoded_indices.add(index)
    if layered_normal_synthesis and selected_normal_index is not None:
        selected_normal = updated_inputs[selected_normal_index]
        selected_decoded = selected_normal_index in decoded_indices
        if not selected_decoded:
            deferred_raw_channel_labels.setdefault("normal", set()).add(
                _texture_label(
                    _input_value(selected_normal, "preview_texture_path"),
                    _input_value(selected_normal, "texture_name"),
                ).casefold()
            )
        updated_inputs = [
            item
            for item in updated_inputs
            if item is selected_normal
            or not isinstance(item, PreviewMaterialTextureInput)
            or (
                selected_decoded
                and _is_layer_normal_input(item)
            )
            or (
                str(_input_value(item, "slot_kind") or "").strip().casefold()
                != "normal"
                and str(_input_value(item, "semantic_type") or "").strip().casefold()
                != "normal"
            )
        ]
    diagnostics["decoded_input_count"] = len(decoded_indices)
    return (
        tuple(updated_inputs),
        len(decoded_indices),
        deferred_raw_channel_labels,
        diagnostics,
    )


def _relabel_deferred_raw_channel_notes(
    notes: tuple[object, ...],
    deferred_raw_channel_labels: Mapping[str, set[str]],
) -> list[str]:
    """Stop a skipped decode from reading as a texture that could not be opened.

    Left as `normal unreadable:<name>.dds`, the note aborted the whole material
    compile, so a preview whose textures were all present and resolved never
    reached the viewport and Solid (Textured) stayed flat.
    """
    rewritten: list[str] = []
    for note in notes:
        text = str(note or "")
        folded = text.casefold()
        for channel, labels in deferred_raw_channel_labels.items():
            prefix = f"{channel} unreadable:"
            if not labels or not folded.startswith(prefix):
                continue
            label = text[len(prefix):].strip()
            if label.casefold() in labels:
                text = f"{channel} not decoded, raw channel packaged:{label}"
            break
        rewritten.append(text)
    return rewritten


__all__ = [
    "_decode_synthesis_input_previews",
    "_has_native_support_map",
    "_input_value",
    "_local_synthesis_dds_path",
    "_native_support_map_channel",
    "_relabel_deferred_raw_channel_notes",
    "_synthesis_mask_input_ids",
]
