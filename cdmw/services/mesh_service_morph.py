"""Resident procedural morph/refit authority for :class:`MeshService`."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import sys
import time
from typing import Mapping, Sequence
from uuid import uuid4

from cdmw.domain.mesh import (
    MeshEditCommand,
    MeshEditResult,
    MeshMorphDefinition,
    MeshMorphProfile,
    MeshMorphRule,
    MeshMorphState,
    MeshMorphValuePreset,
    MeshRefitBindingSummary,
    build_weighted_morph_selection,
    clamp_morph_value,
    generate_procedural_morph_fields,
    mesh_morph_driver_topology_fingerprint,
    procedural_morph_pivot,
)
from cdmw.modding.mesh_native_core import (
    _native_preview_delta_output_dir,
    native_mesh_core_available,
    native_mesh_editor_session_command,
    native_mesh_editor_session_preview_triangle_groups,
    native_mesh_editor_session_preview_vertex_update_groups,
    open_native_mesh_editor_session,
)
from cdmw.services.mesh_morph_profiles import (
    delete_mesh_morph_preset,
    delete_mesh_morph_profile,
    list_mesh_morph_presets,
    list_mesh_morph_profiles,
    mesh_morph_profile_root,
    save_mesh_morph_preset,
    save_mesh_morph_profile,
)
from cdmw.services.mesh_service_kernel import _apply_native_editor_dirty_counts
from cdmw.services.mesh_service_payloads import _native_editor_metrics
from cdmw.services.mesh_service_reports import (
    _native_editor_dirty_counts_from_report,
    _native_editor_report_affected_indices,
    _native_editor_report_changed_vertices,
)
from cdmw.services.mesh_service_state import _MeshEditSession, _MeshHistorySnapshot


@dataclass(slots=True)
class _MeshMorphSessionData:
    profile: MeshMorphProfile | None = None
    preset_id: str = ""
    diagnostics: tuple[str, ...] = ()
    state: MeshMorphState | None = None
    known_profiles: dict[str, MeshMorphProfile] = field(default_factory=dict)
    available_profile_ids: tuple[str, ...] = ()
    profile_diagnostics: tuple[str, ...] = ()
    profiles_loaded: bool = False
    topology_mesh: object | None = None
    topology_invalidated: bool = False


def _service_call(name: str, *args: object, **kwargs: object) -> object:
    return getattr(sys.modules["cdmw.services.mesh_service"], name)(*args, **kwargs)


class MeshMorphServiceMixin:
    """Keep UI shells thin while the resident C++ session owns deformation."""

    def _apply_morph_edit_command_locked(
        self,
        session: _MeshEditSession,
        command: MeshEditCommand,
    ) -> MeshEditResult:
        action = str(command.action or "").strip().lower()
        params = dict(command.params or {})
        selection = command.selection if command.selection is not None else session.selection
        if action == "morph_refresh":
            self.morph_state(session.session_id)
            return self._result(session, action)
        if action == "morph_activate":
            return self.activate_morph_profile(session.session_id, params.get("profile_id"))[0]
        if action == "morph_author_definition":
            if command.selection is not None:
                session.selection = command.selection
            profile = self.create_morph_definition(
                session.session_id,
                **{key: value for key, value in params.items() if key != "stop_event"},
            )
            data = self._required_morph_data(session)
            return self._activate_morph_profile_locked(session, profile, data.diagnostics)[0]
        if action == "morph_delete_definition":
            return self.delete_morph_definition(session.session_id, params.get("definition_id"))[0]
        if action == "morph_save_profile":
            self.save_active_morph_profile(session.session_id)
            return self._result(session, action)
        if action == "morph_delete_profile":
            deleted, result = self._delete_morph_profile_locked(session, params.get("profile_id"))
            return result if result is not None else self._result(session, action, status="ok" if deleted else "noop")
        if action == "morph_change":
            return self.set_morph_value(
                session.session_id,
                params.get("definition_id"),
                params.get("value"),
                phase=params.get("phase", "end"),
                change_id=params.get("change_id", ""),
            )[0]
        if action == "morph_apply_preset":
            return self.apply_morph_preset(session.session_id, params.get("preset_id"))[0]
        if action == "morph_save_preset":
            self.save_morph_preset(session.session_id, params.get("preset_id"), params.get("name"))
            return self._result(session, action)
        if action == "morph_delete_preset":
            deleted = self.delete_morph_preset(session.session_id, params.get("preset_id"))
            return self._result(session, action, status="ok" if deleted else "noop")
        if action == "morph_set_driver":
            indices = params.get("submesh_indices") or selection.source_indices
            return self.set_refit_driver(session.session_id, tuple(indices or ()))[0]  # type: ignore[arg-type]
        if action == "morph_bind":
            indices = params.get("garment_submesh_indices") or selection.source_indices
            return self.bind_refit(session.session_id, tuple(indices or ()))[0]  # type: ignore[arg-type]
        if action == "morph_clear_refit":
            return self.clear_refit(session.session_id)[0]
        if action == "morph_reset":
            return self.reset_morph(session.session_id)[0]
        if action == "morph_bake":
            return self.bake_morph(session.session_id)[0]
        if action == "morph_finish":
            return self.finish_morph(session.session_id)[0]
        raise ValueError(f"Unsupported procedural morph action: {action}")

    def morph_state(self, session_id: str) -> MeshMorphState:
        session = self._session(session_id)
        with session.export_lock:
            report = self._run_morph_query_locked(session, "morph_state")
            return self._remember_morph_state(
                session,
                self._morph_state_from_report_locked(session, report, refresh_profiles=True),
            )

    def cached_morph_state(self, session_id: str) -> MeshMorphState | None:
        session = self._session(session_id)
        with session.export_lock:
            data = self._morph_sessions.get(session.session_id)
            return data.state if isinstance(data, _MeshMorphSessionData) else None

    def activate_morph_profile(self, session_id: str, profile_id: object) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            profiles, diagnostics = self._profiles_locked(session, refresh_topology=True)
            requested = str(profile_id or "").strip()
            profile = next((item for item in profiles if item.profile_id == requested), None)
            if profile is None:
                raise ValueError(f"Unknown procedural morph profile: {requested or '<empty>'}")
            return self._activate_morph_profile_locked(session, profile, diagnostics)

    def _activate_morph_profile_locked(
        self,
        session: _MeshEditSession,
        profile: MeshMorphProfile,
        diagnostics: tuple[str, ...] = (),
    ) -> tuple[MeshEditResult, MeshMorphState]:
        driver_mesh = self._profile_driver_mesh_locked(session)
        current_fingerprint = mesh_morph_driver_topology_fingerprint(driver_mesh, profile.definitions)
        if profile.topology_fingerprint != current_fingerprint:
            raise RuntimeError("Procedural morph profile topology does not match the active Edit Mesh driver.")
        fields = [
            sparse
            for definition in profile.definitions
            for sparse in generate_procedural_morph_fields(driver_mesh, definition)
        ]
        report = self._run_morph_command_locked(
            session,
            "morph_upload",
            {
                "profile": {
                    "profile_id": profile.profile_id,
                    "name": profile.name,
                    "topology_fingerprint": profile.topology_fingerprint,
                    "definitions": [
                        {
                            "definition_id": definition.definition_id,
                            "label": definition.label,
                            "category": definition.category,
                            "min_percent": definition.min_percent,
                            "max_percent": definition.max_percent,
                            "default_percent": definition.default_percent,
                        }
                        for definition in profile.definitions
                    ],
                    "fields": [
                        {
                            "definition_id": sparse.definition_id,
                            "submesh_index": sparse.submesh_index,
                            "vertex_indices": list(sparse.vertex_indices),
                            "deltas": [list(delta) for delta in sparse.deltas],
                        }
                        for sparse in fields
                    ],
                }
            },
            history_label="Select Morph Profile",
            record_history=False,
        )
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        data.profile = profile
        data.preset_id = ""
        data.diagnostics = tuple(diagnostics)
        data.known_profiles[profile.profile_id] = profile
        data.available_profile_ids = tuple(dict.fromkeys((*data.available_profile_ids, profile.profile_id)))
        data.topology_invalidated = False
        return self._morph_result_and_state_locked(session, "morph_upload", report)

    def create_morph_definition(
        self,
        session_id: str,
        *,
        profile_id: object,
        profile_name: object,
        definition_id: object,
        label: object,
        category: object = "General",
        rule: object = "volume",
        axis: object = "y",
        amount: object = 0.1,
        feather: object = 2,
        falloff: object = "smooth",
        mirror_mode: object = "off",
        min_percent: object = -100.0,
        max_percent: object = 100.0,
        default_percent: object = 0.0,
        local_basis: Sequence[Sequence[object]] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        preserve_selection: object = False,
        source_definition_id: object = "",
    ) -> MeshMorphProfile:
        session = self._session(session_id)
        with session.export_lock:
            self._require_baked_morph_definition_edit(session)
            mesh = self._working_mesh_locked(session, clone=False)
            requested_profile_id = str(profile_id or "").strip() or f"profile-{uuid4().hex[:10]}"
            requested_definition_id = str(definition_id or "").strip()
            original_definition_id = str(source_definition_id or requested_definition_id).strip()
            data = self._morph_sessions.get(session.session_id)
            profiles, _diagnostics = self._profiles_locked(session, refresh_topology=True)
            existing = (
                data.profile
                if isinstance(data, _MeshMorphSessionData)
                and data.profile is not None
                and data.profile.profile_id == requested_profile_id
                else next((item for item in profiles if item.profile_id == requested_profile_id), None)
            )
            existing_definition = next(
                (
                    item
                    for item in (existing.definitions if existing is not None else ())
                    if item.definition_id == original_definition_id
                ),
                None,
            )
            preserve_existing_selection = preserve_selection is True or str(preserve_selection).strip().lower() in {"1", "true", "yes", "on"}
            if preserve_existing_selection:
                if existing_definition is None:
                    raise ValueError(f"Unknown procedural morph definition: {original_definition_id or '<empty>'}")
                weighted = existing_definition.vertices
                pivot = existing_definition.pivot
                definition_basis = existing_definition.local_basis
            else:
                selected = session.selection.vertex_map()
                if not selected:
                    raise ValueError("Author Slider requires a vertex selection in the existing Edit Mesh view.")
                weighted = build_weighted_morph_selection(
                    mesh,
                    selected,
                    feather=max(0, int(feather)),
                    falloff=str(falloff or "smooth"),
                    mirror_mode=str(mirror_mode or "off"),
                )
                pivot = procedural_morph_pivot(mesh, weighted)
                definition_basis = tuple(tuple(float(value) for value in basis[:3]) for basis in local_basis)
            definition = MeshMorphDefinition(
                definition_id=requested_definition_id,
                label=str(label or "").strip(),
                category=str(category or "General").strip(),
                vertices=weighted,
                pivot=pivot,
                local_basis=definition_basis,  # type: ignore[arg-type]
                rule=MeshMorphRule(
                    kind=str(rule or "volume"),
                    axis=str(axis or "y"),
                    amount=float(amount),
                    falloff=str(falloff or "smooth"),
                    feather=max(0, int(feather)),
                ),
                mirror_mode=str(mirror_mode or "off"),
                min_percent=float(min_percent),
                max_percent=float(max_percent),
                default_percent=float(default_percent),
            )
            definitions = [
                item
                for item in (existing.definitions if existing is not None else ())
                if item.definition_id not in {original_definition_id, definition.definition_id}
            ]
            definitions.append(definition)
            profile = MeshMorphProfile(
                profile_id=requested_profile_id,
                name=str(profile_name or (existing.name if existing is not None else requested_profile_id)).strip(),
                topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, definitions),
                definitions=tuple(definitions),
            )
            if not isinstance(data, _MeshMorphSessionData):
                data = _MeshMorphSessionData()
                self._morph_sessions[session.session_id] = data
            data.profile = profile
            data.known_profiles[profile.profile_id] = profile
            data.available_profile_ids = tuple(dict.fromkeys((*data.available_profile_ids, profile.profile_id)))
            data.topology_mesh = mesh
            data.topology_invalidated = False
            return profile

    def delete_morph_definition(
        self,
        session_id: str,
        definition_id: object,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            self._require_baked_morph_definition_edit(session)
            data = self._required_morph_data(session)
            key = str(definition_id or "").strip()
            definitions = tuple(
                definition
                for definition in data.profile.definitions  # type: ignore[union-attr]
                if definition.definition_id != key
            )
            if len(definitions) == len(data.profile.definitions):  # type: ignore[union-attr]
                raise ValueError(f"Unknown procedural morph definition: {key or '<empty>'}")
            driver_mesh = self._profile_driver_mesh_locked(session)
            profile = replace(  # type: ignore[arg-type]
                data.profile,
                definitions=definitions,
                topology_fingerprint=mesh_morph_driver_topology_fingerprint(driver_mesh, definitions),
            )
            data.profile = profile
            data.known_profiles[profile.profile_id] = profile
            return self._activate_morph_profile_locked(session, profile, data.diagnostics)

    def save_active_morph_profile(self, session_id: str) -> MeshMorphProfile:
        session = self._session(session_id)
        with session.export_lock:
            data = self._morph_sessions.get(session.session_id)
            if not isinstance(data, _MeshMorphSessionData) or data.profile is None:
                raise RuntimeError("No procedural morph profile is active.")
            profile = replace(data.profile, migrated_from_version=0, requires_v2_save=False)
            save_mesh_morph_profile(self._profile_root(), profile)
            data.profile = profile
            data.known_profiles[profile.profile_id] = profile
            data.available_profile_ids = tuple(dict.fromkeys((*data.available_profile_ids, profile.profile_id)))
            self._refresh_cached_morph_metadata_locked(session)
            return profile

    def delete_morph_profile(self, session_id: str, profile_id: object) -> bool:
        session = self._session(session_id)
        with session.export_lock:
            deleted, _result = self._delete_morph_profile_locked(session, profile_id)
            return deleted

    def _delete_morph_profile_locked(
        self,
        session: _MeshEditSession,
        profile_id: object,
    ) -> tuple[bool, MeshEditResult | None]:
        profile_key = str(profile_id or "").strip()
        deleted = delete_mesh_morph_profile(self._profile_root(), profile_key)
        data = self._morph_sessions.get(session.session_id)
        result: MeshEditResult | None = None
        if deleted and isinstance(data, _MeshMorphSessionData) and data.profile is not None and data.profile.profile_id == profile_key:
            reset_report = self._run_morph_command_locked(
                session,
                "morph_reset",
                {"suppress_history": True},
                history_label="Reset Morph",
                record_history=False,
            )
            result, _state = self._morph_result_and_state_locked(session, "morph_delete_profile", reset_report)
            self._run_morph_command_locked(
                session,
                "morph_upload",
                {"profile": {}},
                history_label="Clear Morph Profile",
                record_history=False,
            )
            data.profile = None
            data.preset_id = ""
        if deleted and isinstance(data, _MeshMorphSessionData):
            data.known_profiles.pop(profile_key, None)
            data.available_profile_ids = tuple(
                item for item in data.available_profile_ids if item != profile_key
            )
            self._refresh_cached_morph_metadata_locked(session)
        return deleted, result

    def set_morph_value(
        self,
        session_id: str,
        definition_id: object,
        value: object,
        *,
        phase: object = "end",
        change_id: object = "",
    ) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            definition_key = str(definition_id or "").strip()
            definition = next((item for item in data.profile.definitions if item.definition_id == definition_key), None)  # type: ignore[union-attr]
            if definition is None:
                raise ValueError(f"Unknown procedural morph definition: {definition_key or '<empty>'}")
            normalized_phase = str(phase or "end").strip().lower()
            report = self._run_morph_command_locked(
                session,
                "morph_change",
                {
                    "definition_id": definition.definition_id,
                    "value": clamp_morph_value(definition, value),
                    "phase": normalized_phase,
                    "change_id": str(change_id or "").strip() or f"morph-{uuid4().hex}",
                },
                history_label=f"Morph {definition.label}",
                record_history=normalized_phase != "cancel",
            )
            return self._morph_result_and_state_locked(session, "morph_change", report)

    def apply_morph_preset(self, session_id: str, preset_id: object) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            presets, diagnostics = list_mesh_morph_presets(self._profile_root(), data.profile)  # type: ignore[arg-type]
            requested = str(preset_id or "").strip()
            preset = next((item for item in presets if item.preset_id == requested), None)
            if preset is None:
                raise ValueError(f"Unknown procedural morph preset: {requested or '<empty>'}")
            report = self._run_morph_command_locked(
                session,
                "morph_apply_preset",
                {"preset_id": preset.preset_id, "values": {key: value for key, value in preset.values}},
                history_label=f"Apply Morph Preset {preset.name}",
                record_history=True,
            )
            data.preset_id = preset.preset_id
            data.diagnostics = tuple(dict.fromkeys((*data.diagnostics, *diagnostics)))
            return self._morph_result_and_state_locked(session, "morph_apply_preset", report)

    def save_morph_preset(self, session_id: str, preset_id: object, name: object) -> MeshMorphValuePreset:
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            report = self._run_morph_query_locked(session, "morph_state")
            values = _morph_values_from_report(report)
            preset = MeshMorphValuePreset(
                preset_id=str(preset_id or "").strip(),
                name=str(name or preset_id or "").strip(),
                profile_id=data.profile.profile_id,  # type: ignore[union-attr]
                topology_fingerprint=data.profile.topology_fingerprint,  # type: ignore[union-attr]
                values=tuple(values.items()),
            )
            save_mesh_morph_preset(self._profile_root(), preset)
            data.preset_id = preset.preset_id
            self._remember_morph_state(
                session,
                self._morph_state_from_report_locked(session, report),
            )
            return preset

    def delete_morph_preset(self, session_id: str, preset_id: object) -> bool:
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            deleted = delete_mesh_morph_preset(self._profile_root(), data.profile.profile_id, preset_id)  # type: ignore[union-attr]
            if deleted and data.preset_id == str(preset_id or ""):
                data.preset_id = ""
            if deleted:
                self._refresh_cached_morph_metadata_locked(session)
            return deleted

    def set_refit_driver(self, session_id: str, submesh_indices: Sequence[object]) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_set_driver", {"submesh_indices": _indices(submesh_indices)}, "Set Refit Driver", False)

    def bind_refit(self, session_id: str, garment_submesh_indices: Sequence[object]) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_bind", {"garment_submesh_indices": _indices(garment_submesh_indices)}, "Bind Garment Refit", True)

    def clear_refit(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_clear_refit", {}, "Clear Garment Refit", True)

    def reset_morph(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_reset", {}, "Reset Morph", True)

    def bake_morph(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_bake", {}, "Bake Morph", True)

    def finish_morph(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_finish", {}, "Finish Morph", True)

    def _simple_morph_command(
        self,
        session_id: str,
        command: str,
        payload: Mapping[str, object],
        history_label: str,
        record_history: bool,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            report = self._run_morph_command_locked(session, command, payload, history_label=history_label, record_history=record_history)
            return self._morph_result_and_state_locked(session, command, report)

    def _profile_root(self):
        return mesh_morph_profile_root(self.settings)

    def _profile_driver_mesh_locked(self, session: _MeshEditSession) -> object:
        data = self._morph_sessions.get(session.session_id)
        if isinstance(data, _MeshMorphSessionData) and data.topology_mesh is not None:
            return data.topology_mesh
        return session.base_mesh

    def _profiles_locked(
        self,
        session: _MeshEditSession,
        *,
        refresh_topology: bool = False,
    ) -> tuple[tuple[MeshMorphProfile, ...], tuple[str, ...]]:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        if data.topology_invalidated:
            if not refresh_topology:
                return (), tuple(dict.fromkeys((*data.diagnostics, "Topology changed; procedural profiles and refit bindings were invalidated.")))
            data.topology_mesh = self._working_mesh_locked(session, clone=False)
            data.topology_invalidated = False
            data.profiles_loaded = False
            data.available_profile_ids = ()
        if data.profiles_loaded and not refresh_topology:
            cached = tuple(
                data.known_profiles[profile_id]
                for profile_id in data.available_profile_ids
                if profile_id in data.known_profiles
            )
            return tuple(sorted(cached, key=lambda item: (item.name.casefold(), item.profile_id))), data.profile_diagnostics
        mesh = self._profile_driver_mesh_locked(session)
        profiles, diagnostics = list_mesh_morph_profiles(self._profile_root(), mesh)
        merged = {profile.profile_id: profile for profile in profiles}
        if data.profile is not None:
            merged[data.profile.profile_id] = data.profile
        ordered = tuple(sorted(merged.values(), key=lambda item: (item.name.casefold(), item.profile_id)))
        data.known_profiles.update(merged)
        data.available_profile_ids = tuple(profile.profile_id for profile in ordered)
        data.profile_diagnostics = tuple(diagnostics)
        data.profiles_loaded = True
        return ordered, diagnostics

    def _require_baked_morph_definition_edit(self, session: _MeshEditSession) -> None:
        data = self._morph_sessions.get(session.session_id)
        if isinstance(data, _MeshMorphSessionData) and data.state is not None and data.state.unbaked:
            raise RuntimeError("Bake or Reset active Morph & Refit values before editing profile definitions.")

    def _required_morph_data(self, session: _MeshEditSession) -> _MeshMorphSessionData:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData) or data.profile is None:
            raise RuntimeError("Select a procedural morph profile first.")
        return data

    def _invalidate_morph_after_topology_locked(self, session: _MeshEditSession) -> None:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            # Ordinary Edit Mesh sessions must stay independent of Morph & Refit
            # persistence. A later first morph-state request will load profiles
            # against the then-current topology, so there is nothing to
            # invalidate until this session has actually used the feature.
            return
        if data.profile is not None:
            data.known_profiles[data.profile.profile_id] = data.profile
        data.profile = None
        data.preset_id = ""
        data.topology_mesh = None
        data.topology_invalidated = True
        data.profiles_loaded = False
        data.available_profile_ids = ()
        data.diagnostics = tuple(dict.fromkeys((*data.diagnostics, "Topology changed; procedural profiles and refit bindings were invalidated.")))
        try:
            data.topology_mesh = self._working_mesh_locked(session, clone=False)
            data.topology_invalidated = False
            report = self._run_morph_query_locked(session, "morph_state")
            self._remember_morph_state(
                session,
                self._morph_state_from_report_locked(session, report, refresh_profiles=False),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            previous_revision = data.state.state_revision if data.state is not None else 0
            data.state = MeshMorphState(
                session_id=session.session_id,
                diagnostics=data.diagnostics,
                failure=f"Procedural profile compatibility refresh failed after topology changed: {exc}",
                state_revision=previous_revision + 1,
                edit_revision=session.revision,
                change_id="topology-invalidated",
            )

    def _refresh_cached_morph_after_history_locked(
        self,
        session: _MeshEditSession,
        *,
        topology_changed: bool,
    ) -> None:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            return
        if topology_changed:
            data.topology_mesh = self._working_mesh_locked(session, clone=False)
            data.topology_invalidated = False
            data.profiles_loaded = False
            data.available_profile_ids = ()
        report = self._run_morph_query_locked(session, "morph_state")
        self._remember_morph_state(
            session,
            self._morph_state_from_report_locked(session, report, refresh_profiles=False),
        )

    def _refresh_cached_morph_metadata_locked(self, session: _MeshEditSession) -> MeshMorphState:
        report = self._run_morph_query_locked(session, "morph_state")
        return self._remember_morph_state(
            session,
            self._morph_state_from_report_locked(session, report, refresh_profiles=False),
        )

    def _ensure_native_morph_session_locked(self, session: _MeshEditSession) -> None:
        if not native_mesh_core_available():
            raise RuntimeError("Procedural Morph & Refit requires the resident C++ mesh core.")
        _service_call("_refresh_native_editor_session_if_mesh_changed", session)
        if session.native_editor_session_ready:
            return
        if session.native_editor_mesh_dirty:
            raise RuntimeError("Resident C++ mesh state is dirty and cannot be reopened from stale Python geometry.")
        opened = open_native_mesh_editor_session(session.working_mesh, session.session_id, timeout_seconds=10.0)
        if opened is None:
            raise RuntimeError("Resident C++ Edit Mesh session failed to open.")
        session.native_editor_session_ready = True
        session.native_editor_selection_signature = ()
        session.native_editor_active_stroke_id = ""
        session.native_editor_mesh_signature = _service_call("_native_editor_mesh_storage_signature", session.working_mesh)  # type: ignore[assignment]

    def _run_morph_query_locked(self, session: _MeshEditSession, command: str) -> Mapping[str, object]:
        self._ensure_native_morph_session_locked(session)
        report = native_mesh_editor_session_command(command, session.session_id, timeout_seconds=5.0)
        if not isinstance(report, Mapping) or str(report.get("status") or "").lower() != "ok":
            raise RuntimeError(_report_error(report, f"Resident C++ {command} failed."))
        return report

    def _run_morph_command_locked(
        self,
        session: _MeshEditSession,
        command: str,
        payload: Mapping[str, object],
        *,
        history_label: str,
        record_history: bool,
    ) -> Mapping[str, object]:
        self._ensure_native_morph_session_locked(session)
        request = dict(payload)
        request["delta_output_dir"] = _native_preview_delta_output_dir()
        request["include_edit_report"] = True
        started = time.perf_counter()
        report = native_mesh_editor_session_command(command, session.session_id, request, timeout_seconds=30.0)
        if not isinstance(report, Mapping) or str(report.get("status") or "").lower() != "ok":
            raise RuntimeError(_report_error(report, f"Resident C++ {command} failed."))
        metrics = _native_editor_metrics(report)
        metrics["native_morph_roundtrip_ms"] = max(0.0, (time.perf_counter() - started) * 1000.0)
        if command == "morph_change" and str(payload.get("phase") or "").strip().lower() == "cancel":
            change_id = str(payload.get("change_id") or "").strip()
            if (
                change_id
                and session.undo_stack
                and session.undo_stack[-1].native_editor_history
                and session.undo_stack[-1].native_editor_stroke_id == change_id
            ):
                _service_call("_discard_history_snapshot", session.undo_stack)
        history_published = bool(report.get("history_published")) and record_history
        if history_published:
            self._push_history_snapshot(
                session,
                _MeshHistorySnapshot(
                    mesh=None,
                    mode=session.mode,
                    selection=session.selection,
                    edit_operations=tuple(session.edit_operations),
                    native_editor_history=True,
                    native_editor_stroke_id=str(report.get("change_id") or ""),
                    history_action=command,
                    history_label=history_label,
                ),
            )
        _service_call("_update_native_history_usage", session, metrics)
        return report

    def _morph_result_and_state_locked(
        self,
        session: _MeshEditSession,
        action: str,
        report: Mapping[str, object],
    ) -> tuple[MeshEditResult, MeshMorphState]:
        counts = _native_editor_dirty_counts_from_report(report, current_submesh_count=len(session.working_mesh.submeshes))
        affected = _native_editor_report_affected_indices(report, len(counts) if counts else len(session.working_mesh.submeshes))
        changed = _native_editor_report_changed_vertices(report, counts or tuple((len(submesh.vertices), len(submesh.faces)) for submesh in session.working_mesh.submeshes))
        preview_vertices = native_mesh_editor_session_preview_vertex_update_groups(report)
        preview_triangles = native_mesh_editor_session_preview_triangle_groups(report)
        if affected or changed:
            if not counts:
                raise RuntimeError("Resident C++ morph report omitted submesh counts.")
            session.native_editor_mesh_dirty = True
            session.native_editor_mesh_dirty_counts = counts
            _apply_native_editor_dirty_counts(session)
            session.revision += 1
        metrics = _native_editor_metrics(report)
        result = self._result(
            session,
            action,
            affected=affected,
            changed=changed,
            native_preview_vertex_update_groups=preview_vertices,
            native_preview_triangle_groups=preview_triangles,
            diagnostics=tuple(str(item) for item in tuple(report.get("diagnostics") or ()) if str(item).strip()),
            metrics=metrics,
        )
        return result, self._remember_morph_state(session, self._morph_state_from_report_locked(session, report))

    def _remember_morph_state(self, session: _MeshEditSession, state: MeshMorphState) -> MeshMorphState:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        if data.state is not None and state.state_revision <= data.state.state_revision:
            state = replace(state, state_revision=data.state.state_revision + 1)
        data.state = state
        return state

    def _morph_state_from_report_locked(
        self,
        session: _MeshEditSession,
        report: Mapping[str, object],
        *,
        refresh_profiles: bool = False,
    ) -> MeshMorphState:
        data = self._morph_sessions.get(session.session_id)
        profiles, profile_diagnostics = self._profiles_locked(
            session,
            refresh_topology=refresh_profiles,
        )
        native_state = report.get("morph_state")
        raw_state = native_state if isinstance(native_state, Mapping) else report
        active_profile_id = str(raw_state.get("profile_id") or "")
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        profile = data.known_profiles.get(active_profile_id) if active_profile_id else None
        if profile is None and active_profile_id:
            profile = next((item for item in profiles if item.profile_id == active_profile_id), None)
        data.profile = profile
        if profile is not None:
            data.known_profiles[profile.profile_id] = profile
        presets, preset_diagnostics = list_mesh_morph_presets(self._profile_root(), profile) if profile is not None else ((), ())
        raw_preset_id = str(raw_state.get("preset_id") or "")
        available_preset_ids = {preset.preset_id for preset in presets}
        data.preset_id = raw_preset_id if raw_preset_id in available_preset_ids else ""
        raw_refit = raw_state.get("refit")
        refit = raw_refit if isinstance(raw_refit, Mapping) else {}
        diagnostics = tuple(dict.fromkeys(
            str(item)
            for item in (
                *data.diagnostics,
                *profile_diagnostics,
                *preset_diagnostics,
                *(tuple(raw_state.get("diagnostics") or ())),
            )
            if str(item).strip()
        ))
        return MeshMorphState(
            session_id=session.session_id,
            profile_id=active_profile_id,
            preset_id=data.preset_id,
            topology_fingerprint=(profile.topology_fingerprint if profile is not None else ""),
            definitions=(profile.definitions if profile is not None else ()),
            values=tuple(sorted(_morph_values_from_report(raw_state).items())),
            available_profiles=tuple((item.profile_id, item.name) for item in profiles),
            available_presets=tuple((item.preset_id, item.name) for item in presets),
            driver_submesh_indices=_indices(raw_state.get("driver_submesh_indices") or ()),
            refit=MeshRefitBindingSummary(
                driver_submesh_indices=_indices(refit.get("driver_submesh_indices") or ()),
                garment_submesh_indices=_indices(refit.get("garment_submesh_indices") or ()),
                bound_vertex_count=int(refit.get("bound_vertex_count", 0) or 0),
                maximum_distance=float(refit.get("maximum_distance", 0.0) or 0.0),
                p95_distance=float(refit.get("p95_distance", 0.0) or 0.0),
                warning_distance=float(refit.get("warning_distance", 0.0) or 0.0),
                distance_warning=bool(refit.get("distance_warning")),
            ),
            unbaked=bool(raw_state.get("unbaked")),
            topology_blocked=bool(raw_state.get("topology_blocked")),
            busy=bool(raw_state.get("busy")),
            failure=str(raw_state.get("failure") or ""),
            diagnostics=diagnostics,
            state_revision=int(raw_state.get("state_revision", 0) or 0),
            edit_revision=int(raw_state.get("edit_revision", session.revision) or 0),
            change_id=str(raw_state.get("change_id") or ""),
        )


def _indices(values: object) -> tuple[int, ...]:
    result: set[int] = set()
    for value in tuple(values or ()):  # type: ignore[arg-type]
        try:
            index = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0:
            result.add(index)
    return tuple(sorted(result))


def _morph_values_from_report(report: Mapping[str, object]) -> dict[str, float]:
    raw_values = report.get("values")
    if not isinstance(raw_values, Mapping):
        raw_state = report.get("morph_state")
        raw_values = raw_state.get("values") if isinstance(raw_state, Mapping) else None
    values: dict[str, float] = {}
    if isinstance(raw_values, Mapping):
        for raw_key, raw_value in raw_values.items():
            try:
                values[str(raw_key)] = float(raw_value)
            except (TypeError, ValueError, OverflowError):
                continue
    return values


def _report_error(report: object, fallback: str) -> str:
    if isinstance(report, Mapping):
        for key in ("error", "failure", "message"):
            value = str(report.get(key) or "").strip()
            if value:
                return value
    return fallback


__all__ = ["MeshMorphServiceMixin"]
