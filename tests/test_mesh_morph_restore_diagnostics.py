from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.services import mesh_service_morph
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_morph_service import _Settings, _author_command
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


@pytest.mark.parametrize("report,reason", [
    (None, "Native restore rejected: snapshot identity mismatch"),
    ({"status": "ok", "geometry_recomposed": True}, "geometry_recomposed=True"),
])
def test_restore_error_keeps_its_reason_while_cleanup_preserves_the_mesh(tmp_path, report, reason):
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    source = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    target, captured = "", None
    try:
        assert service.apply_command(source, _author_command()).ok
        captured = service.capture_morph_session_state(source)
        target = service.open_edit_session(service.working_mesh(source, clone=True), mode="edit").session_id
        before = service.working_mesh(target, clone=True)
        with patch.object(mesh_service_morph, "restore_native_mesh_editor_morph_runtime_snapshot", return_value=report), \
             patch.object(mesh_service_morph, "last_native_mesh_core_job_error", return_value=reason):
            with pytest.raises(RuntimeError) as error:
                service.install_morph_session_state(target, captured)
        assert "runtime snapshot restore failed" in str(error.value) and reason in str(error.value)
        after = service.working_mesh(target, clone=True)
        assert [part.vertices for part in after.submeshes] == [part.vertices for part in before.submeshes]
        assert target not in service._morph_sessions
    finally:
        if target:
            service.close_edit_session(target)
        service.close_edit_session(source)
        if captured is not None:
            path = Path(captured.native_snapshot["path"])
            service.dispose_morph_session_state(captured)
            assert not path.exists()
