from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

from cdmw.core import archive_hkx
from cdmw.core import archive_hkx_native_summary
from cdmw.core import archive_hkx_decoder_requirements
from cdmw.core import archive_hkx_editable_catalog
from cdmw.core import archive_hkx_converter
from cdmw.core import archive_hkx_edit_gate
from cdmw.core import archive_hkx_editable_xml
from cdmw.core import archive_hkx_editor_model
from cdmw.core import archive_hkx_fixup_reports
from cdmw.core import archive_hkx_havok_view
from cdmw.core import archive_hkx_readiness
from cdmw.core import archive_hkx_record_layout
from cdmw.core import archive_hkx_relationships
from cdmw.core import archive_hkx_xml_metadata


REPO_ROOT = Path(__file__).resolve().parents[1]
OWNER_PATTERN = "archive_hkx_*_helpers_*.py"


def _owner_paths() -> tuple[Path, ...]:
    return tuple(sorted((REPO_ROOT / "cdmw" / "core").glob(OWNER_PATTERN)))


def test_hkx_helper_facade_keeps_direct_owner_identity() -> None:
    assert archive_hkx._hkx_native_summary_parts is archive_hkx_native_summary._hkx_native_summary_parts
    assert (
        archive_hkx._hkx_missing_decoder_requirements_for_type
        is archive_hkx_decoder_requirements._hkx_missing_decoder_requirements_for_type
    )
    assert (
        archive_hkx._hkx_editable_field_catalog_document
        is archive_hkx_editable_catalog._hkx_editable_field_catalog_document
    )
    for path in _owner_paths():
        owner = importlib.import_module(f"cdmw.core.{path.stem}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = (
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for name in names:
            assert getattr(archive_hkx, name) is getattr(owner, name), (path, name)

    owner_symbols = (
        (archive_hkx_record_layout, ("_hkx_record_layout_document",)),
        (archive_hkx_editor_model, ("_hkx_editor_model_document",)),
        (archive_hkx_relationships, ("_hkx_relationship_graph_document",)),
        (archive_hkx_editable_xml, ("build_hkx_editable_geometry_xml",)),
        (archive_hkx_xml_metadata, ("_hkx_xml_add_hkclass_metadata_readiness", "_hkx_xml_add_mesh_details")),
        (archive_hkx_edit_gate, ("_hkx_byte_patch_map_document", "_hkx_edit_gate_v1_document", "_hkx_modding_workspace_document")),
        (archive_hkx_converter, ("_hkx_export_mesh_shape_details_document", "_hkx_converter_report_document", "_hkx_interpret_record_payload")),
        (archive_hkx_fixup_reports, ("_hkx_tagfile_reference_fixups_document", "_hkx_fixup_semantics_report_document")),
        (archive_hkx_havok_view, ("_hkx_havok_xml_specialized_fields", "_hkx_havok_xml_view_document", "_hkx_havok_xml_parity_report_document")),
        (archive_hkx_readiness, ("_hkx_hkclass_metadata_readiness_document", "_hkx_native_backend_document", "_hkx_modding_readiness_document")),
    )
    for owner, symbols in owner_symbols:
        for name in symbols:
            assert getattr(archive_hkx, name) is getattr(owner, name), (owner, name)


def test_hkx_helper_owners_obey_size_caps_and_reduce_facade() -> None:
    facade = REPO_ROOT / "cdmw" / "core" / "archive_hkx.py"
    facade_source = facade.read_text(encoding="utf-8")
    facade_tree = ast.parse(facade_source)
    assert len(facade_source.splitlines()) <= 3_400
    assert max(
        (
            int(node.end_lineno or node.lineno) - node.lineno + 1
            for node in ast.walk(facade_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        default=0,
    ) <= 150
    for path in (
        *sorted((REPO_ROOT / "cdmw" / "core").glob("archive_hkx_*.py")),
    ):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert len(source.splitlines()) <= 800, path
        sizes = (
            int(node.end_lineno or node.lineno) - node.lineno + 1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        assert max(sizes, default=0) <= 150, path


def test_hkx_helper_owner_first_import_keeps_identity() -> None:
    owner_imports = (
        "import cdmw.core.archive_hkx_record_layout as record_layout; "
        "import cdmw.core.archive_hkx_editor_model as editor; "
        "import cdmw.core.archive_hkx_relationships as relationships; "
        "import cdmw.core.archive_hkx_editable_xml as editable_xml; "
        "import cdmw.core.archive_hkx_converter as converter; "
        "import cdmw.core.archive_hkx_fixup_reports as fixups; "
        "import cdmw.core.archive_hkx_havok_view as havok_view; "
        "import cdmw.core.archive_hkx_readiness as readiness; "
    )
    facade_imports = (
        "import cdmw.core.archive_hkx as facade; "
        "import cdmw.core.archive_modding as compat; "
    )
    assertions = (
        "assert facade._hkx_record_layout_document is record_layout._hkx_record_layout_document; "
        "assert facade._hkx_editor_model_document is editor._hkx_editor_model_document; "
        "assert facade._hkx_relationship_graph_document is relationships._hkx_relationship_graph_document; "
        "assert facade.build_hkx_editable_geometry_xml is editable_xml.build_hkx_editable_geometry_xml; "
        "assert compat.build_hkx_editable_geometry_xml is editable_xml.build_hkx_editable_geometry_xml; "
        "assert facade._hkx_converter_report_document is converter._hkx_converter_report_document; "
        "assert facade._hkx_fixup_semantics_report_document is fixups._hkx_fixup_semantics_report_document; "
        "assert facade._hkx_havok_xml_view_document is havok_view._hkx_havok_xml_view_document; "
        "assert facade._hkx_hkclass_metadata_readiness_document is readiness._hkx_hkclass_metadata_readiness_document"
    )
    for script in (owner_imports + facade_imports, facade_imports + owner_imports):
        result = subprocess.run(
            [sys.executable, "-c", script + assertions],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
