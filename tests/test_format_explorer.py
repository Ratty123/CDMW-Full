from __future__ import annotations

import json
import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.content_capabilities import capability_for, load_capabilities
from cdmw.domain.mesh import authoring_capability as mesh_policy
from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS
from tools.format_explorer import catalogue
from tools.format_explorer.tab import FormatExplorerTab, _TOOL_KEYS
from tools.format_explorer.workflows import FormatOperation, FormatWorkflow


@pytest.fixture
def rows():
    return catalogue.load_rows()


@pytest.fixture
def panel():
    app = QApplication.instance() or QApplication([])
    calls = []
    widget = FormatExplorerTab(activate_tool=calls.append)
    yield widget, calls
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _select(widget, extension):
    index = next(index for index, row in enumerate(widget._shown) if row.extension == extension)
    widget.table.selectRow(index)
    widget._on_selected()
    return index


def test_archive_inventory_is_preserved_and_package_count_does_not_apply(rows):
    manifest = json.loads(catalogue.MANIFEST.read_text(encoding="utf-8"))
    archived = {entry["extension"]: entry for entry in manifest["extensions"]}
    displayed = {row.extension: row for row in rows}
    assert len(rows) == len(displayed) == len(archived) + 1
    assert len(catalogue.filter_rows(rows)) == 87
    for extension, entry in archived.items():
        row = displayed[extension]
        assert (row.files, row.decode, row.write) == (
            entry["archive_files"], entry["decode"], entry["write"],
        )
    package = displayed[".cditem"]
    assert package.files is None
    assert not package.shipped
    assert displayed[".glb"].files == 0
    assert capability_for(".cditem") is None
    assert {cap.extension for cap in load_capabilities()} == archived.keys()
    from tools.report_format_decode_progress import summarize
    progress = summarize(manifest["extensions"])
    assert progress["headline"]["all_formats"]["extensions"] == len(archived) == 141


@pytest.mark.parametrize("include_other,editable,expected", [
    (False, False, 87), (False, True, 38), (True, False, 142), (True, True, 60),
])
def test_presence_and_editing_filters_are_independent(rows, include_other, editable, expected):
    found = catalogue.filter_rows(rows, shipped_only=not include_other, editable_only=editable)
    extensions = {row.extension for row in found}
    assert len(found) == expected
    assert (".glb" in extensions) is include_other
    assert (".cditem" in extensions) is (include_other and not editable)
    assert ".paseq" in extensions
    if editable:
        assert ".levelinfo" not in extensions


def test_import_export_and_package_support_alone_do_not_qualify_for_editing(rows):
    original = next(row for row in rows if row.extension == ".obj")
    synthetic = tuple(
        replace(
            original, extension=f".{kind}_only",
            workflow=FormatWorkflow(
                operations=(FormatOperation(kind, "A supported operation"),),
                editable=False,
            ),
        )
        for kind in ("import", "export", "package")
    )
    assert catalogue.filter_rows(synthetic, shipped_only=False, editable_only=True) == ()
    assert len(catalogue.filter_rows(synthetic, shipped_only=False)) == 3


def test_mesh_limits_and_interchange_operations_match_current_policy(rows):
    by_ext = {row.extension: row for row in rows}
    for extension in (".pac", ".pam", ".pamlod"):
        row = by_ext[extension]
        assert row.write_label == "Limited edits"
        assert row.moddable
        assert mesh_policy.geometry_authoring_capability(extension, lod_index=1).reason in " ".join(row.workflow.limits)
        assert mesh_policy.action_authoring_capability("extrude", mesh_format=extension).reason in row.workflow.limits
        assert row.remaining
    fbx = by_ext[".fbx"]
    assert fbx.decode == "none"  # Archive research is not external conversion.
    assert fbx.read_label == "Via Blender"
    assert "Configure Blender" in fbx.workflow.prerequisites
    assert {"import", "edit", "export"} == {op.kind for op in fbx.workflow.operations}
    for extension in (".dae", ".gltf"):
        row = by_ext[extension]
        assert {op.kind for op in row.workflow.operations} == {"import", "edit"}
        assert "same-format export" in " ".join(row.workflow.limits)
        assert "OBJ" in " ".join(row.workflow.limits)
        assert row.write_label == "Edit after import; OBJ output"


def test_package_describes_admission_and_output_without_claiming_general_editing(rows):
    row = next(row for row in rows if row.extension == ".cditem")
    assert not row.moddable
    assert {op.kind for op in row.workflow.operations} == {"inspect", "package", "import"}
    notes = " ".join(row.workflow.limits)
    assert "Experimental" in notes and "writes v1" in notes and "supported v2" in notes
    assert "Unknown package versions" in notes and "refused" in notes
    assert "Mods" in row.workflow.prerequisites
    from cdmw.services.independent_item_package import VERSION, _package
    from cdmw.domain.new_item.independent import IndependentItemError
    assert VERSION == 1
    with pytest.raises(IndependentItemError, match="Unsupported"):
        _package({"version": 3}, {})


def test_workflow_routes_use_registered_tools_and_state_prerequisites(rows):
    registered = {spec.key for spec in COMPACT_TOOL_SPECS}
    for row in rows:
        for segment in row.tool.split(" > "):
            for label in segment.split(" / "):
                target = _TOOL_KEYS.get(label)
                if target is not None:
                    assert target in registered
    for extension in (".paseq", ".paseqc", ".pastage", ".pabgh"):
        row = next(row for row in rows if row.extension == extension)
        assert row.tool == "Browse Archives > Edit Structured Data Safely..."
        assert "select a file" in row.workflow.prerequisites
        assert row.write == "constrained"
    for extension in (".pae", ".paem"):
        row = next(row for row in rows if row.extension == extension)
        assert row.tool == "Create New Item > Effects"
        assert "template" in row.workflow.prerequisites
    for extension in (".pac_xml", ".pami"):
        row = next(row for row in rows if row.extension == extension)
        assert row.tool == catalogue._TEXT_TOOL


def test_search_covers_operation_prerequisites_and_area_filter(rows):
    found = catalogue.filter_rows(rows, "configure blender", shipped_only=False)
    assert {row.extension for row in found} == {".fbx"}
    packages = catalogue.filter_rows(rows, group="application_packages", shipped_only=False)
    assert [row.extension for row in packages] == [".cditem"]


def test_panel_refreshes_details_keeps_selection_and_clears_empty_results(panel):
    widget, _calls = panel
    widget.search_box.setText(".paloc")
    _select(widget, ".paloc")
    assert "PALOC" in widget.detail.toPlainText()
    widget.search_box.setText(".paseq")
    _select(widget, ".paseq")
    text = widget.detail.toPlainText()
    assert "fixed-size" in text and "PALOC language table" not in text
    widget.include_absent.setChecked(True)
    assert widget.selected_row().extension == ".paseq"
    widget.search_box.setText("___no_format_matches_this___")
    assert widget.table.rowCount() == 0
    assert widget.selected_row() is None
    assert widget.detail.toPlainText() == "Nothing matches that filter."


def test_panel_shows_package_provenance_and_routes_table_and_detail_links(panel):
    widget, calls = panel
    widget.include_absent.setChecked(True)
    widget.search_box.setText(".cditem")
    index = _select(widget, ".cditem")
    assert widget.table.item(index, 1).text() == "N/A"
    assert "archive count does not apply" in widget.detail.toPlainText()
    assert "stored archive inventory" in widget.headline_label.text()
    label = widget.table.cellWidget(index, 5)
    assert "Mods" in label.toolTip()
    label.linkActivated.emit("cdmw-tool:mod_management")
    widget.detail.anchorClicked.emit(QUrl("cdmw-tool:new_item_studio"))
    assert calls == ["mod_management", "new_item_studio"]
    assert widget.selected_row().extension == ".cditem"
    widget.detail.anchorClicked.emit(QUrl("https://invalid.example/"))
    assert calls == ["mod_management", "new_item_studio"]


def test_missing_note_does_not_claim_complete_support(panel):
    widget, _calls = panel
    plain = next(row for row in widget._rows if not row.remaining and not row.workflow.operations)
    widget.include_absent.setChecked(True)
    _select(widget, plain.extension)
    assert "Nothing outstanding." not in widget.detail.toPlainText()
    assert catalogue.NO_REMAINING_NOTE in widget.detail.toPlainText()


def test_policy_refusal_removes_editing_claim_without_hiding_import_or_export(monkeypatch):
    from tools.format_explorer.workflows import workflow_for

    refusal = mesh_policy.geometry_authoring_capability(".pac", lod_index=1)
    output_policy = mesh_policy.output_policy_state
    monkeypatch.setattr(mesh_policy, "geometry_authoring_capability", lambda *args, **kwargs: refusal)
    monkeypatch.setattr(
        mesh_policy, "output_policy_state",
        lambda *args, **kwargs: replace(output_policy(*args, **kwargs), output_capability=refusal),
    )
    exact = workflow_for(".pac")
    working = workflow_for(".glb")
    assert exact.editable is working.editable is False
    assert exact.write_label == "Not editable"
    assert working.write_label == "Import only"
    assert {operation.kind for operation in exact.operations} == {"inspect", "export"}
    assert {operation.kind for operation in working.operations} == {"import", "export"}
    assert refusal.reason in " ".join(exact.limits)
    assert refusal.reason in " ".join(working.limits)


def test_localization_manifest_covers_presented_workflow_metadata(rows):
    from scripts.generate_ui_localization_manifest import MANIFEST_PATH
    from tools.format_explorer.workflows import OPERATION_LABELS, READ_LABELS, WRITE_LABELS

    entries = {entry["key"] for entry in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["entries"]}
    labels = set(OPERATION_LABELS.values()) | set(READ_LABELS.values()) | set(WRITE_LABELS.values())
    labels.update((catalogue.NO_REMAINING_NOTE, catalogue._HEADLINE))
    for row in rows:
        texts = (
            row.workflow.prerequisites, *row.workflow.limits,
            *(operation.description for operation in row.workflow.operations),
        )
        for text in texts:
            labels.update(part for part in catalogue.detail_text_segments(text) if part)
        if row.files is None:
            labels.update((row.role, row.group.replace("_", " ")))
            for text in (row.evidence, row.remaining):
                labels.update(part for part in catalogue.detail_text_segments(text) if part)
    assert labels <= entries


@pytest.mark.parametrize("code", [
    "de", "es-ES", "es-419", "fr", "it", "pt-BR", "pl", "ru", "tr",
    "ja", "ko", "zh-Hans", "zh-Hant",
])
def test_new_workflow_guidance_translates_at_runtime(rows, code, tmp_path):
    from cdmw.ui.localization import UiLocalizer

    localizer = UiLocalizer(language_dir=tmp_path, language_code=code)
    package = next(row for row in rows if row.extension == ".cditem")
    try:
        for source in (
            "Include application and non-shipped formats", "Read / import",
            "Edit / output", "Where to use it", "Edit after import; OBJ output",
            "No additional limits recorded here.", package.workflow.prerequisites,
            *package.workflow.limits,
        ):
            assert localizer.translate_rendered(source) != source, (code, source)
        headline = catalogue.headline(rows)
        translated = localizer.translate_rendered(headline)
        assert translated != headline
        assert "87" in translated
    finally:
        localizer.shutdown()
