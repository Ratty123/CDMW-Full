from __future__ import annotations

from typing import Mapping, Sequence

from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit


class MeshEditorDotNetMaterialParameterMixin:
    @staticmethod
    def _normalized_dotnet_material_parameter_groups(
        groups: Sequence[Mapping[str, object]],
    ) -> tuple[list[dict[str, object]], list[int]]:
        normalized: list[dict[str, object]] = []
        affected: set[int] = set()
        for raw_group in groups:
            if not isinstance(raw_group, Mapping):
                continue
            group = dict(raw_group)
            raw_indices = group.get("source_submesh_indices", ())
            if isinstance(raw_indices, Sequence) and not isinstance(raw_indices, (str, bytes)):
                index_values = raw_indices
            elif "source_submesh_index" in group:
                index_values = (group.get("source_submesh_index"),)
            else:
                index_values = ()
            indices: set[int] = set()
            for raw_index in index_values:
                if isinstance(raw_index, bool):
                    continue
                try:
                    index = int(raw_index)
                except (TypeError, ValueError, OverflowError):
                    continue
                if index >= 0:
                    indices.add(index)
            if not any(
                key in group
                for key in (
                    "texture_brightness", "contrast", "saturation", "gamma", "tint_color",
                    "post_contrast_brightness", "base_color_lift", "value_max", "auto_balance", "shadow_lift",
                    "roughness", "metalness", "metallic", "specular", "height_scale",
                    "roughness_inverted", "roughness_scale", "roughness_min", "roughness_max",
                    "roughness_blend_target", "roughness_blend_strength",
                    "metalness_inverted", "metalness_scale", "metalness_min", "metalness_max",
                    "metalness_blend_target", "metalness_blend_strength",
                    "emissive_intensity", "emissive_color", "material_role", "visible",
                )
            ):
                continue
            ordered = sorted(indices)
            affected.update(ordered)
            group.pop("source_submesh_index", None)
            group["source_submesh_indices"] = ordered
            normalized.append(group)
        return normalized, sorted(affected)

    def apply_resident_material_parameters(
        self,
        groups: Sequence[Mapping[str, object]],
    ) -> bool:
        if not self._dotnet_resident_material_parameter_updates_supported():
            return False
        if not self._standalone_dotnet_editor_process_running():
            return False
        normalized_groups, affected = self._normalized_dotnet_material_parameter_groups(groups)
        if not normalized_groups:
            return False
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            view = controller.session_view()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        session_id = str(view.session_id or "")
        if not session_id:
            return False
        if self.standalone_dotnet_material_parameter_session_id != session_id:
            self.standalone_dotnet_material_parameter_timer.stop()
            self.standalone_dotnet_pending_material_parameter_payload = None
            _material_commit.remember_sent_material_parameters(self, None)
            self.standalone_dotnet_material_parameter_session_id = session_id
            self.standalone_dotnet_material_parameter_generation = 0
            self.standalone_dotnet_sent_material_parameter_generation = 0
            self.standalone_dotnet_applied_material_parameter_generation = 0
            self.standalone_dotnet_completed_material_parameter_generation = 0
        self.standalone_dotnet_material_parameter_generation += 1
        generation = self.standalone_dotnet_material_parameter_generation
        revision = max(0, int(view.revision or 0))
        self.standalone_dotnet_material_parameter_revision = revision
        self.standalone_dotnet_pending_material_parameter_payload = {
            "schema": "cdmw_mesh_material_parameters_v1",
            "version": 1,
            "event": "material_parameter_update",
            "session_id": session_id,
            "edit_revision": revision,
            "parameter_generation": generation,
            "affected_submeshes": affected,
            "groups": normalized_groups,
        }
        self.standalone_dotnet_material_parameter_timer.start(0)
        return True

    def _flush_dotnet_material_parameter_update(self) -> bool:
        payload = self.standalone_dotnet_pending_material_parameter_payload
        self.standalone_dotnet_pending_material_parameter_payload = None
        if payload is None:
            return False
        generation = int(payload.get("parameter_generation", 0) or 0)
        if generation != self.standalone_dotnet_material_parameter_generation:
            return False
        if not self._send_dotnet_protocol_message(payload):
            _material_commit.remember_sent_material_parameters(self, None)
            self.standalone_dotnet_completed_material_parameter_generation = generation
            self.standalone_dotnet_lifecycle_counts["material_parameter_failed_count"] += 1
            self._set_dotnet_status("Could not send resident Mesh Editor material parameters.", error=True)
            return False
        self.standalone_dotnet_sent_material_parameter_generation = generation
        _material_commit.remember_sent_material_parameters(self, payload)
        self.standalone_dotnet_lifecycle_counts["material_parameter_update_count"] += 1
        self._record_mesh_dotnet_event(
            "mesh_dotnet_material_parameter_update",
            parameter_generation=generation,
            edit_revision=int(payload.get("edit_revision", 0) or 0),
            affected_submesh_count=len(tuple(payload.get("affected_submeshes", ()) or ())),
        )
        return True

    def _handle_dotnet_material_parameter_event(
        self,
        payload: Mapping[str, object],
        event: str,
    ) -> bool:
        try:
            generation = int(payload.get("parameter_generation", payload.get("generation", 0)) or 0)
            revision = int(payload.get("edit_revision", payload.get("revision", -1)))
        except (TypeError, ValueError, OverflowError):
            return False
        session_id = str(payload.get("session_id", "") or "").strip()
        if (
            not session_id
            or session_id != self.standalone_dotnet_material_parameter_session_id
            or generation != self.standalone_dotnet_material_parameter_generation
            or generation != self.standalone_dotnet_sent_material_parameter_generation
            or generation <= self.standalone_dotnet_completed_material_parameter_generation
            or revision != self.standalone_dotnet_material_parameter_revision
        ):
            return False
        self.standalone_dotnet_completed_material_parameter_generation = generation
        if event == "material_parameter_applied":
            if not _material_commit.commit_acknowledged_material_parameters(self, payload):
                return False
            self.standalone_dotnet_applied_material_parameter_generation = generation
            self.standalone_dotnet_lifecycle_counts["material_parameter_applied_count"] += 1
            self._set_dotnet_status(
                f"Mesh material parameters applied in the resident .NET session (generation {generation})."
            )
            return True
        _material_commit.remember_sent_material_parameters(self, None)
        self.standalone_dotnet_lifecycle_counts["material_parameter_failed_count"] += 1
        message = str(
            payload.get("message", payload.get("reason", "Material parameter update failed."))
            or "Material parameter update failed."
        )
        self._set_dotnet_status(
            f"Mesh material parameter update failed; keeping the last applied values: {message}",
            error=True,
        )
        return False


__all__ = ["MeshEditorDotNetMaterialParameterMixin"]
