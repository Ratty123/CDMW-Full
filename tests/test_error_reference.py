"""Source coverage and verbatim diagnostics in the shared Help/Wiki library."""
from cdmw.domain.mesh.topology import TOPOLOGY_BLOCKER_CODES
from cdmw.services.mesh_editor_error_codes import MeshEditorErrorCode
from cdmw.ui.localization import _translate_html_text
from cdmw.ui.shell.error_reference import (
    CODE_GUIDANCE, ERROR_REFERENCE_GROUPS, build_error_reference_section,
)
from cdmw.ui.shell.error_reference_data import ERROR_REFERENCE
from scripts.generate_error_reference import ROOT, collect_reference


def test_error_inventory_matches_emitting_sources_and_registries():
    assert collect_reference() == ERROR_REFERENCE
    codes = {row["code"] for row in ERROR_REFERENCE}
    assert {code.value for code in MeshEditorErrorCode} <= codes
    assert set(TOPOLOGY_BLOCKER_CODES) <= codes
    assert set(CODE_GUIDANCE) <= codes
    assert {"request_stalled", "permission_denied", "effect.layers.limit", "payload_truncated"} <= codes
    for row in ERROR_REFERENCE:
        assert row["group"] in ERROR_REFERENCE_GROUPS
        assert row["sources"]
        assert all((ROOT / source).is_file() for source in row["sources"])


def test_only_marked_diagnostics_are_verbatim():
    seen = []
    def translate(value):
        seen.append(value)
        return {"Explanation": "Erklärung", "Ordinary code label": "Normale Codebezeichnung"}.get(value, "WRONG")
    source = '<p>Explanation</p><code translate="no">File is missing: {path}</code><code>Ordinary code label</code>'
    result = _translate_html_text(source, translate)
    assert result == '<p>Erklärung</p><code translate="no">File is missing: {path}</code><code>Normale Codebezeichnung</code>'
    assert seen == ["Explanation", "Ordinary code label"]


def test_library_contains_every_code_and_owning_source_link():
    section = build_error_reference_section()
    assert section["id"] == "error_code_library"
    for row in ERROR_REFERENCE:
        from html import escape
        assert f'<code translate="no">{escape(row["code"])}</code>' in section["html"]
        assert all(f'/blob/main/{source}"' in section["html"] for source in row["sources"])


def test_inventory_does_not_mistake_list_methods_for_diagnostics(tmp_path):
    source = tmp_path / "cdmw/example.py"
    source.parent.mkdir()
    source.write_text('''
def _issue(code, field_name, message):
    return {}
def example():
    def append(code, message):
        pass
    append("real_warning", "Something needs review.")
    values = []
    values.append("not_a_diagnostic")
    return _issue("name.required", "name", "Enter a name.")
''', encoding="utf-8")
    worker = tmp_path / "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    worker.parent.mkdir(parents=True)
    worker.write_text('var code = exception switch { _ => "worker_failure" }; return new WorkerError(code);', encoding="utf-8")
    rows = collect_reference(tmp_path)
    codes = {row["code"] for row in rows}
    assert {"real_warning", "name.required"} <= codes
    assert "not_a_diagnostic" not in codes
