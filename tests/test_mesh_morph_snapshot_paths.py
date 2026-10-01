from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from cdmw.modding import mesh_native_session_api as api


@pytest.fixture
def redirected_temp(tmp_path: Path):
    physical = tmp_path / "physical temp"
    physical.mkdir()
    alias = tmp_path / "redirected temp"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(physical)],
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
    else:
        alias.symlink_to(physical, target_is_directory=True)
    try:
        yield alias, physical
    finally:
        alias.rmdir() if os.name == "nt" else alias.unlink()


def _descriptor(path: Path) -> dict[str, object]:
    path.write_bytes(b"{}")
    return {
        "schema": "cdmw_mesh_editor_morph_runtime_snapshot_v1",
        "version": 1,
        "snapshot_id": "snapshot",
        "source_session_id": "source",
        "path": str(path),
        "sha256": hashlib.sha256(b"{}").hexdigest(),
        "topology_digest": "0" * 64,
        "byte_length": 2,
        "retained_bytes": 1,
    }


@pytest.mark.parametrize("operation", ["restore", "dispose"])
def test_snapshot_commands_use_the_validated_temp_alias(
    redirected_temp, monkeypatch, operation: str,
) -> None:
    alias, physical = redirected_temp
    path = physical / "cdmw_mesh_preview_delta_test_morph_runtime_snapshot.json"
    descriptor = _descriptor(path)
    monkeypatch.setattr(api.tempfile, "gettempdir", lambda: str(alias))
    assert api._validated_morph_runtime_snapshot_descriptor(descriptor)["path"] == str(path)
    calls = []
    released = []

    def command(name, session_id, payload, **kwargs):
        calls.append((name, session_id, payload))
        return {"status": "ok", "disposed": True}

    monkeypatch.setattr(api, "native_mesh_editor_session_command", command)
    monkeypatch.setattr(api, "_release_native_preview_delta_path", released.append)
    if operation == "restore":
        assert api.restore_native_mesh_editor_morph_runtime_snapshot("target", descriptor)
    else:
        assert api.dispose_native_mesh_editor_morph_runtime_snapshot(descriptor)
    assert len(calls) == 1
    name, session_id, payload = calls[0]
    assert name == f"morph_snapshot_{operation}"
    assert session_id == ("target" if operation == "restore" else "source")
    expected_path = str(alias / path.name)
    assert payload == {
        "snapshot_id": descriptor["snapshot_id"],
        "snapshot_path": expected_path,
        "snapshot_byte_length": descriptor["byte_length"],
        "snapshot_sha256": descriptor["sha256"],
    }
    assert released == ([expected_path] if operation == "dispose" else [])


@pytest.mark.parametrize("operation", ["restore", "dispose"])
def test_redirected_temp_does_not_allow_snapshots_outside_its_target(
    tmp_path: Path, redirected_temp, monkeypatch, operation: str,
) -> None:
    alias, _ = redirected_temp
    path = tmp_path / "cdmw_mesh_preview_delta_outside_morph_runtime_snapshot.json"
    descriptor = _descriptor(path)
    monkeypatch.setattr(api.tempfile, "gettempdir", lambda: str(alias))
    monkeypatch.setattr(
        api, "native_mesh_editor_session_command",
        lambda *args, **kwargs: pytest.fail("outside snapshot reached native core"),
    )
    if operation == "restore":
        assert api.restore_native_mesh_editor_morph_runtime_snapshot("target", descriptor) is None
    else:
        assert api.dispose_native_mesh_editor_morph_runtime_snapshot(descriptor) is False
    assert path.read_bytes() == b"{}"


def _finish_in_redirected_temp(root: Path, with_edit: bool) -> None:
    # A fresh process keeps pytest's temp canonicalization and any running
    # native helper from hiding the actual application path mismatch.
    from cdmw.modding import mesh_native_core, mesh_native_core_temp_paths
    from tests.test_mesh_rust_authoring_exact_output import (
        _apply_position_edit, _open_exact_session, _request,
    )

    temp_root = Path(tempfile.gettempdir())
    assert temp_root != temp_root.resolve()
    _, service, session = _open_exact_session(root)
    try:
        if with_edit:
            _apply_position_edit(session)
        result = session.finish(_request(session, "finish_request", 2))
        assert result["status"] == "accepted"
        assert service.session_view(session.authoritative_session_id).revision == 1
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)
        mesh_native_core.shutdown_native_mesh_core_service()
    assert not list(temp_root.glob("cdmw_mesh_preview_delta_*_morph_runtime_snapshot.json"))
    assert not any(
        path.name.endswith("_morph_runtime_snapshot.json")
        for path in mesh_native_core_temp_paths._native_preview_delta_paths
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows native helper TEMP junction regression")
@pytest.mark.parametrize("with_edit", [False, True])
def test_finish_with_redirected_temp_uses_real_native_restore_and_disposal(
    tmp_path: Path, redirected_temp, with_edit: bool,
) -> None:
    alias, _ = redirected_temp
    env = dict(os.environ)
    env.update(TEMP=str(alias), TMP=str(alias), TMPDIR=str(alias), QT_QPA_PLATFORM="offscreen")
    script = (
        "from pathlib import Path; import sys; "
        "from tests.test_mesh_morph_snapshot_paths import _finish_in_redirected_temp; "
        "_finish_in_redirected_temp(Path(sys.argv[1]), sys.argv[2] == 'True')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "session"), str(with_edit)],
        cwd=Path(__file__).resolve().parents[1], env=env,
        text=True, capture_output=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
