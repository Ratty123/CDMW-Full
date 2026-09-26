"""Rust presentation of the integrated management workflow and live preview portals."""
from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
from cdmw.ui.tools.mod_management import ModManagementTab


class RustModManagementTab(RustNewItemStudioTab):
    def __init__(self, parent=None, **kwargs):
        workflow = ModManagementTab(**kwargs)
        super().__init__(parent, window=kwargs.get('window'), workflow=workflow,
                         tool_key='mod_management', title='Mod Management')

    def prewarm(self):
        # Mod Management reads its own inventory; opening it never starts the
        # unrelated New Item authoring snapshot.
        if not self._closed and self._bridge is None:
            self._prewarming = not self.isVisible()
            self.use_rust()
