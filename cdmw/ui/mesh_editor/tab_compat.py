from __future__ import annotations

import sys
from types import ModuleType


class _MeshEditorTabFacadeGlobals:
    """Resolve legacy patch seams from the public tab module at call time."""

    @staticmethod
    def _module() -> ModuleType:
        module = sys.modules.get("cdmw.ui.mesh_editor.tab")
        if module is None:
            raise RuntimeError("Mesh Editor tab facade is not loaded")
        return module

    def __getattr__(self, name: str) -> object:
        return getattr(self._module(), name)


facade_globals = _MeshEditorTabFacadeGlobals()
