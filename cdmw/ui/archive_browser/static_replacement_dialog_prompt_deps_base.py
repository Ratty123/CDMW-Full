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
from cdmw.services.archive_workflow_service import (
    _attach_model_sidecar_texture_preview_paths,
    _attach_model_support_texture_preview_paths,
    _attach_model_texture_preview_paths,
    _infer_model_preview_normal_strength,
    _resolve_model_texture_semantic_details,
)
from cdmw.services.archive_workflow_service import (
    _collect_same_stem_related_target_basenames,
    _normalize_model_visible_texture_mode,
)
from cdmw.services.archive_query_service import extract_archive_model_sidecar_texture_references as _extract_archive_model_sidecar_texture_references
from cdmw.services.archive_preview_service import (
    build_archive_preview_result,
    ensure_archive_preview_source,
)
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.preview_workflow_service import try_decode_text_like_archive_data
from cdmw.services.mesh_workflow_service import read_archive_entry_baseline_data
from cdmw.services.preview_workflow_service import scene_import_normalizes_texture_v
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.domain.archives.mesh_contracts import MeshImportSupplementalFileSpec
from cdmw.services.preview_workflow_service import (
    attach_scene_preview_textures,
    parsed_mesh_to_preview_model,
)
from cdmw.services.preview_workflow_service import (
    TEXTURE_PLAN_STATUS_READY,
    TEXTURE_PLAN_STATUS_REVIEW,
    TEXTURE_PLAN_STATUS_SUPPORT_ONLY,
    build_dds_override_table_row,
    build_replacement_texture_plan_rows,
    simplified_part_label,
)
from cdmw.domain.library.item_icons import ItemIconOverrideSpec
from cdmw.services.texture_workflow_service import parse_dds
from cdmw.services.preview_workflow_service import ensure_dds_display_preview_png
from cdmw.services.texture_workflow_service import SourceMixCandidate, scan_loose_folder_source, scan_mod_archive_source
from cdmw.models import (
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
from cdmw.services.mesh_workflow_service import ReplacementAssetProfile, analyze_replacement_asset, classify_texture_binding
from cdmw.services.mesh_workflow_service import (
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
from cdmw.services.mesh_workflow_service import (
    assert_mesh_topology_unchanged,
    grow_vertex_selection,
    invert_vertex_selection,
    mesh_topology_signature,
    select_all_vertex_selection,
    shrink_vertex_selection,
    smooth_vertex_selection,
)
from cdmw.services.mesh_workflow_service import (
    MeshMorphSliderDelta,
    MeshMorphSliderProfile,
    apply_morph_slider_values,
    create_region_volume_slider_profile,
    load_morph_slider_delta,
    load_morph_slider_profiles,
    validate_morph_target,
)
from cdmw.services.mesh_workflow_service import ParsedMesh, parse_mesh
from cdmw.services.mesh_workflow_service import default_pac_xml_profile_cache_path
from cdmw.services.mesh_workflow_service import (
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
from cdmw.services.mesh_workflow_service import (
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
    source_affine_for_transformed_preview,
    source_normal_transform_for_transformed_preview,
    suggest_static_submesh_mappings,
)
from cdmw.services.preview_rendering_service import (
    MeshPreviewCacheSignature,
    prepare_model_preview,
    run_native_preview_core_preview_job,
)
from cdmw.ui.preview import DotNetPreviewHostFrame, DotNetPreviewProfile


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
