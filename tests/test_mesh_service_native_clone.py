"""Clone refusals retain the failing phase and native error before cleanup."""

import pytest

from cdmw.services.mesh_service_native_clone import (
    _clone_mesh_for_service_native_snapshot, _clone_mesh_pair_for_session_open,
)
from tests.test_mesh_service_editing import _quad_mesh


@pytest.mark.parametrize("pair", [False, True])
@pytest.mark.parametrize("phase", ["creation", "restoration", "exception"])
def test_native_clone_refusal_preserves_error_and_blocks_python_fallback(monkeypatch, pair, phase):
    from cdmw.services import mesh_service

    error = ["snapshot-submeshes-json: owned native failure"]
    disposed = []
    snapshot = {"kind": "native_submesh_snapshot", "submeshes": []}
    monkeypatch.setattr(mesh_service, "native_mesh_core_available", lambda: True)
    monkeypatch.setattr(mesh_service, "last_native_mesh_core_job_error", lambda: error[0])
    monkeypatch.setattr(mesh_service, "record_native_mesh_core_fallback", lambda *a, **kw: None)
    monkeypatch.setattr(mesh_service, "snapshot_native_mesh_submeshes",
                        lambda mesh: None if phase == "creation" else snapshot)

    def restore(*args):
        if phase == "exception":
            raise ValueError("owned invalid snapshot descriptor")
        return False

    def dispose(value):
        disposed.append(value)
        error[0] = ""  # Successful cleanup clears the runner's compatibility slot.

    def python_clone(*args):
        raise AssertionError("Python fallback must remain blocked")

    monkeypatch.setattr(mesh_service, "restore_native_mesh_submesh_snapshot", restore)
    monkeypatch.setattr(mesh_service, "dispose_native_mesh_submesh_snapshot", dispose)
    monkeypatch.setattr(mesh_service, "clone_mesh_for_editing", python_clone)
    expected = ("snapshot restoration: ValueError: owned invalid snapshot descriptor" if phase == "exception"
                else f"snapshot {phase}: snapshot-submeshes-json: owned native failure")
    with pytest.raises(RuntimeError, match="Python fallback was blocked") as failure:
        if pair:
            _clone_mesh_pair_for_session_open(_quad_mesh())
        else:
            _clone_mesh_for_service_native_snapshot(_quad_mesh(), "owned.clone", "owned test refusal")
    assert expected in str(failure.value)
    assert disposed == ([] if phase == "creation" else [snapshot])
