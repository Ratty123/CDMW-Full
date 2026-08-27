from __future__ import annotations

import os
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.models import TextureEditorSourceBinding
from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.texture_workflow.editor_resident_texture import (
    build_texture_editor_resident_patch,
)
from tools.mesh_harness.fixtures import build_synthetic_mesh


def test_texture_editor_handoffs_are_retired_without_mutating_the_mesh(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / "source.dds"
    candidate_path = tmp_path / "candidate.dds"
    source_path.write_bytes(b"dds source")
    candidate_path.write_bytes(b"dds candidate")
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(source_path)
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshTextureHandoffsRetired"))
    try:
        tab.open_mesh_session(mesh, session_id="texture-handoffs-retired", mode="edit")
        controller = tab.standalone_controller
        assert controller is not None
        tab.standalone_texture_preview_overrides[0] = "existing-preview-authority"
        binding = TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            source_identity_path=f"texture-handoffs-retired:0:{source_path}",
            source_path=str(source_path),
            texture_type="mesh_material",
            mesh_session_id="texture-handoffs-retired",
            mesh_resource_id=str(source_path),
            mesh_submesh_indices=(0,),
            mesh_channel="base",
            mesh_commit_mode="assign",
        )

        assert not tab.apply_texture_editor_dds_preview(str(candidate_path), binding)
        assert not tab.apply_texture_editor_dds_assignment(str(candidate_path), binding)
        assert not tab.apply_texture_editor_dds_result(str(candidate_path), binding)

        assert controller.working_mesh().submeshes[0].texture == str(source_path)
        assert controller.session_view().revision == 0
        assert tab.standalone_texture_preview_overrides == {0: "existing-preview-authority"}
    finally:
        tab.request_shutdown()
        tab.deleteLater()
        app.processEvents()


def test_retired_texture_patch_releases_composite_lease(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / "source.dds"
    source_path.write_bytes(b"dds source")
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(source_path)
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshTexturePatchRetiredLease"))
    try:
        tab.open_mesh_session(mesh, session_id="texture-patch-retired", mode="edit")
        binding = TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            source_identity_path=f"texture-patch-retired:0:{source_path}",
            texture_type="mesh_material",
            mesh_session_id="texture-patch-retired",
            mesh_submesh_indices=(0,),
            mesh_channel="base",
        )
        rgba = np.zeros((2, 2, 4), dtype=np.uint8)
        patch = build_texture_editor_resident_patch(
            binding,
            rgba,
            texture_revision=1,
            dirty_bounds=(0, 0, 1, 1),
        )
        assert not rgba.flags.writeable

        assert not tab.apply_texture_editor_region_patch(patch)

        assert patch.composite_lease.released
        assert rgba.flags.writeable
    finally:
        tab.request_shutdown()
        tab.deleteLater()
        app.processEvents()
