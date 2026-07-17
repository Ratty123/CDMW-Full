"""Composition and refresh boundary for structured PAC XML editor tabs."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Mapping, Sequence

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTabWidget,
    QTreeWidgetItem,
    QWidget,
)

from cdmw.domain.pac_xml_editor import PacXmlDocument, PacXmlSourceFormat, parse_pac_xml_document
from cdmw.domain.pac_xml_graph import build_pac_xml_connection_graph
from cdmw.ui.archive_browser.pac_xml_editor_graph_view import PacXmlConnectionGraphView
from cdmw.ui.archive_browser.pac_xml_editor_parameters import PacXmlParameterPanel, PacXmlParameterRow
from cdmw.ui.archive_browser.pac_xml_editor_source_view import PacXmlSourceChangesView
from cdmw.ui.archive_browser.material_sidecar_editor_helpers import (
    material_editor_color_from_value,
    material_sidecar_preview_color_tooltip,
    material_value_swatch_icon,
)
from cdmw.ui.widgets import make_tree_columns_persistent


@dataclass(frozen=True, slots=True)
class PacXmlEditorViews:
    tabs: QTabWidget
    parameters: PacXmlParameterPanel
    connections: PacXmlConnectionGraphView
    source_changes: PacXmlSourceChangesView
    selected_detail_label: QLabel
    selected_swatch: QFrame


@dataclass(frozen=True, slots=True)
class PacXmlEditorRefreshResult:
    valid: bool
    changed_count: int = 0
    error: str = ""


def build_pac_xml_editor_views(
    rows: Sequence[PacXmlParameterRow],
    original_text: str,
    *,
    is_pac_xml: bool,
) -> PacXmlEditorViews:
    tabs = QTabWidget()
    tabs.setObjectName("PacXmlEditorTabs")
    parameters = PacXmlParameterPanel(rows)
    source_changes = PacXmlSourceChangesView(original_text)
    connections = PacXmlConnectionGraphView()
    selected_detail_label = QLabel("")
    selected_detail_label.setObjectName("HintLabel")
    selected_detail_label.setWordWrap(True)
    selected_swatch = QFrame()
    selected_swatch.setObjectName("SelectedMaterialValueColorSwatch")
    selected_swatch.setFixedSize(28, 28)
    footer = QHBoxLayout()
    footer.addWidget(selected_detail_label, 1)
    footer.addWidget(selected_swatch)
    parameters.layout().addLayout(footer)
    tabs.addTab(parameters, "Parameters")
    if is_pac_xml:
        tabs.addTab(connections, "Connections")
    tabs.addTab(source_changes, "Source && Changes")
    return PacXmlEditorViews(
        tabs=tabs,
        parameters=parameters,
        connections=connections,
        source_changes=source_changes,
        selected_detail_label=selected_detail_label,
        selected_swatch=selected_swatch,
    )


def refresh_pac_xml_editor_views(
    *,
    parsed_document: PacXmlDocument,
    source_format: PacXmlSourceFormat,
    edited_values: Mapping[str, str],
    root_path: str,
    model_path: str = "",
    model_entry: object = None,
    normalized_path_index: Mapping[str, object] | None = None,
    basename_index: Mapping[str, Sequence[object]] | None = None,
    family_graph: object = None,
    index_warming: bool = False,
    include_connections: bool = True,
    source_view: PacXmlSourceChangesView,
    connection_view: PacXmlConnectionGraphView,
) -> PacXmlEditorRefreshResult:
    try:
        rendered = parsed_document.render(edited_values)
        patched_document = parse_pac_xml_document(
            rendered.text,
            source_format=source_format,
            original_payload=rendered.payload,
        )
    except ValueError as exc:
        source_view.show_validation_error(exc)
        return PacXmlEditorRefreshResult(False, error=str(exc))
    newline_label = {"\r\n": "CRLF", "\r": "CR", "\n": "LF"}.get(source_format.newline, "mixed")
    source_view.set_patched_source(
        rendered.text,
        changed_count=len(rendered.changed_rows),
        validation_text=(
            f"{len(rendered.changed_rows)} changed parameter(s). Structural validation passed. "
            f"Source bytes: {source_format.encoding}, {'BOM' if source_format.bom else 'no BOM'}, {newline_label}."
        ),
    )
    if not include_connections:
        return PacXmlEditorRefreshResult(True, len(rendered.changed_rows))
    normalized_root = str(root_path or "").replace("\\", "/").casefold()
    family_root = str(getattr(family_graph, "root_path", "") or "").replace("\\", "/").casefold()
    family_members = tuple(getattr(family_graph, "member_rows", ()) or ()) if family_root == normalized_root else ()
    graph = build_pac_xml_connection_graph(
        patched_document,
        root_path=root_path,
        model_paths=(model_path,) if model_path else (),
        model_entries=(model_entry,) if model_entry is not None else (),
        archive_entries_by_normalized_path=normalized_path_index,
        archive_entries_by_basename=basename_index,
        family_members=family_members,
        index_warming=index_warming,
    )
    connection_view.set_graph(graph)
    return PacXmlEditorRefreshResult(True, len(rendered.changed_rows))


def configure_pac_xml_parameter_tree(
    panel: PacXmlParameterPanel,
    *,
    settings: object,
    save_callback: Callable[[], None],
) -> Callable[[QTreeWidgetItem | None], None]:
    tree = panel.tree
    tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    swatch_icons: dict[str, QIcon] = {}

    def update_swatch(item: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        blocker = QSignalBlocker(tree)
        try:
            if item.text(1).strip().casefold() != "color":
                item.setIcon(3, QIcon())
                return
            color = material_editor_color_from_value(item.text(3))
            if color is None:
                item.setIcon(3, QIcon())
                item.setToolTip(3, item.text(3))
                return
            item.setIcon(3, material_value_swatch_icon(color, swatch_icons))
            item.setToolTip(3, material_sidecar_preview_color_tooltip(item.text(3), color.name()))
        finally:
            del blocker

    for item in panel.row_items.values():
        update_swatch(item)
    header = tree.header()
    header.setStretchLastSection(False)
    for section, mode in enumerate(
        (
            QHeaderView.Interactive,
            QHeaderView.ResizeToContents,
            QHeaderView.Interactive,
            QHeaderView.Interactive,
            QHeaderView.ResizeToContents,
            QHeaderView.Stretch,
        )
    ):
        header.setSectionResizeMode(section, mode)
    make_tree_columns_persistent(
        tree,
        settings,
        "dialog/pac_xml_parameter_values",
        minimum_width=56,
        save_callback=save_callback,
    )
    return update_swatch


def confirm_pac_xml_export_risks(
    parent: QWidget | None,
    *,
    edited_values: Mapping[str, str],
    rows_by_id: Mapping[str, PacXmlParameterRow],
    unresolved_count: int,
) -> bool:
    warning_lines: list[str] = []
    risky_count = sum(
        1
        for row_id in edited_values
        if row_id in rows_by_id and rows_by_id[row_id].risk
    )
    if risky_count:
        warning_lines.append(
            f"{risky_count} edited value(s) affect runtime flags or masks and require in-game review."
        )
    if unresolved_count:
        warning_lines.append(
            f"{unresolved_count} referenced asset path(s) are unresolved in the current archive indexes."
        )
    if not warning_lines:
        return True
    answer = QMessageBox.question(
        parent,
        "PAC XML Export Review",
        "\n".join(warning_lines)
        + "\n\nThe XML structure is valid, but these runtime relationships cannot be proven. Continue to mod-package export?",
        QMessageBox.Yes | QMessageBox.Cancel,
        QMessageBox.Cancel,
    )
    return answer == QMessageBox.Yes


__all__ = [
    "PacXmlEditorRefreshResult",
    "PacXmlEditorViews",
    "build_pac_xml_editor_views",
    "configure_pac_xml_parameter_tree",
    "confirm_pac_xml_export_risks",
    "refresh_pac_xml_editor_views",
]
