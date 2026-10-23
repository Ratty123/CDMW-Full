"""Explicit, staged restoration from a verified matching unbaked PAC."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import copy
import hashlib
from pathlib import Path

from cdmw.domain.mesh.islands import mesh_islands
from cdmw.domain.mesh.morph_targets import match_refit_shape_source
from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE
from cdmw.domain.mesh.topology import SubmeshTopologyProvenance, validate_topology_provenance


@dataclass(slots=True)
class _RefitShapeRestorePreview:
    history: object
    base_revision: int
    preview_revision: int
    source_name: str
    source_sha256: str
    parts: tuple[int, ...]
    vertex_count: int
    scope: tuple[tuple[int, str, int], ...]
    autosave_pending: bool


class MeshRefitRecoveryMixin:
    def _require_no_pending_refit_shape_restore_locked(self, session):
        if session.session_id in self._refit_shape_recoveries:
            raise RuntimeError("Apply or Cancel Restore fitting shape before editing or finishing.")

    def _refit_shape_restore_state_fields_locked(self, session):
        pending = self._refit_shape_recoveries.get(session.session_id)
        return {
            "shape_restore_source": pending.source_name if pending else "",
            "shape_restore_sha256": pending.source_sha256 if pending else "",
            "shape_restore_parts": pending.parts if pending else (),
            "shape_restore_vertex_count": pending.vertex_count if pending else 0,
            "shape_restore_scope": pending.scope if pending else (),
        }

    def _refit_shape_restore_reference_locked(self, session, index, current, neutral_appearance=None):
        """Resolve the immutable loaded source and its existing display frame."""
        context = session.archive_refit_context
        if context is not None:
            matches = [(asset, asset.part_indices.index(index)) for asset in context.assets if index in asset.part_indices]
            if len(matches) != 1:
                raise ValueError(f"Restore fitting shape: Part {index} has lost its source asset identity.")
            asset, local = matches[0]
            if asset.role == "body":
                raise ValueError(f"Restore fitting shape: Part {index} is a body Part.")
            return asset.source.mesh.submeshes[local], asset.neutral_appearance if context.neutral_coordinates else None
        state = session.replacement_state
        if state is not None:
            part_id = getattr(current, PART_ID_ATTRIBUTE, "")
            bindings = [part for part in state.parts if part.part_id == part_id]
            if len(bindings) != 1:
                raise ValueError(f"Restore fitting shape: Part {index} has lost its source identity.")
            index = bindings[0].target_index
        if index >= len(session.base_mesh.submeshes):
            raise ValueError(f"Restore fitting shape: Part {index} has no loaded source identity.")
        appearance = state.neutral_appearance if state is not None and state.neutral_coordinates else neutral_appearance
        return session.base_mesh.submeshes[index], appearance

    def preview_refit_shape_restore(self, session_id, path, submesh_indices=(), *, islands=(), stop_event=None, _neutral_appearance=None):
        from cdmw.domain.cancellation import raise_if_cancelled
        from cdmw.services.mesh_service_morph_authoring import _strict_indices
        from cdmw.services.mesh_service_morph import native_mesh_editor_session_command, _report_error
        from cdmw.modding.mesh_native_core import _native_preview_delta_output_dir, last_native_mesh_core_job_error

        session = self._session(session_id)
        with session.export_lock:
            raise_if_cancelled(stop_event)
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            self._require_no_pending_refit_shape_restore_locked(session)
            state = self._refresh_cached_morph_metadata_locked(session)
            if state.unbaked:
                raise ValueError("Bake or Reset the current preview before restoring fitting shape.")
            current = self._working_mesh_locked(session, clone=True)
            count = len(current.submeshes)
            whole = _strict_indices(submesh_indices, label="Restore garment Parts", count=count, nonempty=False)
            selected_faces = {index: set(range(len(current.submeshes[index].faces))) for index in whole}
            island_counts = {}
            for row in tuple(islands or ()):
                if not isinstance(row, dict):
                    raise ValueError("Restore fitting shape requires explicit island identities.")
                index = _strict_indices((row.get("submesh_index"),), label="Restore island Part", count=count)[0]
                faces = _strict_indices(row.get("face_indices", ()), label=f"Part {index} restore island faces",
                                        count=len(current.submeshes[index].faces))
                if frozenset(faces) not in {frozenset(group) for group in mesh_islands(current.submeshes[index])}:
                    raise ValueError(f"Restore fitting shape: Part {index} has a stale island identity.")
                selected_faces.setdefault(index, set()).update(faces)
                island_counts[index] = island_counts.get(index, 0) + 1
            if not selected_faces:
                raise ValueError("Select garment Parts or islands before restoring fitting shape.")
            if set(selected_faces).intersection(state.driver_submesh_indices):
                raise ValueError("Restore fitting shape cannot replace body Parts.")
            source_path = Path(str(path or "")).expanduser()
            if source_path.suffix.casefold() != ".pac":
                raise ValueError("Choose a matching unbaked PAC for Restore fitting shape.")
            raw = source_path.read_bytes()
            raise_if_cancelled(stop_event)
            source = self.load_mesh_bytes(raw, source_path, run_roundtrip=True)
            raise_if_cancelled(stop_event)
            reference = copy.copy(current)
            reference.submeshes = list(current.submeshes)
            appearances = {}
            for index in selected_faces:
                reference.submeshes[index], appearances[index] = self._refit_shape_restore_reference_locked(
                    session, index, current.submeshes[index], _neutral_appearance)
            matches = dict(match_refit_shape_source(reference, source, submesh_indices=selected_faces))
            bindings = {part.part_id: part for part in session.replacement_state.parts} if session.replacement_state else {}
            restored = []
            scope = []
            for index, selected in sorted(selected_faces.items()):
                part, seed = current.submeshes[index], reference.submeshes[index]
                binding = bindings.get(getattr(part, PART_ID_ATTRIBUTE, ""))
                if binding is not None and not binding.included:
                    continue
                mapping, original = tuple(part.source_vertex_map), tuple(seed.source_vertex_map)
                provenance = getattr(part, "topology_provenance", None)
                if isinstance(provenance, SubmeshTopologyProvenance):
                    if (validate_topology_provenance(provenance, output_vertex_count=len(part.vertices), output_face_count=len(part.faces))
                            or provenance.original_vertex_count != len(seed.vertices)):
                        raise ValueError(f"Restore fitting shape: Part {index} has invalid source lineage.")
                elif mapping != original:
                    raise ValueError(f"Restore fitting shape: Part {index} has changed vertex identity without retained lineage.")
                if len(mapping) != len(part.vertices) or len(set(mapping)) != len(mapping):
                    raise ValueError(f"Restore fitting shape: Part {index} has ambiguous vertex identity.")
                original_lookup = {value: vertex for vertex, value in enumerate(original)}
                source_faces = Counter(tuple(original[v] for v in face) for face in seed.faces)
                retained_faces = Counter(tuple(mapping[v] for v in part.faces[f]) for f in selected)
                if retained_faces - source_faces:
                    raise ValueError(f"Restore fitting shape: Part {index} selected topology no longer matches its source.")
                excluded = set(binding.excluded_island_faces) if binding is not None else set()
                if excluded:
                    if isinstance(provenance, SubmeshTopologyProvenance):
                        origins = provenance.face_origins
                    elif part.faces == seed.faces:
                        origins = tuple(range(len(part.faces)))
                    else:
                        raise ValueError(f"Restore fitting shape: Part {index} cannot prove its excluded face identities.")
                    selected = {face for face in selected if origins[face] not in excluded}
                vertices = sorted({vertex for face in selected for vertex in part.faces[face]})
                if not vertices:
                    continue
                if isinstance(provenance, SubmeshTopologyProvenance) and any(
                    provenance.vertex_origins[v].parents != (original_lookup.get(mapping[v], -1),)
                    or provenance.vertex_origins[v].weights != (1.,) for v in vertices
                ):
                    raise ValueError(f"Restore fitting shape: Part {index} has derived or ambiguous selected vertices.")
                try:
                    source_vertices = [original_lookup[mapping[vertex]] for vertex in vertices]
                except KeyError as exc:
                    raise ValueError(f"Restore fitting shape: Part {index} has unknown source vertices.") from exc
                source_part = source.submeshes[matches[index]]
                positions = [source_part.vertices[v] for v in source_vertices]
                appearance = appearances[index]
                if appearance is not None:
                    subset = copy.copy(source)
                    selected_part = copy.copy(part)
                    selected_part.vertices = positions
                    selected_part.faces, selected_part.normals, selected_part.tangents = [], [], []
                    selected_part.bone_indices = [part.bone_indices[v] for v in vertices] if part.bone_indices else []
                    selected_part.bone_weights = [part.bone_weights[v] for v in vertices] if part.bone_weights else []
                    subset.submeshes, subset.lod_levels = [selected_part], []
                    positions = appearance.to_neutral(subset).submeshes[0].vertices
                restored.append({"submesh_index": index, "vertex_indices": vertices,
                                 "positions": positions})
                scope.append((index, part.name, 0 if index in whole else island_counts[index]))
            if not restored:
                raise ValueError("Restore fitting shape has no selected included garment surface.")
            raise_if_cancelled(stop_event)
            history = self._capture_morph_profile_history_locked(session, action="refit_restore_shape",
                                                                 label="Restore fitting shape", include_profile_files=False)
            before_revision = session.revision
            try:
                report = native_mesh_editor_session_command("morph_restore_shape", session.session_id,
                    {"restored_positions": restored, "suppress_history": True, "include_edit_report": True,
                     "delta_output_dir": _native_preview_delta_output_dir()}, timeout_seconds=90.)
                if not isinstance(report, dict) or str(report.get("status") or "").lower() != "ok":
                    raise RuntimeError(_report_error(report, last_native_mesh_core_job_error() or "Restore fitting shape failed."))
                session.morph_session_revision += 1
                self._refit_shape_recoveries[session.session_id] = _RefitShapeRestorePreview(
                    history, before_revision, session.revision, source_path.name, hashlib.sha256(raw).hexdigest(),
                    tuple(row["submesh_index"] for row in restored), sum(len(row["vertex_indices"]) for row in restored), tuple(scope),
                    session.mesh_layer_autosave_requested_key != session.mesh_layer_autosave_saved_key)
                result, _state = self._morph_result_and_state_locked(session, "morph_restore_shape", report)
                self._refit_shape_recoveries[session.session_id].preview_revision = session.revision
                state = self._refresh_cached_morph_metadata_locked(session)
                raise_if_cancelled(stop_event)
            except Exception:
                self._refit_shape_recoveries.pop(session.session_id, None)
                self._rollback_unpublished_morph_profile_history_locked(session, history)
                raise
            return replace(result, action="refit_restore_shape_preview"), state

    def apply_refit_shape_restore(self, session_id):
        session = self._session(session_id)
        with session.export_lock:
            pending = self._refit_shape_recoveries.get(session.session_id)
            if pending is None:
                raise ValueError("Preview Restore fitting shape before applying it.")
            if session.revision != pending.preview_revision:
                raise RuntimeError("Restore fitting shape preview is stale; the mesh changed.")
            state = self._refresh_cached_morph_metadata_locked(session)
            self._publish_morph_profile_history_locked(session, pending.history, base_revision=pending.base_revision)
            self._refit_shape_recoveries.pop(session.session_id)
            session.revision += 1
            state = self._remember_morph_state(session, replace(state, edit_revision=session.revision,
                **self._refit_shape_restore_state_fields_locked(session)))
            self._schedule_mesh_layer_autosave(session)
            return self._result(session, "refit_restore_shape_apply"), state

    def cancel_refit_shape_restore(self, session_id):
        session = self._session(session_id)
        with session.export_lock:
            pending = self._refit_shape_recoveries.get(session.session_id)
            if pending is None:
                raise ValueError("No Restore fitting shape preview is pending.")
            if session.revision != pending.preview_revision:
                raise RuntimeError("Restore fitting shape preview is stale; the mesh changed.")
            self._refit_shape_recoveries.pop(session.session_id)
            self._rollback_unpublished_morph_profile_history_locked(session, pending.history)
            session.revision += 1
            state = self._refresh_cached_morph_metadata_locked(session)
            if pending.autosave_pending:
                self._schedule_mesh_layer_autosave(session)
            return self._result(session, "refit_restore_shape_cancel"), state

    def _discard_refit_shape_restore_locked(self, session):
        pending = self._refit_shape_recoveries.pop(session.session_id, None)
        if pending is not None:
            from cdmw.services.mesh_service_morph import _service_call
            _service_call("_dispose_history_snapshot", pending.history)
