"""What the .NET helper says it is, and whether the host believes it.

Split out of :mod:`tab_dotnet_resources` to keep that module inside the
owned-file line cap. The helper announces its capabilities and its build
provenance on connect. Both are recorded, and a helper whose provenance does
not match what this build expects is refused rather than driven, because the
protocol between them is versioned and a mismatch is not recoverable.
"""

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

    def _verify_dotnet_helper_provenance(self, payload: Mapping[str, object]) -> bool:
        executable = Path(str(self.standalone_dotnet_last_program or "")).expanduser()
        manifest_path = executable.parent / "cdmw-mesh-dotnet-editor.manifest.json"
        blockers = _tab.mesh_dotnet_helper_provenance_blockers(
            executable,
            payload,
            require_manifest=bool(getattr(sys, "frozen", False) or manifest_path.is_file()),
            required_capabilities=(
                "correlated_selection_strokes_v1",
                "geometry_layers_v1",
            ),
        )
        if blockers:
            text = "Mesh .NET helper provenance blocked: " + "; ".join(blockers)
            self.standalone_dotnet_provenance_verified = False
            self._record_mesh_dotnet_event(
                "mesh_dotnet_helper_provenance_blocked",
                executable=str(executable),
                blockers=blockers,
            )
            self._set_dotnet_status(text, error=True)
            self._stop_standalone_dotnet_editor_process(embedded_state="failed")
            if self.standalone_dotnet_target_embedded:
                self._notify_embedded_dotnet_launch_failed(
                    "mesh_dotnet_helper_provenance_blocked",
                    diagnostics=text,
                )
            return False
        self.standalone_dotnet_provenance_verified = True
        self._record_mesh_dotnet_event(
            "mesh_dotnet_helper_provenance_verified",
            executable=str(executable),
            manifest_path=str(manifest_path) if manifest_path.is_file() else "development",
        )
        return True
