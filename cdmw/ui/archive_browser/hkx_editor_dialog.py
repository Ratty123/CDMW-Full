"""HKX editor dialog for archive browser entries."""
from __future__ import annotations
import dataclasses
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from cdmw.services.archive_workflow_service import parse_socket_bone_data_xml
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.services.hkx_edit_service import apply_hkx_editable_geometry_xml
from cdmw.domain.xml_text import decode_xml_text_payload
from cdmw.models import (
    ArchiveEntry,
    ArchivePreviewResult,
    AssetFamilyGraph,
    AttachmentPlacementEvidence,
    AttachmentSocketInfo,
    HkxPhysicsOverlayData,
    HkxPhysicsOverlayShape,
    ModelPreviewData,
)
from cdmw.services.hkx_embedded_preview_service import HkxEmbeddedPreviewRequest, build_hkx_embedded_preview
from cdmw.ui.archive_browser.hkx_editor_dialog_helpers import (
    browser_data_viewer_id as _browser_data_viewer_id,
    browser_viewer_id_aliases as _browser_viewer_id_aliases,
    collision_context_by_shape_index as _collision_context_by_shape_index,
    collision_shape_by_index as _collision_shape_by_index,
    connected_detail_lines_from_mapping as _connected_detail_lines_from_mapping_helper,
    connected_node_label as _connected_node_label,
    connected_node_lookup as _connected_node_lookup,
    connected_risk_bucket as _connected_risk_bucket,
    connected_row_text_matches_target as _connected_row_text_matches_target,
    connected_target_filter_aliases as _connected_target_filter_aliases,
    connected_value_text as _connected_value_text,
    filter_terms as _filter_terms,
    format_hkx_display_value as _format_hkx_display_value,
    friendly_hkx_value_meaning as _friendly_hkx_value_meaning,
    has_preview_link_hint as _has_preview_link_hint,
    hkx_confidence_color as _hkx_confidence_color,
    hkx_numeric_text_kind as _hkx_numeric_text_kind,
    hkx_preview_context_skeleton_note as _hkx_preview_context_skeleton_note,
    hkx_preview_counts as _hkx_preview_counts,
    hkx_preview_target_ids_from_model as _helper_hkx_preview_target_ids_from_model,
    hkx_status_display as _hkx_status_display,
    normalize_hkx_viewer_id_text as _normalize_hkx_viewer_id_text,
    overlay_shape_position as _helper_overlay_shape_position,
    overlay_target_position_from_model as _helper_overlay_target_position_from_model,
    previewable_viewer_id as _previewable_viewer_id,
    record_indices_from_data as _record_indices_from_data,
    row_matches_filter_terms as _row_matches_filter_terms,
    viewer_ids_from_text as _viewer_ids_from_text,
    workflow_catalog_counts as _workflow_catalog_counts,
    workflow_detail_lines as _workflow_detail_lines,
    workspace_group_for_row as _workspace_group_for_row,
    workspace_group_sort_key as _workspace_group_sort_key,
    workspace_task_label_for_key as _workspace_task_label_for_key,
)
from cdmw.ui.archive_browser.hkx_related_models import (
    hkx_related_model_candidate_rows as _rank_hkx_related_model_candidate_rows,
)
from cdmw.ui.archive_browser.hkx_xml_export_controller import start_hkx_editor_xml_export
from cdmw.ui.archive_browser.hkx_xml_highlighter import HkxXmlHighlighter
from cdmw.ui.shell.theme_controller import build_monospace_font
from cdmw.ui.widgets import NativePreviewPanel
from cdmw.ui.archive_browser.hkx_editor_dialog_owners import DIALOG_STEPS
from cdmw.ui.archive_browser.hkx_editor_dialog_runtime import run_hkx_editor_dialog


class ArchiveHkxEditorDialogMixin:
    """HKX editor dialog and related preview wiring."""

    def _open_archive_hkx_editor_dialog(self, entry: ArchiveEntry, document_text: str, *, initial_section: str = "") -> None:
        run_hkx_editor_dialog(self, entry, document_text, initial_section, globals(), DIALOG_STEPS)


__all__ = ["ArchiveHkxEditorDialogMixin"]
