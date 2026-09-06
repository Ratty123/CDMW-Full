from __future__ import annotations

import os
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_rust_authoring import (
    RustMeshAuthoringSession,
    RustMeshValidationError,
)
from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadWorker
from tests.test_mesh_rust_authoring import (
    _Settings,
    _pac_fixture,
    _request,
    _with_resolvable_bone_palette,
)


_BONE_HASHES = tuple(0xA1000000 + index for index in range(8))


def _pab(hashes: tuple[int, ...]) -> bytes:
    data = bytearray(b"PAR " + bytes(18))
    struct.pack_into("<H", data, 20, len(hashes))
    identity = struct.pack("<16f", *(1.0 if i % 5 == 0 else 0.0 for i in range(16)))
    for index, name_hash in enumerate(hashes):
        name = f"Bone{index}".encode("ascii")
        data.extend(struct.pack("<IB", name_hash, len(name)) + name)
        data.extend(struct.pack("<i", -1) + identity * 4)
        data.extend(struct.pack("<3f4f3f", 1, 1, 1, 0, 0, 0, 1, 0, 0, 0))
    return bytes(data)


@pytest.fixture
def loaded_mesh(request: pytest.FixtureRequest, tmp_path: Path):
    source = _with_resolvable_bone_palette(_pac_fixture(skinned=True), _BONE_HASHES)
    payloads = {"character/model/body.pac": source}
    case = request.param
    if case == "resolved":
        payloads["character/model/body.pab"] = _pab(tuple(0xB1000000 + i for i in range(8)))
        payloads["character/skeleton/shared_rig.pab"] = _pab(_BONE_HASHES)
    elif case == "ambiguous":
        payloads["character/skeleton/shared_one.pab"] = _pab(_BONE_HASHES)
        payloads["character/skeleton/shared_two.pab"] = _pab(_BONE_HASHES)
    elif case == "invalid":
        payloads["character/model/body.pab"] = b"invalid PAB"
    elif case == "empty":
        payloads["character/model/body.pab"] = _pab(())
    entries = [
        ArchiveEntry(
            path=path,
            pamt_path=tmp_path / "0.pamt",
            paz_file=tmp_path / "0.paz",
            offset=index * 10000,
            comp_size=len(payload),
            orig_size=len(payload),
            flags=0,
            paz_index=0,
        )
        for index, (path, payload) in enumerate(payloads.items())
    ]
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    worker = MeshArchiveSessionLoadWorker(
        4,
        entries[0],
        session_id="pab-resolution",
        archive_entries_by_normalized_path=(
            {} if case == "no_index" else {entry.path: (entry,) for entry in entries}
        ),
        archive_entries_by_basename=(
            {} if case == "no_index" else {entry.basename.casefold(): (entry,) for entry in entries}
        ),
    )
    loaded = []
    errors = []
    worker.loaded.connect(lambda _request_id, result: loaded.append(result))
    worker.error.connect(lambda _request_id, error: errors.append(error))
    with patch(
        "cdmw.workers.mesh_editor_aux_workers.read_archive_entry_data",
        side_effect=lambda entry, **_kwargs: (payloads[entry.path], False, ""),
    ), patch("cdmw.workers.mesh_editor_aux_workers.MeshService", return_value=service):
        worker.run()
    try:
        assert errors == []
        assert len(loaded) == 1
        yield entries[0], loaded[0]
    finally:
        for session_id in tuple(service._sessions):
            service.close_edit_session(session_id, force_without_saving=True)


@pytest.mark.parametrize(
    ("loaded_mesh", "expected_reason"),
    [
        ("resolved", ""),
        ("missing", "No PAB skeleton candidate could be resolved"),
        ("ambiguous", "Ambiguous skeleton candidates"),
        ("invalid", "Not a valid PAB file"),
        ("empty", "PAB contains no parsed bones"),
        ("no_index", "No archive dependency index was available"),
    ],
    indirect=["loaded_mesh"],
)
def test_archive_pab_resolution_reaches_the_initial_rig_controls(
    loaded_mesh, expected_reason: str, tmp_path: Path
) -> None:
    entry, result = loaded_mesh
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat))
    tab.archive_session_load_request_id = 4
    tab.archive_session_load_entry = entry
    sessions = []

    def show_session(*_args, **_kwargs):
        sessions.append(
            RustMeshAuthoringSession.create(
                tab.standalone_controller,
                tmp_path / "rust-session",
                process_generation=1,
                theme={},
            )
        )

    try:
        with patch.object(tab, "_show_standalone_session", side_effect=show_session), patch.object(
            tab, "_start_archive_material_context_resolution", return_value=True
        ):
            tab._handle_archive_session_loaded(4, result)
        assert len(sessions) == 1
        session = sessions[0]
        state = session.state_payload(include_document=False)
        rig = state["skeleton"]
        capability = rig["weight_edit_capability"]
        assert state["authoring_enabled"]
        assert rig["weighted_vertex_count"] > 0
        if not expected_reason:
            assert result.skeleton_source_path == "character/skeleton/shared_rig.pab"
            assert len(rig["bones"]) == len(_BONE_HASHES)
            assert capability["enabled"]
            assert capability["palette_size"] == len(_BONE_HASHES)
        else:
            assert result.source_skeleton is None
            assert result.skeleton_source_path == ""
            assert expected_reason in result.skeleton_resolution_reason
            assert rig["bones"] == []
            assert not capability["enabled"]
            assert capability["reason"] == result.skeleton_resolution_reason
            command = _request(session, "command_request", 1)
            command.update(
                command="rig_normalize_weights",
                arguments={
                    "selection": {
                        "vertices_by_submesh": {"0": [0]},
                        "edges_by_submesh": {},
                        "faces_by_submesh": {},
                        "source_indices": [],
                    }
                },
            )
            with pytest.raises(RustMeshValidationError) as error:
                session.run_command(command)
            assert str(error.value) == result.skeleton_resolution_reason
    finally:
        for session in sessions:
            session.cancel()
        tab.close_standalone_session()
        tab.deleteLater()
        app.processEvents()
