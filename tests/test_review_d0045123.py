"""Review of d0045123 (section 8.8 R12): Build marks a state it did not build as clean.

The real MeshService and the real MeshDirectOutputWorker's saved-work step; only
the built mod's record (register_built_mod) is stubbed, as it is not the point.
Strict xfail: it fails on the reviewed code; remove the marker with the fix.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.services.mesh_service import MeshService
from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
from tests.test_mesh_geometry_layers import _layer_mesh

_REVIEW = "Review of d0045123 (REPORT-review.md): Build marks a newer state clean"


def test_an_edit_made_while_a_mesh_without_a_draft_builds_still_asks_on_close(tmp_path, monkeypatch) -> None:
    """Build snapshots revision R. An edit lands while it builds (R + 1). The draft
    save then returns None ("the session has moved on"), and since R12 Build calls
    mark_history_clean anyway: for a mesh without a draft that marks the current
    key, R + 1, clean. Closing then loses the edit made during the build unasked."""

    from cdmw.services import mesh_saved_work_service

    monkeypatch.setattr(mesh_saved_work_service, "register_built_mod", lambda *args, **kwargs: object())
    service = MeshService()
    session_id = service.open_edit_session(_layer_mesh(), session_id=f"disk-{uuid4().hex}", mode="edit").session_id
    try:
        built_revision = int(service.session_view(session_id).revision)
        service.apply_command(session_id, MeshEditCommand(
            "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
            params={"translate": (0.5, 0.0, 0.0)}))  # made while the build ran
        assert service.closing_loses_work(session_id)
        worker = MeshDirectOutputWorker(1, service, session_id, SimpleNamespace(path="character/a.pac"),
                                        kind="loose_mod", saved_work_root=tmp_path / "saved")
        snapshot = SimpleNamespace(mesh_revision=built_revision, mesh_asset_source_hash="0" * 64)
        result = SimpleNamespace(output_path=tmp_path / "mod", zip_path=None, manager_profile="dmm")
        monkeypatch.setattr("cdmw.workers.mesh_editor_workers.replace", lambda value, **changes: value)
        worker._register_saved_work(snapshot, result)
        assert service.closing_loses_work(session_id), "Build marked an edit it did not build as clean"
    finally:
        service.close_edit_session(session_id)
