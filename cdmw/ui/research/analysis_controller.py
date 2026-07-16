from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QAbstractItemView, QFileDialog, QTreeWidgetItem

from cdmw.domain.research.contracts import (
    MipAnalysisRow,
    NormalValidationRow,
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
from cdmw.workers.research_analysis_workers import (
    AnalysisDetailResult,
    AnalysisReportExportResult,
    mip_detail_request,
    normal_detail_request,
    report_export_request,
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
        already_current = self.mip_tree.currentItem() is item
        self.mip_tree.setCurrentItem(item)
        self.mip_tree.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        if already_current:
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
        self.analysis_task_controller.cancel_detail()
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
        self.analysis_task_controller.cancel_detail()
        return
    row = item_payload(current, NormalValidationRow)
    if row is None:
        return
    self._show_normal_row_details(row)

def _show_mip_row_details(self, row: MipAnalysisRow) -> None:
    original_root_text = self.get_original_root().strip()
    output_root_text = self.get_output_root().strip()
    self.analysis_detail_label.setText("Mip Analysis details")
    QTimer.singleShot(
        0,
        self.analysis_detail_edit,
        lambda: self.analysis_detail_edit.setPlainText("Loading Mip Analysis details..."),
    )
    family_lookup = self.research_payload.get("mip_detail_family_members_by_path")
    family_members = family_lookup.get(row.relative_path, ()) if isinstance(family_lookup, dict) else ()
    request = mip_detail_request(
        Path(original_root_text).expanduser() if original_root_text else Path("."),
        Path(output_root_text).expanduser() if output_root_text else Path("."),
        row,
        family_members if isinstance(family_members, (list, tuple)) else (),
    )
    self.analysis_task_controller.queue_detail(
        request,
        on_complete=self._apply_analysis_detail_result,
        on_error=self._handle_analysis_detail_error,
    )

def _show_normal_row_details(self, row: NormalValidationRow) -> None:
    self.analysis_detail_label.setText("Bulk Normal Validator details")
    QTimer.singleShot(
        0,
        self.analysis_detail_edit,
        lambda: self.analysis_detail_edit.setPlainText("Loading Bulk Normal Validator details..."),
    )
    root_path = Path(row.root_path).expanduser() if row.root_path else Path(".")
    self.analysis_task_controller.queue_detail(
        normal_detail_request(root_path, row),
        on_complete=self._apply_analysis_detail_result,
        on_error=self._handle_analysis_detail_error,
    )

def _apply_analysis_detail_result(self, result: AnalysisDetailResult) -> None:
    self.analysis_detail_label.setText(
        "Mip Analysis details" if result.kind == "mip" else "Bulk Normal Validator details"
    )
    self.analysis_detail_edit.setPlainText(result.detail_text)

def _handle_analysis_detail_error(self, message: str) -> None:
    status = f"Could not load analysis details: {message}"
    self.analysis_detail_edit.setPlainText(status)
    self.status_message_requested.emit(status, True)

def _show_budget_details(self, row: object) -> None:
    payload = budget_detail_payload(row)
    if payload is None:
        return
    self.analysis_task_controller.cancel_detail()
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
    request = report_export_request(
        report_path,
        mip_rows=report_rows.mip_rows,
        normal_rows=report_rows.normal_rows,
        budget_rows=report_rows.budget_rows,
        budget_class_rows=report_rows.budget_class_rows,
        budget_group_rows=report_rows.budget_group_rows,
        budget_profile=report_rows.budget_profile,
    )
    self.export_report_csv_button.setEnabled(False)
    self.export_report_json_button.setEnabled(False)
    self.analysis_status_label.setText(f"Exporting analysis report to {report_path}...")
    if not self.analysis_task_controller.start_export(
        request,
        on_complete=self._handle_analysis_export_complete,
        on_error=self._handle_analysis_export_error,
        on_idle=self._handle_analysis_export_idle,
    ):
        self._handle_analysis_export_idle()

def _handle_analysis_export_complete(self, result: AnalysisReportExportResult) -> None:
    status_text = analysis_report_exported_status_text(result.output_path)
    self.analysis_status_label.setText(status_text)
    self.status_message_requested.emit(status_text, False)

def _handle_analysis_export_error(self, message: str) -> None:
    self.analysis_status_label.setText(message)
    self.status_message_requested.emit(message, True)

def _handle_analysis_export_idle(self) -> None:
    self.export_report_csv_button.setEnabled(True)
    self.export_report_json_button.setEnabled(True)
