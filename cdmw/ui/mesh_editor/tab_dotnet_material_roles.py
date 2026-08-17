"""Per-role material readiness for the resident Mesh Editor panes.

Split out of :mod:`tab_dotnet_resources` to keep that module inside the owned
file cap. Everything here answers one of two questions about a single resident
role: is this pane textured yet, and if not, what stage is it stopped at.

The distinction that matters is between the *active* role and the *required*
ones. Display mode is one viewport-wide message, so a two-pane scene applies it
to both panes and a pane whose materials are not resident simply draws
untextured. Making a textured request wait for every role therefore bought
nothing visible and cost the reader the pane that was ready: an Original pane
that failed, or that was still compiling a full character's archive textures,
held the Imported mesh grey behind it until the watchdog gave up.
"""

from __future__ import annotations

from typing import Sequence

from cdmw.services.mesh_material_publication import normalize_material_role


class MeshEditorDotNetMaterialRoleMixin:
    @staticmethod
    def _dotnet_material_role_key(role: object) -> str:
        return normalize_material_role(role)

    @staticmethod
    def _dotnet_material_role_label(role: str) -> str:
        return "Original" if role == "original_reference" else "Imported"

    def _dotnet_comparison_mode(self) -> str:
        return str(
            (getattr(self, "standalone_dotnet_scene_desired", None) or {}).get(
                "comparison_mode",
                "replacement_only",
            )
            or "replacement_only"
        ).strip().lower()

    def _dotnet_active_material_role(self) -> str:
        """The pane a textured request is really about."""

        return (
            "original_reference"
            if self._dotnet_comparison_mode() == "original_only"
            else "editable_imported"
        )

    def _dotnet_required_material_roles(self) -> tuple[str, ...]:
        """Every pane the scene will eventually texture."""

        package = getattr(self, "standalone_dotnet_experiment_package", None)
        try:
            has_reference = int(getattr(package, "reference_submesh_count", 0) or 0) > 0
        except (TypeError, ValueError):
            has_reference = False
        return (
            ("editable_imported", "original_reference")
            if has_reference
            else ("editable_imported",)
        )

    def _dotnet_material_role_ready(self, role: object) -> bool:
        key = normalize_material_role(role)
        applied = int(
            self.standalone_dotnet_applied_material_generation_by_role.get(key, 0) or 0
        )
        desired = int(self.standalone_dotnet_material_generation_by_role.get(key, 0) or 0)
        completed = int(
            self.standalone_dotnet_completed_material_generation_by_role.get(key, 0) or 0
        )
        return (
            applied > 0
            and applied >= desired
            and completed >= desired
            and bool(self.standalone_dotnet_texture_resources_ready_by_role.get(key, False))
        )

    def _dotnet_active_material_role_ready(self) -> bool:
        return self._dotnet_material_role_ready(self._dotnet_active_material_role())

    def _dotnet_material_roles_ready(self) -> bool:
        return all(
            self._dotnet_material_role_ready(role)
            for role in self._dotnet_required_material_roles()
        )

    def _dotnet_missing_material_roles(self) -> tuple[str, ...]:
        return tuple(
            role
            for role in self._dotnet_required_material_roles()
            if not self._dotnet_material_role_ready(role)
        )

    def _dotnet_material_role_stage(self, role: object) -> str:
        """Where this pane's materials are, as one word."""

        key = normalize_material_role(role)
        if str(self.standalone_dotnet_material_error_by_role.get(key, "") or ""):
            return "failed"
        if self._dotnet_material_role_ready(key):
            return "textured"
        publications = self.standalone_dotnet_material_publications
        if publications.has_pending_role(key):
            # A publication that has left the compiler and is waiting on the
            # renderer is a different wait from one that is still compiling.
            return "compiling" if publications.is_busy() else "publishing"
        applied = int(
            self.standalone_dotnet_applied_material_generation_by_role.get(key, 0) or 0
        )
        if applied > 0 and not bool(
            self.standalone_dotnet_texture_resources_ready_by_role.get(key, False)
        ):
            return "no_textures"
        return "not_published"

    def _dotnet_material_role_status(self, role: str) -> dict[str, object]:
        """Everything a pane needs to say why it is or is not textured."""

        key = normalize_material_role(role)
        return {
            "role": key,
            "active": key == self._dotnet_active_material_role(),
            "required": key in self._dotnet_required_material_roles(),
            "stage": self._dotnet_material_role_stage(key),
            "desired_generation": int(
                self.standalone_dotnet_material_generation_by_role.get(key, 0) or 0
            ),
            "completed_generation": int(
                self.standalone_dotnet_completed_material_generation_by_role.get(key, 0) or 0
            ),
            "applied_generation": int(
                self.standalone_dotnet_applied_material_generation_by_role.get(key, 0) or 0
            ),
            "resources_ready": bool(
                self.standalone_dotnet_texture_resources_ready_by_role.get(key, False)
            ),
            "error": str(self.standalone_dotnet_material_error_by_role.get(key, "") or ""),
        }

    def _dotnet_material_role_blocking_reason(self, role: str) -> str:
        """One line naming why this pane is not textured, or empty when it is.

        This is diagnostic text, not a status-bar string: it names the stage and
        the compiler's own message so a bundle says which of the four different
        waits a grey pane was in. The catalogued status line stays separate.
        """

        key = normalize_material_role(role)
        label = self._dotnet_material_role_label(key)
        stage = self._dotnet_material_role_stage(key)
        if stage == "textured":
            return ""
        if stage == "failed":
            detail = str(self.standalone_dotnet_material_error_by_role.get(key, "") or "")
            return f"{label} pane material update failed: {detail}"
        if stage == "compiling":
            return f"Compiling {label} pane materials."
        if stage == "publishing":
            return f"Uploading {label} pane textures."
        if stage == "no_textures":
            return f"No resolved textures are available for the {label} pane."
        return f"{label} pane materials have not been published yet."

    def _dotnet_material_roles_for_generation(
        self,
        generation: int,
        fallback_role: object = "replacement",
    ) -> tuple[str, ...]:
        stored = self.standalone_dotnet_material_role_by_generation.get(generation)
        if isinstance(stored, str):
            return (stored,)
        if isinstance(stored, Sequence):
            roles = tuple(
                self._dotnet_material_role_key(role)
                for role in stored
                if str(role or "").strip()
            )
            if roles:
                return roles
        return (self._dotnet_material_role_key(fallback_role),)


__all__ = ["MeshEditorDotNetMaterialRoleMixin"]
