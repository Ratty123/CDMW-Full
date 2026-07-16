"""Dependency-free Research data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


REGEX_PRESET_DEFAULT_EXTENSIONS = ".xml;.json;.cfg;.ini;.lua;.material;.shader;.pami"


@dataclass(slots=True)
class DependencyEdge:
    left: str
    right: str
    package_count: int
    example_packages: List[str] = field(default_factory=list)


@dataclass(slots=True)
class TextureClassificationRow:
    path: str
    package_label: str
    texture_type: str
    confidence: int
    reason: str
    group_key: str


@dataclass(slots=True)
class TextureSetMember:
    path: str
    package_label: str
    member_kind: str
    extension: str


@dataclass(slots=True)
class TextureSetGroup:
    group_key: str
    display_name: str
    member_count: int
    package_labels: List[str]
    member_kinds: List[str]
    members: List[TextureSetMember] = field(default_factory=list)


@dataclass(slots=True)
class UnknownResolverSuggestion:
    choice_key: str
    texture_type: str
    semantic_subtype: str
    confidence: int
    reason: str


@dataclass(slots=True)
class UnknownResolverMember:
    path: str
    package_label: str
    current_kind: str
    reason: str
    role_hint: str = ""
    extension: str = ""
    is_unknown: bool = True
    local_texture_type: str = ""
    local_semantic_subtype: str = ""


@dataclass(slots=True)
class UnknownResolverGroup:
    group_key: str
    display_name: str
    unknown_count: int
    total_members: int
    package_labels: List[str]
    known_kinds: List[str]
    sidecar_paths: List[str]
    suggestion_label: str = ""
    members: List[UnknownResolverMember] = field(default_factory=list)
    suggestions: List[UnknownResolverSuggestion] = field(default_factory=list)
    local_approval_state: str = "None"


@dataclass(slots=True)
class RegexPreset:
    category: str
    name: str
    pattern: str
    description: str
    extensions: str = REGEX_PRESET_DEFAULT_EXTENSIONS
    path_hint: str = ""


@dataclass(slots=True)
class SearchCluster:
    mode: str
    label: str
    file_count: int
    total_matches: int
    sample_paths: List[str] = field(default_factory=list)


@dataclass(slots=True)
class MaterialTextureReferenceRow:
    source_path: str
    source_package_label: str
    related_path: str
    related_package_label: str
    relation_kind: str
    match_count: int
    snippet: str
    source_kind: str = ""
    texture_name: str = ""
    filename_token: str = ""
    get_rect_raw: str = ""
    rect_x: int = -1
    rect_y: int = -1
    rect_width: int = 0
    rect_height: int = 0
    texture_width: int = 0
    texture_height: int = 0
    constraint_kind: str = ""
    warning_text: str = ""
    evidence_level: str = ""


@dataclass(slots=True)
class SidecarDiscoveryRow:
    anchor_path: str
    related_path: str
    package_label: str
    relation_kind: str
    confidence: int
    reason: str


@dataclass(slots=True)
class ResearchNote:
    target_key: str
    source_kind: str
    tags: List[str]
    note: str
    updated_at: str


@dataclass(slots=True)
class MipAnalysisRow:
    relative_path: str
    original_format: str
    rebuilt_format: str
    original_size: str
    rebuilt_size: str
    original_mips: int
    rebuilt_mips: int
    warning_count: int
    planner_profile: str = ""
    planner_path_kind: str = ""
    planner_backend_mode: str = ""
    planner_alpha_policy: str = ""
    planner_preserve_reason: str = ""
    warnings: List[str] = field(default_factory=list)


@dataclass(slots=True)
class NormalValidationRow:
    path: str
    root_label: str
    dds_format: str
    size_text: str
    issue_count: int
    root_path: str = ""
    planner_profile: str = ""
    planner_path_kind: str = ""
    planner_backend_mode: str = ""
    planner_alpha_policy: str = ""
    planner_preserve_reason: str = ""
    issues: List[str] = field(default_factory=list)


@dataclass(slots=True)
class AtlasDetectionRow:
    path: str
    root_label: str
    size_text: str
    score: int
    signals: List[str] = field(default_factory=list)


@dataclass(slots=True)
class TexturePreviewStats:
    path: str
    width: int
    height: int
    sample_count: int
    has_alpha: bool
    mean_r: float
    mean_g: float
    mean_b: float
    mean_a: float
    min_r: int
    min_g: int
    min_b: int
    min_a: int
    max_r: int
    max_g: int
    max_b: int
    max_a: int
    luma_mean: float
    luma_min: float
    luma_max: float
    opaque_fraction: float
    transparent_fraction: float


@dataclass(slots=True)
class TextureUsageHeatRow:
    scope: str
    label: str
    texture_count: int
    set_count: int
    normal_count: int
    ui_count: int
    material_count: int
    impostor_count: int
    heat_score: int
    sample_paths: List[str] = field(default_factory=list)


@dataclass(slots=True)
class TextureBudgetRow:
    relative_path: str
    group_key: str
    system_area: str
    folder_bucket: str
    texture_type: str
    planner_profile: str
    planner_path_kind: str
    planner_alpha_policy: str
    original_bytes: int
    rebuilt_bytes: int
    byte_delta: int
    byte_ratio: float
    original_width: int
    original_height: int
    rebuilt_width: int
    rebuilt_height: int
    pixel_ratio: float
    original_mips: int
    rebuilt_mips: int
    mip_delta: int
    original_format: str
    rebuilt_format: str
    format_changed: bool
    changed: bool
    explicit_ui_constraint: bool = False
    ui_constraint_summary: str = ""
    risk_score: int = 0
    risk_band: str = ""
    risk_signals: List[str] = field(default_factory=list)


@dataclass(slots=True)
class TextureBudgetClassSummary:
    texture_type: str
    affected_count: int
    total_byte_delta: int
    average_risk: float
    risk_band: str
    sample_paths: List[str] = field(default_factory=list)


@dataclass(slots=True)
class TextureBudgetGroupSummary:
    group_key: str
    system_area: str
    texture_count: int
    total_original_bytes: int
    total_rebuilt_bytes: int
    total_byte_delta: int
    average_byte_ratio: float
    max_byte_ratio: float
    average_width: float
    average_height: float
    large_2048_count: int
    large_4096_count: int
    average_risk: float
    risk_score: int
    risk_band: str
    signals: List[str] = field(default_factory=list)


@dataclass(slots=True)
class TextureBudgetProfileSummary:
    profile_label: str
    total_original_bytes: int
    total_rebuilt_bytes: int
    total_byte_delta: int
    total_byte_ratio: float
    changed_texture_count: int
    upscaled_texture_count: int
    high_risk_texture_fraction: float
    highest_group_risk: int
    reasons: List[str] = field(default_factory=list)


__all__ = [
    'AtlasDetectionRow',
    'DependencyEdge',
    'MaterialTextureReferenceRow',
    'MipAnalysisRow',
    'NormalValidationRow',
    'RegexPreset',
    'ResearchNote',
    'SearchCluster',
    'SidecarDiscoveryRow',
    'TextureBudgetClassSummary',
    'TextureBudgetGroupSummary',
    'TextureBudgetProfileSummary',
    'TextureBudgetRow',
    'TextureClassificationRow',
    'TexturePreviewStats',
    'TextureSetGroup',
    'TextureSetMember',
    'TextureUsageHeatRow',
    'UnknownResolverGroup',
    'UnknownResolverMember',
    'UnknownResolverSuggestion',
]
