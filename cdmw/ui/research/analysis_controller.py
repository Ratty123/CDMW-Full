from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QAbstractItemView, QFileDialog, QTreeWidgetItem

from cdmw.core.research import (
    MipAnalysisRow,
    NormalValidationRow,
    build_mip_analysis_detail,
    build_normal_validation_detail,
    export_texture_analysis_report,
)
from cdmw.ui.research.analysis_state import (
    analysis_report_default_name,
    analysis_report_exported_status_text,
    analysis_report_missing_status_text,
    analysis_report_output_path,
    budget_detail_payload,
    missing_mip_focus_state,
    research_analysis_report_rows,
    texture_analysis_context_text,
)
from cdmw.ui.research.help_widgets import set_help_button_text as _set_help_button_text
from cdmw.ui.research.models import item_payload, item_user_role
from cdmw.ui.research.reference_payload_state import normalize_relative_path
from cdmw.ui.research.tree_population import (
    populate_research_heatmap_tree,
    populate_research_mip_tree,
    populate_research_normal_tree,
)

def _populate_heatmap_rows(self, rows: object) -> None:
    populate_research_heatmap_tree(self.heatmap_tree, rows)

def _populate_mip_rows(self, rows: object) -> None:
    populate_research_mip_tree(self.mip_tree, rows)

def _populate_normal_rows(self, rows: object) -> None:
    populate_research_normal_tree(
        self.normal_tree,
        rows,
        select_first=self.mip_tree.topLevelItemCount() == 0,
    )
    if self.normal_tree.topLevelItemCount() == 0 and self.mip_tree.topLevelItemCount() == 0:
        self.analysis_detail_label.setText(
            "Select a row in Mip Analysis or Bulk Normal Validator to see where the result came from and what it means."
        )
        self.analysis_detail_edit.clear()

def _focus_pending_mip_row(self) -> bool:
    target_path = normalize_relative_path(self.pending_mip_focus_relative_path)
    if not target_path:
        return False
    target_key = target_path.casefold()
    self.tab_widget.setCurrentWidget(self.texture_tab)
    self.right_panel_stack.setCurrentWidget(self.analysis_detail_group)
    for row_index in range(self.mip_tree.topLevelItemCount()):
        item = self.mip_tree.topLevelItem(row_index)
        if item is None:
            continue
        row = item_payload(item, MipAnalysisRow)
        if row is None:
            continue
        row_key = normalize_relative_path(row.relative_path).casefold()
        if row_key != target_key:
            continue
        self.pending_mip_focus_relative_path = ""
        self.mip_tree.setCurrentItem(item)
        self.mip_tree.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        self._show_mip_row_details(row)
        self.analysis_status_label.setText(f"Showing Mip Analysis details for {target_path}.")
        self.status_message_requested.emit(f"Showing Mip Analysis details for {target_path}.", False)
        return True
    self.pending_mip_focus_relative_path = ""
    missing_state = missing_mip_focus_state(target_path)
    self.analysis_status_label.setText(missing_state.status_text)
    self.analysis_detail_label.setText(missing_state.detail_label)
    self.analysis_detail_edit.setPlainText(missing_state.detail_text)
    self.status_message_requested.emit(missing_state.user_status_text, True)
    return False

def _refresh_texture_analysis_summary(self) -> None:
    analysis_context = texture_analysis_context_text(
        original_root_text=self.get_original_root(),
        output_root_text=self.get_output_root(),
        research_payload=self.research_payload,
    )
    self.analysis_context_label.setText(analysis_context)
    if hasattr(self, "analysis_context_help_button"):
        _set_help_button_text(self.analysis_context_help_button, analysis_context)

def _handle_mip_selection_changed(
    self,
    current: Optional[QTreeWidgetItem],
    _previous: Optional[QTreeWidgetItem],
) -> None:
    if current is None:
        return
    row = item_payload(current, MipAnalysisRow)
    if row is None:
        return
    self._show_mip_row_details(row)

def _handle_normal_selection_changed(
    self,
    current: Optional[QTreeWidgetItem],
    _previous: Optional[QTreeWidgetItem],
) -> None:
    if current is None:
        return
    row = item_payload(current, NormalValidationRow)
    if row is None:
        return
    self._show_normal_row_details(row)

def _show_mip_row_details(self, row: MipAnalysisRow) -> None:
    original_root_text = self.get_original_root().strip()
    output_root_text = self.get_output_root().strip()
    self.analysis_detail_label.setText("Mip Analysis details")
    texconv_path = Path(self.get_texconv_path()).expanduser() if self.get_texconv_path().strip() else None
    detail_text = build_mip_analysis_detail(
        Path(original_root_text).expanduser() if original_root_text else Path("."),
        Path(output_root_text).expanduser() if output_root_text else Path("."),
        row,
        texconv_path=texconv_path,
        family_members_by_path=self.research_payload.get("mip_detail_family_members_by_path")
        if isinstance(self.research_payload.get("mip_detail_family_members_by_path"), dict)
        else None,
    )
    self.analysis_detail_edit.setPlainText(detail_text)

def _show_normal_row_details(self, row: NormalValidationRow) -> None:
    self.analysis_detail_label.setText("Bulk Normal Validator details")
    texconv_path = Path(self.get_texconv_path()).expanduser() if self.get_texconv_path().strip() else None
    root_path = Path(row.root_path).expanduser() if row.root_path else Path(".")
    detail_text = build_normal_validation_detail(root_path, row, texconv_path=texconv_path)
    self.analysis_detail_edit.setPlainText(detail_text)

def _show_budget_details(self, row: object) -> None:
    payload = budget_detail_payload(row)
    if payload is None:
        return
    label_text, detail_text = payload
    self.analysis_detail_label.setText(label_text)
    self.analysis_detail_edit.setPlainText(detail_text)

def _handle_budget_selection_changed(
    self,
    current: Optional[QTreeWidgetItem],
    _previous: Optional[QTreeWidgetItem],
) -> None:
    if current is None:
        return
    self._show_budget_details(item_user_role(current))

def _export_analysis_report(self, default_suffix: str) -> None:
    report_rows = research_analysis_report_rows(self.research_payload)
    if report_rows is None:
        self.status_message_requested.emit(analysis_report_missing_status_text(), True)
        return
    default_name = analysis_report_default_name(default_suffix)
    selected_path, _selected_filter = QFileDialog.getSaveFileName(
        self,
        "Export Texture Analysis Report",
        str(self.base_dir / default_name),
        "JSON report (*.json);;CSV report (*.csv)",
    )
    report_path = analysis_report_output_path(selected_path, default_suffix)
    if report_path is None:
        return
    try:
        final_path = export_texture_analysis_report(
            report_path,
            report_rows.mip_rows,
            report_rows.normal_rows,
            budget_rows=report_rows.budget_rows,
            budget_class_rows=report_rows.budget_class_rows,
            budget_group_rows=report_rows.budget_group_rows,
            budget_profile=report_rows.budget_profile,
        )
        status_text = analysis_report_exported_status_text(final_path)
        self.analysis_status_label.setText(status_text)
        self.status_message_requested.emit(status_text, False)
    except Exception as exc:
        self.analysis_status_label.setText(str(exc))
        self.status_message_requested.emit(str(exc), True)
