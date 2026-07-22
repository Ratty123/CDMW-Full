from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(slots=True)
class PreviewMaterialParameterInput:
    parameter_kind: str = ""
    parameter_name: str = ""
    tag_name: str = ""
    string_item_id: str = ""
    item_id: str = ""
    index: int = -1
    value: str = ""
    texture_path: str = ""
    color_value: Tuple[float, float, float] = ()
    numeric_value: Optional[float] = None


@dataclass(slots=True)
class PreviewMaterialTextureInput:
    slot_kind: str = ""
    parameter_name: str = ""
    source_texture_path: str = ""
    source_dds_path: str = ""
    texture_name: str = ""
    preview_texture_path: str = ""
    semantic_type: str = ""
    semantic_subtype: str = ""
    packed_channels: Tuple[str, ...] = ()
    material_name: str = ""
    part_name: str = ""
    shader_family: str = ""
    confidence: str = ""
    visualized: bool = False
    sidecar_kind: str = ""
    sidecar_path: str = ""
    linked_mesh_path: str = ""
    srgb_mode: str = ""
    normal_space: str = ""
    parameter_declared_by: str = ""
    material_output_quality: str = ""
    layer_role: str = ""
    layer_channel: str = ""
    blend_flags: Tuple[str, ...] = ()
    owner_slot_index: int = -1
    owner_wrapper_item_id: str = ""
    binding_authority: str = ""
    binding_disposition: str = ""
    source_kind: str = ""
    material_parameters: Tuple[PreviewMaterialParameterInput, ...] = ()


__all__ = ["PreviewMaterialParameterInput", "PreviewMaterialTextureInput"]
