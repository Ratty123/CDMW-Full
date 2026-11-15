"""The embedded Mesh Editor as a hostable component (P4 V2)."""

from cdmw.ui.mesh_editor.live_edit.component import (
    HOST_NAMES,
    STATE_NAMES,
    LiveEditComponent,
    install_live_edit_forwarders,
    moved_method_names,
)

__all__ = ["HOST_NAMES", "STATE_NAMES", "LiveEditComponent", "install_live_edit_forwarders", "moved_method_names"]
