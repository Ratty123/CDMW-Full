from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import QProcess

from cdmw.services.mesh_rust_authoring import read_owned_payload_reference
from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin
from cdmw.workers.mesh_rust_editor_workers import MeshRustProtocolWorker
from tests import test_mesh_rust_authoring as authoring_fixtures


@pytest.mark.parametrize("rejected", [False, True])
def test_large_selection_reply_and_recovery_use_verified_file(tmp_path, rejected):
    # Dense PAC contribution arrays used to make even a part selection exceed
    # the helper's 256 KiB line limit. Exercise the real worker and pipe encoder.
    dense = {"available": True, "overlay_parts": [
        {"index": 0, "preview": {"current_bytes": [249] * 80_000}}
    ]}
    with patch("cdmw.services.mesh_rust_jiggle.jiggle_ui_state", return_value=dense):
        service, session = authoring_fixtures.RustMeshAuthoringTests()._create(tmp_path / "session")
        authoritative_id = session.authoritative_session_id
        try:
            request = {**authoring_fixtures._request(session, "command_request", 1),
                       "command": "unsupported" if rejected else "select",
                       "arguments": {"selection": {"source_indices": [0]}}}
            worker = MeshRustProtocolWorker(7, session, request)
            completed, errors = [], []
            worker.completed.connect(lambda *args: completed.append(args))
            worker.error.connect(lambda *args: errors.append(args))
            worker.run()
            if rejected:
                assert errors and not completed
                response = {"event": "command_result", "ok": False,
                            "payload": errors[0][-1]}
            else:
                assert completed and not errors
                response = completed[0][2]
                assert response["payload"]["state"]["selection"]["source_indices"] == [0]
            original_payload = response["payload"]
            assert original_payload["state"]["jiggle"] == dense
            sent = []
            process = SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                      write=lambda data: sent.append(data) or len(data))
            host = SimpleNamespace(standalone_rust_process=process)
            assert MeshEditorRustProcessMixin._send_rust_message(host, response)
            assert len(sent[0]) < 256 * 1024
            wire = json.loads(sent[0])
            assert set(wire["payload"]) == {"payload_file"}
            restored = read_owned_payload_reference(session.root, wire["payload"]["payload_file"])
            assert restored["state"] == original_payload["state"]
            assert response["payload"] is original_payload
            assert service.session_view(authoritative_id).selection.is_empty()
            # Reuse one owned file and keep normal session validation operational.
            session.stage_control_payload({"state": restored["state"]})
            assert len(list(session.root.glob("host-control*.json"))) == 1
        finally:
            session.cancel()
            service.close_edit_session(authoritative_id)
