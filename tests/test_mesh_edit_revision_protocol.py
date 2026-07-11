from __future__ import annotations

import os
from pathlib import Path
import tempfile

from tests.mesh_editor_source_support import mesh_editor_tab_source
from tests.native_source_text import d3d11_preview_source


ROOT = Path(__file__).resolve().parents[1]


def _host():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

    app = QApplication.instance() or QApplication([])
    return app, NativeD3D11PreviewHostFrame()


def test_python_sender_rejects_out_of_order_and_future_acknowledgements() -> None:
    app, host = _host()
    try:
        with host._mesh_edit_sender_condition:
            host._mesh_edit_sender_inflight_revision = 5
        capability = {"capabilities": ["mesh_edit_revision_ack_v1"]}
        assert not host._accept_mesh_edit_update_ack({**capability, "edit_revision": 4, "status": "applied"})
        assert not host._accept_mesh_edit_update_ack({**capability, "edit_revision": 6, "status": "applied"})
        assert host._accept_mesh_edit_update_ack({**capability, "edit_revision": 5, "status": "applied"})
        assert not host._accept_mesh_edit_update_ack({**capability, "edit_revision": 5, "status": "applied"})
        metrics = host.last_mesh_edit_send_metrics()
        assert metrics["last_acked_revision"] == 5
        assert metrics["ignored_acks"] == 3
        assert metrics["revision_ack_capable"] is True
    finally:
        host._mesh_edit_sender_inflight_revision = 0
        host.close()
        host.deleteLater()
        app.processEvents()


def test_python_sender_keeps_legacy_revision_zero_until_capability_is_known() -> None:
    app, host = _host()
    try:
        with host._mesh_edit_sender_condition:
            host._mesh_edit_sender_inflight_revision = 2
        assert host._accept_mesh_edit_update_ack({"event": "mesh_edit_vertices_updated"})
        with host._mesh_edit_sender_condition:
            host._mesh_edit_sender_inflight_revision = 3
        assert not host._accept_mesh_edit_update_ack(
            {
                "event": "mesh_edit_vertices_updated",
                "capabilities": ["mesh_edit_revision_ack_v1"],
            }
        )
    finally:
        host._mesh_edit_sender_inflight_revision = 0
        host.close()
        host.deleteLater()
        app.processEvents()


def test_python_sender_tracks_current_rejected_revision_without_treating_it_as_applied() -> None:
    app, host = _host()
    try:
        with host._mesh_edit_sender_condition:
            host._mesh_edit_sender_inflight_revision = 9
        assert host._accept_mesh_edit_update_ack(
            {
                "event": "mesh_edit_vertices_updated",
                "edit_revision": 9,
                "status": "rejected",
                "reason": "stale_or_out_of_order",
                "last_applied_revision": 12,
                "capabilities": ["mesh_edit_revision_ack_v1"],
            }
        )
        metrics = host.last_mesh_edit_send_metrics()
        assert metrics["last_acked_revision"] == 0
        assert metrics["last_rejected_revision"] == 9
        assert metrics["rejected_updates"] == 1
        assert metrics["latest_revision"] == 12
    finally:
        host._mesh_edit_sender_inflight_revision = 0
        host.close()
        host.deleteLater()
        app.processEvents()


def test_loading_package_resets_revision_stream_and_discards_pending_delta() -> None:
    app, host = _host()
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pending_delta = root / "pending.bin"
            pending_delta.write_bytes(b"pending")
            with host._mesh_edit_sender_condition:
                host._mesh_edit_sender_generation = 3
                host._mesh_edit_sender_latest_revision = 20
                host._mesh_edit_sender_last_sent_revision = 20
                host._mesh_edit_sender_last_acked_revision = 20
                host._mesh_edit_sender_pending = (
                    3,
                    21,
                    1,
                    2,
                    {"command": "mesh_edit_update", "edit_revision": 21},
                    (pending_delta,),
                )
            host._host_hwnd = lambda: 1  # type: ignore[method-assign]
            host._send_host_json_command_to_hwnd = (  # type: ignore[method-assign]
                lambda _hwnd, _sender, payload: payload.get("command") == "load_package"
            )

            assert host.load_package(root / "package", root / "status.json")
            assert not pending_delta.exists()
            assert host._reserve_mesh_edit_revision(1) == 1
            metrics = host.last_mesh_edit_send_metrics()
            assert metrics["generation"] == 4
            assert metrics["latest_revision"] == 1
            assert metrics["last_sent_revision"] == 0
            assert metrics["last_acked_revision"] == 0
    finally:
        host.close()
        host.deleteLater()
        app.processEvents()


def test_native_and_dotnet_receivers_advertise_revision_ack_and_keep_legacy_alias() -> None:
    native = d3d11_preview_source()
    dotnet = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.Protocol.cs").read_text(
        encoding="utf-8"
    )

    assert "mesh_edit_revision_is_stale" in native
    assert '"edit_revision"' in native
    assert '"revision"' in native
    assert '"status"' in native
    assert "mesh_edit_revision_ack_v1" in native
    assert "CanApplyEditRevision" in dotnet
    assert "MarkEditRevisionApplied" in dotnet
    assert '["edit_revision"] = revision' in dotnet
    assert '["revision"] = revision' in dotnet
    assert "stale_or_out_of_order" in dotnet
    assert "mesh_edit_revision_ack_v1" in dotnet

    tab = mesh_editor_tab_source()
    queue = Path("cdmw/ui/mesh_editor/dotnet_update_queue.py").read_text(encoding="utf-8")
    assert 'base["edit_revision"] = int(revision)' in tab
    assert 'event in {"preview_vertex_update_ack", "preview_triangle_update_ack"}' in tab
    assert "DotNetRevisionUpdateQueue" in tab
    assert "pending_depth" in queue
    assert "_remove_paths(self._active_paths)" in queue
    assert "_handle_dotnet_update_ack_timeout" in tab
    assert "standalone_dotnet_update_ack_timer.start(1_000)" in tab
