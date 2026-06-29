"""Dependency exports for static replacement prompt owner."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import re
import shutil
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QModelIndex, QObject, QProcess, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QBrush, QColor, QImageReader, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.domain.mesh.validation import format_scene_import_file_size_summary
from cdmw.constants import MODEL_PREVIEW_BACKGROUND_COLOR, MODEL_PREVIEW_TEXT_COLOR
from cdmw.core.archive import (
    _attach_model_sidecar_texture_preview_paths,
    _attach_model_support_texture_preview_paths,
    _attach_model_texture_preview_paths,
    _collect_same_stem_related_target_basenames,
    _extract_archive_model_sidecar_texture_references,
    _infer_model_preview_normal_strength,
    _normalize_model_visible_texture_mode,
    _resolve_model_texture_semantic_details,
    ensure_archive_preview_source,
    read_archive_entry_data,
    try_decode_text_like_archive_data,
)
from cdmw.core.mesh_baseline import read_archive_entry_baseline_data
from cdmw.core.archive_modding import (
    ARCHIVE_MESH_EXTENSIONS,
    MeshImportSupplementalFileSpec,
    attach_scene_preview_textures,
    parsed_mesh_to_preview_model,
)
from cdmw.core.final_package_preview import (
    TEXTURE_PLAN_STATUS_READY,
    TEXTURE_PLAN_STATUS_REVIEW,
    TEXTURE_PLAN_STATUS_SUPPORT_ONLY,
    build_dds_override_table_row,
    build_replacement_texture_plan_rows,
    simplified_part_label,
)
from cdmw.core.item_icon import ItemIconOverrideSpec
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.source_mix import SourceMixCandidate, scan_loose_folder_source, scan_mod_archive_source
from cdmw.models import (
    D3D11_PREVIEW_VIEW_MODE_LABELS,
    D3D11_PREVIEW_VIEW_MODES,
    MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS,
    MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES,
    MODEL_PREVIEW_VISIBLE_TEXTURE_MODE_LABELS,
    MODEL_PREVIEW_VISIBLE_TEXTURE_MODES,
    ArchiveEntry,
    AssetFamilyGraph,
    ModelPreviewData,
    ModelPreviewRenderSettings,
    PreparedModelPreviewData,
    PreviewMaterialParameterInput,
    RunCancelled,
    clamp_model_preview_render_settings,
)
from cdmw.modding.asset_replacement import ReplacementAssetProfile, analyze_replacement_asset, classify_texture_binding
from cdmw.modding.material_replacer import (
    ReplacementTextureSet,
    ReplacementTextureSlot,
    _apply_source_part_role_overrides,
    build_source_material_routing_plan,
    complete_swap_material_profile_to_dict,
    complete_swap_material_runtime_profiles,
    get_complete_swap_material_profile,
    group_replacement_texture_sets,
    is_shared_material_layer_texture,
    material_authority_preview_texture_slots,
    read_complete_swap_calibrated_material_profile,
    replacement_texture_slot_preview_semantics,
    serialize_complete_swap_manual_material_profile,
    write_complete_swap_calibrated_material_profile,
    apply_true_source_basic_controls_to_profile,
)
from cdmw.modding.mesh_deformer import (
    apply_brush_deformation,
    apply_vertex_delta,
    assert_mesh_topology_unchanged,
    build_vertex_adjacency,
    build_x_mirror_pairs,
    clone_mesh_for_editing,
    compact_orphan_vertices,
    delete_faces_by_indices,
    delete_faces_touching_vertices,
    grow_vertex_selection,
    mesh_topology_signature,
    recompute_mesh_normals,
    shrink_vertex_selection,
    smooth_vertex_selection,
    split_faces_to_submesh,
    subdivide_faces_touching_vertices,
)
from cdmw.modding.mesh_morph_sliders import (
    MeshMorphSliderDelta,
    MeshMorphSliderProfile,
    apply_morph_slider_values,
    create_region_volume_slider_profile,
    import_body_slider_profile,
    import_single_morph_slider_profile,
    load_morph_slider_delta,
    load_morph_slider_profiles,
    validate_morph_target,
)
from cdmw.modding.mesh_parser import ParsedMesh, parse_mesh
from cdmw.modding.pac_xml_profiles import default_pac_xml_profile_cache_path
from cdmw.modding.scene_importer import (
    SCENE_IMPORT_EXTENSIONS,
    SCENE_TEXTURE_SOURCE_EXTENSIONS,
    SceneImportResult,
    append_scene_import_to_mesh,
    discover_scene_texture_files,
    flatten_scene_import_result_parts,
    group_scene_import_result_parts_by_material,
    import_scene_mesh,
    import_scene_mesh_with_report,
    reduce_scene_import_result_quality,
    refresh_parsed_mesh_totals,
)
from cdmw.modding.static_mesh_replacer import (
    StaticDonorMaterialPlan,
    StaticIndependentPart,
    StaticMeshReplacementOptions,
    StaticOriginalPartCopy,
    StaticReplacementTransform,
    StaticSourceMaterialTextureOverride,
    StaticSourcePartAdjustment,
    StaticSubmeshMapping,
    StaticTextureSlotOverride,
    StaticTextureUvTransform,
    _compute_anchor_alignment,
    _normalize,
    _rotate_xyz,
    _semantic_tokens,
    _transformed_replacement_sources,
    build_static_replacement_preview_mesh,
    infer_static_replacement_part_role,
    source_delta_for_transformed_delta,
    source_distance_for_transformed_distance,
    source_point_for_transformed_point,
    suggest_static_submesh_mappings,
)
from cdmw.rendering.model_preview_prepare import MeshPreviewCacheSignature, prepare_model_preview
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
from cdmw.rendering.native_preview_core import run_native_preview_core_preview_job
from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame


def install_static_replacement_prompt_base_dependencies(namespace: dict[str, object]) -> None:
    namespace.update(
        {
            name: value
            for name, value in globals().items()
            if not name.startswith("__")
            and name != "install_static_replacement_prompt_base_dependencies"
        }
    )


__all__ = ["install_static_replacement_prompt_base_dependencies"]
