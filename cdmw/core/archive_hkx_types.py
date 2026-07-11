from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(slots=True)
class HkxPreviewResult:
    preview_text: str
    detail_lines: List[str]


@dataclass(slots=True)
class HkxTagItem:
    name: str
    offset: int
    length_word_offset: Optional[int] = None
    raw_length_word: Optional[int] = None
    declared_length: Optional[int] = None
    length_flags: Optional[int] = None
    marker_end_offset: Optional[int] = None
    word_end_offset: Optional[int] = None


@dataclass(slots=True)
class HkxItemRecord:
    index: int
    raw_type_flags: int
    type_index: int
    flags: int
    data_offset: int
    absolute_data_offset: Optional[int]
    count: int
    type_name: str = ""


@dataclass(slots=True)
class HkxItemPayloadSummary:
    record_index: int
    type_name: str
    byte_length: int
    inferred_stride: Optional[float]
    lines: List[str] = field(default_factory=list)


@dataclass(slots=True)
class HkxCollisionGeometryHint:
    shape_type: str = ""
    shape_record_index: Optional[int] = None
    mass_record_index: Optional[int] = None
    vertex_record_index: Optional[int] = None
    vertex_count: int = 0
    plane_record_index: Optional[int] = None
    plane_count: int = 0
    face_record_index: Optional[int] = None
    face_count: int = 0
    face_index_record_index: Optional[int] = None
    face_index_count: int = 0
    edge_record_indices: List[int] = field(default_factory=list)
    face_vertex_indices: List[Tuple[int, ...]] = field(default_factory=list)
    edge_pair_count: int = 0
    radius: Optional[float] = None
    capsule_length: Optional[float] = None
    mesh_section_count: int = 0
    mesh_primitive_count: int = 0
    mesh_aabb_node_count: int = 0
    mesh_shape_tag_count: int = 0
    mesh_data_byte_count: int = 0
    bounds_min: Optional[Tuple[float, float, float]] = None
    bounds_max: Optional[Tuple[float, float, float]] = None

    @property
    def center(self) -> Optional[Tuple[float, float, float]]:
        if self.bounds_min is None or self.bounds_max is None:
            return None
        return (
            (self.bounds_min[0] + self.bounds_max[0]) / 2.0,
            (self.bounds_min[1] + self.bounds_max[1]) / 2.0,
            (self.bounds_min[2] + self.bounds_max[2]) / 2.0,
        )

    @property
    def extent(self) -> Optional[Tuple[float, float, float]]:
        if self.bounds_min is None or self.bounds_max is None:
            return None
        return (
            self.bounds_max[0] - self.bounds_min[0],
            self.bounds_max[1] - self.bounds_min[1],
            self.bounds_max[2] - self.bounds_min[2],
        )


@dataclass(slots=True)
class HkxTypeInfo:
    index: int
    name: str
    template_parameters: List[Tuple[str, int]] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        if not self.template_parameters:
            return self.name
        parameters = ", ".join(f"{name}={value}" for name, value in self.template_parameters)
        return f"{self.name}<{parameters}>"


@dataclass(slots=True)
class HkxTagfileSummary:
    declared_size: Optional[int]
    size_matches: bool
    sdk_version: str
    tag0_offset: int
    tag_items: List[HkxTagItem]
    type_names: List[str]
    string_table_names: List[str]
    type_infos: List[HkxTypeInfo]
    declared_type_name_count: Optional[int]
    item_records: List[HkxItemRecord]
    item_payload_summaries: List[HkxItemPayloadSummary] = field(default_factory=list)
    collision_geometry_hints: List[HkxCollisionGeometryHint] = field(default_factory=list)
    native_object_records: List[Dict[str, object]] = field(default_factory=list)
    native_physics_tuning_groups: List[Dict[str, object]] = field(default_factory=list)
    native_tagfile_reference_fixups: Dict[str, object] = field(default_factory=dict)
    native_fixup_semantics_report: Dict[str, object] = field(default_factory=dict)
    native_model_graph: Dict[str, object] = field(default_factory=dict)
    native_hard_internal_evidence: Dict[str, object] = field(default_factory=dict)
    native_real_hkclass_metadata: Dict[str, object] = field(default_factory=dict)
    native_real_hkclass_metadata_v2: Dict[str, object] = field(default_factory=dict)
    native_fixup_semantics_v2: Dict[str, object] = field(default_factory=dict)
    native_semantic_model_v1: Dict[str, object] = field(default_factory=dict)
    native_semantic_writer_gate_v1: Dict[str, object] = field(default_factory=dict)
    native_edit_candidate_map_v1: Dict[str, object] = field(default_factory=dict)
    native_hkx_edit_gate_v1: Dict[str, object] = field(default_factory=dict)
    native_class_decoder_evidence_v2: Dict[str, object] = field(default_factory=dict)
    native_decoder_evidence_v2: Dict[str, object] = field(default_factory=dict)
    native_modding_readiness: Dict[str, object] = field(default_factory=dict)
    native_no_edit_binary_writer: Dict[str, object] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


@dataclass(slots=True)
class HkxGeometryPatchResult:
    data: bytes
    changed_fields: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
