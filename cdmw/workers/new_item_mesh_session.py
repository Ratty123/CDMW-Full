"""Prepare an owned editing session before the GUI attaches it."""
from dataclasses import dataclass
from pathlib import Path
import tempfile
import uuid

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
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


def new_item_edit_destination() -> Path:
    """A new, unused Free Edit folder for a Create New Item editing session.

    Edits from Create New Item return through Use Mesh Editor changes, not through a
    Free Edit package, yet Free Edit only allows authoring once a new output folder
    is named. Name one up front so the editing tools open unlocked. Finish Edit Mesh
    validates in its own temporary folder; this one is written only if the user
    explicitly saves a Free Edit package.
    """
    parent = Path(tempfile.gettempdir()) / "cdmw-new-item-edits"
    parent.mkdir(parents=True, exist_ok=True)
    return parent / uuid.uuid4().hex


def prepare_new_item_mesh_session(mesh, session_id, stop_event):
    raise_if_cancelled(stop_event)
    service = MeshService()
    view = service.open_edit_session(mesh, session_id=session_id, mode="edit")
    result = PreparedNewItemMeshSession(service, mesh, view)
    try:
        if not view.authoring_enabled and str(getattr(view, "output_policy", "")) == MeshOutputPolicy.FREE_EDIT.value:
            result.view = service.configure_output_policy(
                view.session_id, MeshOutputPolicy.FREE_EDIT, output_destination=new_item_edit_destination())
        raise_if_cancelled(stop_event)
        return result
    except BaseException:
        result.cleanup()
        raise
