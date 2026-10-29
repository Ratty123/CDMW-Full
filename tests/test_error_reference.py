"""Source coverage and verbatim diagnostics in the shared Help/Wiki library."""
from cdmw.domain.mesh.topology import TOPOLOGY_BLOCKER_CODES
from cdmw.services.mesh_editor_error_codes import MeshEditorErrorCode
from cdmw.ui.localization import _translate_html_text
from cdmw.ui.shell.error_reference import (
    CODE_GUIDANCE, ERROR_REFERENCE_GROUPS, build_error_reference_section, build_error_reference_sections,
)
from cdmw.ui.shell.error_reference_data import ERROR_REFERENCE, MESSAGE_REFERENCE, DYNAMIC_REFERENCE, SOURCE_COVERAGE
from scripts.generate_error_reference import ROOT, collect_reference, collect_library


def test_error_inventory_matches_emitting_sources_and_registries():
    assert collect_library() == {'ERROR_REFERENCE': ERROR_REFERENCE, 'MESSAGE_REFERENCE': MESSAGE_REFERENCE,
                                'DYNAMIC_REFERENCE': DYNAMIC_REFERENCE, 'SOURCE_COVERAGE': SOURCE_COVERAGE}
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


def test_independent_language_sink_audit_has_no_unaccounted_messages():
    from scripts.audit_error_reference import audit
    counts, missing = audit()
    assert counts['Python raise'] > 7000
    assert counts['Native direct failure literal'] > 1000
    assert not missing, missing[:20]


def test_message_topics_contain_every_pattern_recovery_and_source():
    from html import escape
    from cdmw.ui.shell.error_reference_guidance import RECOVERY_GUIDANCE
    sections = {row['id']: row['html'] for row in build_error_reference_sections()}
    for row in MESSAGE_REFERENCE:
        body = sections['error_messages_' + row['area']]
        assert f'<code translate="no">{escape(row["message"])}</code>' in body
        assert escape(RECOVERY_GUIDANCE[row['recovery']][1]) in body
        assert all('/blob/main/' + path in body for path in row['sources'])
    for paths in DYNAMIC_REFERENCE.values():
        assert all('/blob/main/' + path in sections['external_errors'] for path in paths)


def test_python_scanner_keeps_reason_variants_and_ignores_metadata():
    from scripts.error_reference_scan import python_emissions
    source = '''
def _record_failure(*, reason, detail): pass
def run(failed):
    reason = "nonzero_returncode" if failed else "missing_report"
    _record_failure(reason=reason, detail=f"No report for {failed}")
    message = "The first input is absent."
    if failed:
        message = "The second input is absent."
    raise RuntimeError(message)
colors = {"error": "#ff0000"}
languages = {"code": "de", "native_name": "Deutsch"}
error_fields = set()
error_fields.add("mod_setup")
'''
    rows = python_emissions('cdmw/example.py', source)
    assert {'nonzero_returncode', 'missing_report'} <= {row.code for row in rows}
    assert {'The first input is absent.', 'The second input is absent.'} <= {row.text for row in rows}
    assert not {'#ff0000', 'mod_setup'} & {row.text for row in rows}
    assert 'de' not in {row.code for row in rows}


def test_native_scanner_preserves_joined_errors_and_rust_display_kinds():
    from scripts.error_reference_scan import native_emissions
    cpp = 'throw OverlayConflict("Wrong entry " + std::to_string(id) + " in package.");'
    assert 'Wrong entry {detail} in package.' in {row.text for row in native_emissions('native/example.cpp', cpp)}
    assert not native_emissions('native/example.cpp', 'FileAccessError(utf8_path("C:/model.pac"), error, "open");')
    rust = '''
enum ExampleError {
    #[error("Cannot open {0}")]
    Open(String),
    #[error(transparent)]
    Io(std::io::Error),
}
impl std::fmt::Display for WindowError {
    fn fmt(&self) { let message = match self {
        Self::WrongHandle => "the created window has no native HWND",
    }; }
}
#[cfg(test)]
mod tests { fn check() { panic!("test-only failure"); } }
fn later() { panic!("A production failure after the tests"); }
'''
    rows = native_emissions('tools/rust_mesh_lab/example.rs', rust)
    assert {'ExampleError::Open', 'ExampleError::Io', 'WindowError::WrongHandle'} <= {r.code for r in rows}
    assert 'test-only failure' not in {r.text for r in rows}
    assert 'A production failure after the tests' in {r.text for r in rows}
    assert any(r.text == '{upstream error}' and r.code == 'ExampleError::Io' for r in rows)


def test_audited_scope_covers_application_and_native_entry_points():
    for path in ('cdmw_app.py', 'cdmw/core/texture_native.py', 'tools/placement_studio/preflight.py',
                 'native/cdmw_preview_core/src/owners/path_io.cpp',
                 'tools/rust_mesh_lab/crates/cdmw_win32_embed/src/lib.rs',
                 'tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerRuntime.cs'):
        assert path in SOURCE_COVERAGE
    assert not any('/tests/' in p or p.endswith('/tests.rs') or '/headless_ui_tests/' in p for p in SOURCE_COVERAGE)
    codes = {row['code'] for row in ERROR_REFERENCE}
    assert {'native_helper_missing', 'unsafe_dds_input', 'missing_report', 'nonzero_returncode',
            'access_denied', 'path_too_long', 'EmbeddedWindowError::UnsupportedPlatform'} <= codes


def test_recovery_guidance_distinguishes_asset_libraries_and_bone_sockets():
    from scripts.generate_error_reference import recovery_kind
    assert recovery_kind('Model library import file is missing: {scene_path}') == 'missing'
    assert recovery_kind('Missing imported material library: {library}') == 'missing'
    assert recovery_kind('Native helper executable is missing.') == 'helper'
    assert recovery_kind('Invalid attachment socket on the skeleton.') == 'input'
