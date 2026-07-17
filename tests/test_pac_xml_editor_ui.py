from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from cdmw.core.material_sidecar_editor import discover_material_sidecar_values
from cdmw.domain.pac_xml_editor import parse_pac_xml_document
from cdmw.domain.pac_xml_graph import build_pac_xml_connection_graph
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.pac_xml_editor_dialog_shell import PacXmlEditorDialog
from cdmw.ui.archive_browser.pac_xml_editor_graph_view import PacXmlConnectionGraphView
from cdmw.ui.archive_browser.pac_xml_editor_parameters import (
    PacXmlParameterPanel,
    byte4_channels,
    byte4_raw_value,
)
from cdmw.ui.archive_browser.pac_xml_editor_source_view import PacXmlSourceChangesView


XML = """
<SkinnedMeshMaterialWrapper _subMeshName="body">
  <Material _materialName="BodyShader">
    <MaterialParameterByte4 _name="_channels" _value="305419896" />
    <MaterialParameterBitFlag32 _name="_flags" _value="7" />
    <MaterialParameterBool _name="_enabled" _value="true" />
    <MaterialParameterInt _name="_signed" _value="-3" />
    <MaterialParameterUint _name="_unsigned" _value="4294967295" />
    <MaterialParameterColor _name="_tint" _value="#804020ff" />
    <MaterialParameterFloat3 _name="_direction" _value="1 2 3" />
    <MaterialParameterFloat _name="_absent" />
    <MaterialParameterMystery _name="_unknown" _value="opaque" />
    <MaterialParameterTexture _name="_base"><ResourceReferencePath_ITexture _path="character/texture/body.dds" /></MaterialParameterTexture>
  </Material>
</SkinnedMeshMaterialWrapper>
<SkinnedMeshMaterialWrapper _subMeshName="trim">
  <Material _materialName="TrimShader">
    <MaterialParameterFloat _name="_roughness" _value="0.5" />
  </Material>
</SkinnedMeshMaterialWrapper>
"""


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _panel() -> PacXmlParameterPanel:
    _app()
    return PacXmlParameterPanel(discover_material_sidecar_values(XML))


def test_parameter_tree_is_hierarchical_and_filters_by_search_part_type_and_changed() -> None:
    panel = _panel()

    assert panel.tree.topLevelItemCount() == 2
    assert panel.tree.topLevelItem(0).text(0) == "body"
    assert panel.tree.topLevelItem(0).childCount() == 10

    panel.search_edit.setText("roughness")
    assert panel.tree.topLevelItem(0).isHidden()
    assert not panel.tree.topLevelItem(1).isHidden()
    panel.search_edit.clear()
    panel.part_filter.setCurrentText("body")
    assert not panel.tree.topLevelItem(0).isHidden()
    assert panel.tree.topLevelItem(1).isHidden()
    panel.part_filter.setCurrentText("All parts")
    panel.type_filter.setCurrentText("Float")
    visible = [
        item
        for item in panel.row_items.values()
        if not item.isHidden()
    ]
    assert {item.text(5) for item in visible} == {"_absent", "_roughness"}

    roughness = next(row for row in panel.rows if row.parameter_name == "_roughness")
    panel.set_row_value(roughness.row_id, "0.8")
    panel.type_filter.setCurrentText("All types")
    panel.changed_filter.setChecked(True)
    assert [item.text(5) for item in panel.row_items.values() if not item.isHidden()] == ["_roughness"]
    panel.deleteLater()


def test_typed_byte4_bitfield_bool_and_vector_controls_update_exact_raw_values() -> None:
    panel = _panel()

    byte_row = next(row for row in panel.rows if row.kind == "byte4")
    panel.select_row(byte_row.row_id)
    assert tuple(spin.value() for spin in panel.inspector.byte_spins) == byte4_channels(byte_row.value)
    panel.inspector.byte_spins[0].setValue(1)
    assert int(panel.edited_values()[byte_row.row_id], 0) == byte4_raw_value((1, 0x56, 0x34, 0x12))

    bit_row = next(row for row in panel.rows if row.kind == "bitflag32")
    panel.select_row(bit_row.row_id)
    panel.inspector.bit_checkboxes[31].setChecked(True)
    assert int(panel.edited_values()[bit_row.row_id], 0) == 0x80000007

    bool_row = next(row for row in panel.rows if row.kind == "bool")
    panel.select_row(bool_row.row_id)
    panel.inspector.bool_checkbox.setChecked(False)
    assert panel.edited_values()[bool_row.row_id] == "false"

    unsigned_row = next(row for row in panel.rows if row.kind == "uint")
    panel.select_row(unsigned_row.row_id)
    assert int(panel.inspector.integer_spin.value()) == 0xFFFFFFFF
    panel.inspector.integer_spin.setValue(32)
    assert panel.edited_values()[unsigned_row.row_id] == "32"

    vector_row = next(row for row in panel.rows if row.kind == "float3")
    panel.select_row(vector_row.row_id)
    panel.inspector.vector_spins[1].setValue(9.0)
    assert panel.edited_values()[vector_row.row_id] == "1 9 3"

    color_row = next(row for row in panel.rows if row.kind == "color")
    panel.select_row(color_row.row_id)
    assert round(panel.inspector.vector_spins[0].value(), 3) == round(0x80 / 255.0, 3)
    panel.inspector.vector_spins[2].setValue(1.0)
    assert panel.edited_values()[color_row.row_id].split()[-1] == "1"
    panel.deleteLater()


def test_undo_redo_reset_all_and_absent_restore_are_interactive() -> None:
    panel = _panel()
    roughness = next(row for row in panel.rows if row.parameter_name == "_roughness")

    panel.set_row_value(roughness.row_id, "0.75")
    assert panel.undo_button.isEnabled()
    panel.undo()
    assert roughness.row_id not in panel.edited_values()
    panel.redo()
    assert panel.edited_values()[roughness.row_id] == "0.75"

    absent = next(row for row in panel.rows if row.parameter_name == "_absent")
    panel.select_row(absent.row_id)
    assert panel.inspector.absent_value_button.isVisibleTo(panel.inspector)
    panel.inspector.absent_value_button.click()
    assert panel.edited_values()[absent.row_id] == "0"
    panel.inspector.absent_value_button.click()
    assert absent.row_id not in panel.edited_values()

    panel.reset_all()
    assert panel.edited_values() == {}
    unknown = next(row for row in panel.rows if row.parameter_name == "_unknown")
    panel.select_row(unknown.row_id)
    assert panel.inspector.raw_edit.isReadOnly()
    panel.deleteLater()


def test_graph_edge_locates_parameter_and_resolved_node_requests_preview() -> None:
    _app()
    document = parse_pac_xml_document(XML)
    texture = ArchiveEntry("character/texture/body.dds", Path("0.pamt"), Path("0.paz"), 1, 1, 1, 0, 0)
    graph = build_pac_xml_connection_graph(
        document,
        root_path="character/modelproperty/body.pac_xml",
        archive_entries_by_normalized_path={texture.path.casefold(): (texture,)},
    )
    view = PacXmlConnectionGraphView()
    view.set_graph(graph)
    requested_rows: list[str] = []
    previews: list[object] = []
    view.parameterRequested.connect(requested_rows.append)
    view.entryPreviewRequested.connect(previews.append)
    texture_field = next(field for field in document.fields if field.kind == "texture")

    view.select_parameter_edge(texture_field.row_id)
    _app().processEvents()
    assert requested_rows == [texture_field.row_id]

    texture_node = next(node for node in graph.nodes if node.kind == "texture")
    view.list_tree.setCurrentItem(view._list_items[texture_node.node_id])
    view._preview_list_item(view._list_items[texture_node.node_id])
    assert previews == [texture]
    view.deleteLater()


def test_source_changes_views_are_read_only_diffable_and_jumpable() -> None:
    _app()
    view = PacXmlSourceChangesView(XML)
    patched = XML.replace('_value="0.5"', '_value="0.75"')
    view.set_patched_source(patched, changed_count=1)

    assert view.original_edit.isReadOnly()
    assert view.patched_edit.isReadOnly()
    assert view.diff_edit.isReadOnly()
    assert "-    <MaterialParameterFloat" in view.diff_edit.toPlainText()
    assert "+    <MaterialParameterFloat" in view.diff_edit.toPlainText()
    view.jump_to_line(3)
    assert view.original_edit.textCursor().blockNumber() == 2
    view.deleteLater()


def test_dirty_close_requires_discard_and_exported_state_can_close(monkeypatch) -> None:
    _app()
    dialog = PacXmlEditorDialog()
    dirty = {"value": True}
    dialog.set_unexported_changes_callback(lambda: dirty["value"])
    answers = iter((QMessageBox.Cancel, QMessageBox.Discard))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: next(answers))

    dialog.accept()
    assert dialog.result() == QDialog.Rejected
    dialog.accept()
    assert dialog.result() == QDialog.Accepted

    clean = PacXmlEditorDialog()
    clean.set_unexported_changes_callback(lambda: False)
    clean.accept()
    assert clean.result() == QDialog.Accepted


def test_compatibility_facade_wires_three_tabs_validation_graph_preview_and_original_bytes() -> None:
    source = Path("cdmw/ui/archive_browser/material_sidecar_editor_dialog.py").read_text(encoding="utf-8")
    composition = Path("cdmw/ui/archive_browser/pac_xml_editor_composition.py").read_text(encoding="utf-8")

    assert 'tabs.addTab(parameters, "Parameters")' in composition
    assert 'tabs.addTab(connections, "Connections")' in composition
    assert 'tabs.addTab(source_changes, "Source && Changes")' in composition
    assert "rendered = parsed_document.render(edited_values)" in composition
    assert "export_button.setEnabled(refresh_result.valid and bool(refresh_result.changed_count))" in source
    assert "connection_graph_view.entryPreviewRequested.connect" in source
    assert "self._open_archive_reference_preview_entry(resolved_entry)" in source
    assert "original_payload=document.original_payload" in source
    assert "edited_payload=preparation.edit_result.payload or None" in source
    assert "task_accepts_cancel=True" in source
