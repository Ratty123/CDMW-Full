"""Named .NET command requests: morph, embedded parts, layers, and direct.

Split out of :mod:`tab_dotnet_commands` to keep that module inside the
owned-file line cap. These four share a shape that the stroke and selection
handlers do not: the helper names a command, the host resolves it against a
controller and answers with one correlated result.
"""

from __future__ import annotations

import json
import time
from typing import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from cdmw.ui.shell.settings_bridge import read_bool_setting
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


from cdmw.ui.mesh_editor.tab_dotnet_lifecycle import MeshEditorDotNetLifecycleMixin


def _record_interaction_decision(target: object, event: str, **payload: object) -> None:
    recorder = getattr(target, "_record_dotnet_interaction_decision", None)
    if callable(recorder):
        recorder(event, **payload)




class MeshEditorDotNetNamedCommandMixin(MeshEditorDotNetLifecycleMixin):
    def _handle_dotnet_morph_command_request(
        self,
        controller: _tab.MeshEditorController,
        command: str,
        payload: Mapping[str, object],
    ) -> bool:
        if command == "morph_change":
            phase = str(payload.get("phase", "end") or "end").strip().lower()
            change_id = str(payload.get("change_id") or "").strip()
            definition_id = str(payload.get("definition_id") or "").strip()
            if phase not in {"begin", "update", "end", "cancel"} or not change_id or not definition_id:
                self._send_dotnet_command_result(
                    command,
                    ok=False,
                    status="error",
                    diagnostics=("Morph change requires definition_id, change_id, and a valid phase.",),
                    request_payload=payload,
                )
                return False
            if self._standalone_action_worker_active() or self.standalone_native_mesh_edit_stroke_id:
                return self._reject_dotnet_mutation_while_busy(command, payload)
            if phase == "begin":
                if self.standalone_dotnet_morph_change_id and self.standalone_dotnet_morph_change_id != change_id:
                    self._send_dotnet_command_result(
                        command,
                        ok=False,
                        status="busy",
                        diagnostics=("Finish the active Morph & Refit slider change first.",),
                        request_payload=payload,
                    )
                    return True
                self.standalone_dotnet_morph_change_id = change_id
            elif self.standalone_dotnet_morph_change_id and self.standalone_dotnet_morph_change_id != change_id:
                self._send_dotnet_command_result(
                    command,
                    ok=False,
                    status="error",
                    diagnostics=("Ignored stale Morph & Refit change id.",),
                    request_payload=payload,
                )
                return False
            queued = _tab.MeshEditCommand(
                "morph_change",
                params={
                    "definition_id": definition_id,
                    "value": self._standalone_native_payload_float(payload.get("value"), 0.0),
                    "phase": phase,
                    "change_id": change_id,
                },
                label="Adjust Procedural Morph",
            )
            sequence = self._ensure_standalone_live_stroke_dispatcher().submit(
                controller,
                queued,
                phase,
                source="dotnet_morph",
                request_payload=payload,
            )
            if sequence > 0:
                _record_interaction_decision(self,
                    "mesh_edit_morph_change_queued",
                    request_id=int(payload.get("request_id", 0) or 0),
                    change_id=change_id,
                    definition_id=definition_id,
                    phase=phase,
                    value=self._standalone_native_payload_float(payload.get("value"), 0.0),
                    dispatcher_sequence=sequence,
                )
                return True
            if phase in {"begin", "end", "cancel"}:
                self.standalone_dotnet_morph_change_id = ""
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="cancelled",
                diagnostics=("Morph & Refit dispatcher is stopping.",),
                request_payload=payload,
            )
            return False

        if self._reject_dotnet_mutation_while_busy(command, payload):
            return True
        local_selection = self._dotnet_local_selection_payload_to_selection(payload)
        params: dict[str, object] = {}
        if command in {"morph_activate", "morph_delete_profile"}:
            params["profile_id"] = str(payload.get("profile_id") or "").strip()
        elif command == "morph_delete_definition":
            params["definition_id"] = str(payload.get("definition_id") or "").strip()
        elif command in {"morph_apply_preset", "morph_delete_preset"}:
            params["preset_id"] = str(payload.get("preset_id") or "").strip()
        elif command == "morph_save_preset":
            params.update({
                "preset_id": str(payload.get("preset_id") or "").strip(),
                "name": str(payload.get("name") or payload.get("preset_name") or "").strip(),
            })
        elif command == "morph_set_driver":
            params["submesh_indices"] = tuple(local_selection.source_indices)
        elif command == "morph_bind":
            params["garment_submesh_indices"] = tuple(local_selection.source_indices)
        elif command == "morph_configure_refit":
            params.update({
                "garment_submesh_indices": tuple(local_selection.source_indices),
                "enabled": bool(payload.get("enabled", True)),
                "intensity_percent": self._standalone_native_payload_float(
                    payload.get("intensity_percent"), 100.0
                ),
                "mode": str(payload.get("mode") or "surface").strip().lower(),
                "clearance_percent": self._standalone_native_payload_float(
                    payload.get("clearance_percent"), 0.0
                ),
            })
        elif command == "morph_author_definition":
            for key in (
                "profile_id", "profile_name", "definition_id", "label", "category",
                "rule", "axis", "amount", "feather", "falloff", "mirror_mode",
                "min_percent", "max_percent", "default_percent", "local_basis",
                "preserve_selection", "source_definition_id",
            ):
                if key in payload:
                    params[key] = payload[key]
        worker_command = _tab.MeshEditCommand(
            command,
            selection=local_selection if command in {
                "morph_author_definition", "morph_set_driver", "morph_bind", "morph_configure_refit",
            } else None,
            params=params,
            label=command.removeprefix("morph_").replace("_", " ").title(),
        )
        return self._start_dotnet_action_worker(
            controller,
            worker_command,
            command_name=command,
            request_payload=payload,
        )

    def _handle_dotnet_embedded_part_command(
        self,
        command: str,
        local_selection: object,
        target_mode: str,
        payload: Mapping[str, object],
    ) -> bool | None:
        if not (
            self.standalone_dotnet_target_embedded
            and target_mode in {"part", "source"}
            and command in {"delete", "duplicate", "toggle_visibility"}
        ):
            return None
        runner = getattr(self.active_builder(), "_mesh_editor_embedded_run_part_action", None)
        if not callable(runner):
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="unavailable",
                diagnostics=("Resident part action bridge is unavailable.",),
                request_payload=payload,
            )
            return False
        try:
            ok = bool(
                runner(
                    command,
                    tuple(local_selection.source_indices),
                    request_payload=payload,
                )
            )
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor part action failed: {command}: {exc}", error=True)
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="error",
                diagnostics=(str(exc),),
                request_payload=payload,
            )
            return False
        revision = None
        current_controller = self._dotnet_target_controller()
        if current_controller is not None:
            try:
                revision = current_controller.session_view().resident_revision
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
                pass
        self._send_dotnet_command_result(
            command,
            ok=ok,
            status="applied" if ok else "no_change",
            revision=revision,
            request_payload=payload,
        )
        return ok

    def _handle_dotnet_layer_command(
        self,
        controller: _tab.MeshEditorController,
        command: str,
        payload: Mapping[str, object],
    ) -> bool | None:
        if command == "layer_delete":
            layer_id = str(payload.get("layer_id", "") or "").strip()
            return self._start_dotnet_action_worker(
                controller,
                _tab.MeshEditCommand(
                    "layer_delete",
                    params={"layer_id": layer_id},
                    mode="edit",
                    label="Delete Layer",
                ),
                command_name=command,
                request_payload=payload,
            )
        if command not in {"layer_activate", "layer_rename", "layer_visibility", "layer_move"}:
            return None
        layer_id = str(payload.get("layer_id", "") or "").strip()
        try:
            if command == "layer_activate":
                controller.activate_geometry_layer(layer_id)
            elif command == "layer_rename":
                controller.rename_geometry_layer(layer_id, str(payload.get("name", "") or ""))
            elif command == "layer_visibility":
                controller.set_geometry_layer_visibility(layer_id, bool(payload.get("visible", False)))
            else:
                controller.move_geometry_layer(
                    layer_id,
                    self._standalone_native_payload_int(payload.get("direction"), 0),
                )
            revision = controller.session_view().revision
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor layer command failed: {exc}", error=True)
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="error",
                diagnostics=(str(exc),),
                request_payload=payload,
            )
            self._send_dotnet_session_state()
            return False
        self._send_dotnet_command_result(
            command,
            ok=True,
            status="applied",
            revision=revision,
            request_payload=payload,
        )
        self._send_dotnet_session_state()
        return True

    def _handle_dotnet_direct_command(
        self,
        controller: _tab.MeshEditorController,
        command: str,
        payload: Mapping[str, object],
        local_selection: _tab.MeshEditSelection,
        *,
        selection_supplied: bool,
        target_mode: str,
    ) -> bool | None:
        if command == "copy":
            worker_command = _tab.MeshEditCommand(
                "copy",
                selection=local_selection if selection_supplied else None,
                params={"target_mode": target_mode},
                mode="edit",
                label="Copy Selection",
            )
        elif command == "paste":
            worker_command = _tab.MeshEditCommand("paste", mode="edit", label="Paste Selection")
        elif command == "clear_selection":
            worker_command = _tab.MeshEditCommand(
                "select",
                selection=_tab.MeshEditSelection(),
                params={"operation": "replace"},
                label="Clear Selection",
            )
        elif command == "select_all":
            worker_command = _tab.MeshEditCommand(
                "select",
                selection=_tab.MeshEditSelection(),
                params={"operation": "all", "target_mode": "vertex"},
                label="Select All",
            )
        elif command in {"grow", "shrink", "invert"}:
            normalized_target = target_mode if target_mode in {"vertex", "edge", "face"} else "vertex"
            worker_command = _tab.MeshEditCommand(
                "select",
                selection=local_selection,
                params={"operation": command, "target_mode": normalized_target},
                label=command.replace("_", " ").title(),
            )
        else:
            return None
        return self._start_dotnet_action_worker(
            controller,
            worker_command,
            command_name=command,
            request_payload=payload,
        )
