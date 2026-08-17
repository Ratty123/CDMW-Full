"""The runtime diagnostics snapshot has to build, not just return.

Almost nothing calls `_mesh_editor_embedded_runtime_diagnostics`, and what it
does is reach across every resident mixin. A helper removed from under it
therefore fails at the moment a reader opens diagnostics to investigate
something else, which is the worst possible time. These assertions walk the
material section rather than only checking that the call returned.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor import MeshEditorTab
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder


def _ready_tab(name: str):
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", name)
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "ready",
            "renderer": {
                "backend": "d3d11_vortice_shader",
                "gpu_backed": True,
                "renderer_blocked": False,
            },
        }
    )
    return app, tab, builder


def test_the_material_section_resolves_every_role_helper() -> None:
    app, tab, builder = _ready_tab("MeshEditorDiagnosticsMaterialSection")

    materials = builder._mesh_editor_embedded_runtime_diagnostics()["materials"]

    assert materials["active_role"] == "editable_imported"
    assert "editable_imported" in materials["required_roles"]
    assert set(materials["status_by_role"]) == {"editable_imported", "original_reference"}
    assert materials["status_by_role"]["editable_imported"]["stage"] == "not_published"
    assert materials["status_by_role"]["editable_imported"]["active"] is True
    assert materials["blocking_reason_by_role"]["editable_imported"] == (
        "Imported pane materials have not been published yet."
    )

    app.processEvents()
    tab.deleteLater()
    builder.deleteLater()


def test_the_publication_section_reports_an_empty_queue_before_any_work() -> None:
    app, tab, builder = _ready_tab("MeshEditorDiagnosticsPublications")

    publications = builder._mesh_editor_embedded_runtime_diagnostics()["materials"][
        "publications"
    ]

    assert publications["active"] is None
    assert publications["queued"] == ()
    assert publications["awaiting_acknowledgement"] == ()
    assert publications["pending_roles"] == ()
    assert publications["counts"]["enqueued"] == 0

    app.processEvents()
    tab.deleteLater()
    builder.deleteLater()


def test_the_active_role_follows_the_comparison_mode_in_diagnostics() -> None:
    app, tab, builder = _ready_tab("MeshEditorDiagnosticsActiveRole")

    tab.standalone_dotnet_scene_desired["comparison_mode"] = "original_only"
    materials = builder._mesh_editor_embedded_runtime_diagnostics()["materials"]

    assert materials["active_role"] == "original_reference"
    assert materials["status_by_role"]["original_reference"]["active"] is True
    assert materials["status_by_role"]["editable_imported"]["active"] is False

    app.processEvents()
    tab.deleteLater()
    builder.deleteLater()
