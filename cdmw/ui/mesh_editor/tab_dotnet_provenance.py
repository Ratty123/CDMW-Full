"""Resident preview capability and material-publication coordination."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Mapping, Sequence

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox

from cdmw.services.mesh_interaction_diagnostics import send_recorded_mesh_protocol_message
from cdmw.services.mesh_dotnet_material_state import (
    copy_dotnet_preview_material_bindings,
    defer_dotnet_preview_material_synthesis,
)
from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompileRequest,
    snapshot_mesh_dotnet_material_inputs,
)
from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    normalize_mesh_preview_display_mode,
    untextured_fallback_display_mode,
)
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_dotnet_capture import MeshEditorDotNetCaptureMixin
from cdmw.ui.mesh_editor.tab_dotnet_material_compilation import (
    MeshEditorDotNetMaterialCompilationMixin,
)
from cdmw.ui.mesh_editor.tab_dotnet_payloads import MeshEditorDotNetPayloadMixin



class MeshEditorDotNetProvenanceMixin(
    MeshEditorDotNetMaterialCompilationMixin,
    MeshEditorDotNetPayloadMixin,
):
    def _observe_dotnet_capabilities(self, payload: Mapping[str, object]) -> None:
        raw = payload.get("capabilities", ())
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            self.standalone_dotnet_capabilities.update(str(item) for item in raw)
        if self._dotnet_resident_material_updates_supported():
            QTimer.singleShot(0, self._flush_pending_dotnet_reference_material_resources)
