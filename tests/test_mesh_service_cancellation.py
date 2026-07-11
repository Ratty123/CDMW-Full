from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.models import RunCancelled
from cdmw.services.mesh_service import MeshService
from tools.mesh_harness.fixtures import build_synthetic_mesh


def test_cancel_during_native_selection_preparation_never_opens_helper() -> None:
    service = MeshService()
    view = service.open_edit_session(build_synthetic_mesh(), session_id="cancel-selection-prep", mode="edit")
    stop_event = threading.Event()

    def cancel_after_signature(*_args: object) -> tuple[str, tuple[object, ...]]:
        stop_event.set()
        return ("selection", ())

    with (
        patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
        patch(
            "cdmw.services.mesh_service._native_editor_selection_signature_for_apply",
            side_effect=cancel_after_signature,
        ),
        patch("cdmw.services.mesh_service.open_native_mesh_editor_session") as open_native,
        pytest.raises(RunCancelled, match="cancelled"),
    ):
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "subdivide",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"stop_event": stop_event},
                mode="edit",
            ),
        )

    open_native.assert_not_called()
