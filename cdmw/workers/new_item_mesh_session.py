"""Prepare an owned editing session before the GUI attaches it."""
from dataclasses import dataclass

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mesh_service import MeshService


@dataclass
class PreparedNewItemMeshSession:
    service: MeshService
    mesh: object
    view: object
    adopted: bool = False

    def cleanup(self):
        if not self.adopted:
            self.service.close_edit_session(self.view.session_id, force_without_saving=True)


def prepare_new_item_mesh_session(mesh, session_id, stop_event):
    raise_if_cancelled(stop_event)
    service = MeshService()
    view = service.open_edit_session(mesh, session_id=session_id, mode="edit")
    result = PreparedNewItemMeshSession(service, mesh, view)
    try:
        raise_if_cancelled(stop_event)
        return result
    except BaseException:
        result.cleanup()
        raise
