"""Identity-bound authored sliders, correction capture, and selection refit tools.

The resident core owns every deformation. This layer records authoring intent,
validates exact source identities, and publishes one reversible service operation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import operator
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from cdmw.domain.mesh import (
    MeshEditResult,
    MeshMorphProfile,
    MeshMorphSparseField,
    MeshMorphState,
    MeshRefitDriverRegion,
    MeshRefitGarmentSettings,
    build_morph_sparse_difference,
    create_authored_morph_definition,
    mesh_morph_base_fingerprint,
    mesh_morph_driver_topology_fingerprint,
    mesh_morph_role_topology_fingerprint,
    validate_morph_definition_geometry,
    validate_morph_target_identity,
    with_morph_garment_corrections,
)
from cdmw.domain.mesh.topology import SubmeshTopologyProvenance, validate_topology_provenance
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service_native_clone import _clone_mesh_for_service_native_snapshot


@dataclass(frozen=True, slots=True)
class _MorphAuthoringBaseline:
    mesh: ParsedMesh
    driver_submesh_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _MorphCorrectionCapture:
    definition_id: str
    garment_submesh_indices: tuple[int, ...]
    preview_mesh: ParsedMesh
    neutral_mesh: ParsedMesh
    return_values: tuple[tuple[str, float], ...]
    effective_vertex_masks: tuple[tuple[int, tuple[tuple[int, float], ...]], ...] = ()
    return_layers: tuple = (None, (), False)
    return_preset_id: str = ""


def _clone_authoring_mesh(mesh: ParsedMesh, operation: str) -> ParsedMesh:
    return _clone_mesh_for_service_native_snapshot(
        mesh, operation,
        "Python authoring mesh clone fallback blocked while native mesh core is available",
    )


def clone_authoring_baseline(value: _MorphAuthoringBaseline | None) -> _MorphAuthoringBaseline | None:
    return replace(value, mesh=_clone_authoring_mesh(value.mesh, "morph.authoring_history")) if value else None


def clone_correction_capture(value: _MorphCorrectionCapture | None) -> _MorphCorrectionCapture | None:
    if value is None:
        return None
    return replace(
        value,
        preview_mesh=_clone_authoring_mesh(value.preview_mesh, "morph.correction_preview_history"),
        neutral_mesh=_clone_authoring_mesh(value.neutral_mesh, "morph.correction_base_history"),
    )


def _strict_indices(values: object, *, label: str, count: int | None = None, nonempty: bool = True) -> tuple[int, ...]:
    result = []
    seen: set[int] = set()
    for value in tuple(values or ()):
        if isinstance(value, bool):
            raise ValueError(f"{label} requires integer indices.")
        try:
            index = operator.index(value)
        except TypeError as exc:
            raise ValueError(f"{label} requires integer indices.") from exc
        if index < 0 or (count is not None and index >= count) or index in seen:
            raise ValueError(f"{label} contains a duplicate or out-of-range index.")
        result.append(index)
        seen.add(index)
    if nonempty and not result:
        raise ValueError(f"{label} requires a nonempty selection.")
    return tuple(sorted(result))


def _selected_vertices(mesh: ParsedMesh, selection: object) -> dict[int, tuple[int, ...]]:
    """Expand only explicit vertex, edge, face, or whole-part selection."""
    selected: dict[int, set[int]] = {}
    part_count = len(mesh.submeshes)

    def part(index: object):
        key = _strict_indices((index,), label="Selected part", count=part_count)[0]
        return key, mesh.submeshes[key]

    for raw_part, raw_vertices in tuple(getattr(selection, "vertices_by_submesh", ()) or ()):
        key, submesh = part(raw_part)
        selected.setdefault(key, set()).update(
            _strict_indices(raw_vertices, label="Selected vertex", count=len(submesh.vertices), nonempty=False)
        )
    for raw_part, raw_edges in tuple(getattr(selection, "edges_by_submesh", ()) or ()):
        key, submesh = part(raw_part)
        for edge in raw_edges:
            if len(edge) != 2:
                raise ValueError("Selected edges must have two endpoints.")
            selected.setdefault(key, set()).update(
                _strict_indices(edge, label="Selected edge", count=len(submesh.vertices))
            )
    for raw_part, raw_faces in tuple(getattr(selection, "faces_by_submesh", ()) or ()):
        key, submesh = part(raw_part)
        for face in _strict_indices(raw_faces, label="Selected face", count=len(submesh.faces), nonempty=False):
            selected.setdefault(key, set()).update(submesh.faces[face])
    for raw_part in tuple(getattr(selection, "source_indices", ()) or ()):
        key, submesh = part(raw_part)
        selected.setdefault(key, set()).update(range(len(submesh.vertices)))
    result = {index: tuple(sorted(vertices)) for index, vertices in sorted(selected.items()) if vertices}
    if not result:
        raise ValueError("Select body or garment vertices, faces, or parts first.")
    return result


def _neutral_rows(mesh: ParsedMesh, indices: Sequence[int]) -> list[dict[str, object]]:
    return [
        {
            "submesh_index": index,
            "vertex_indices": list(range(len(mesh.submeshes[index].vertices))),
            "positions": [list(point) for point in mesh.submeshes[index].vertices],
        }
        for index in indices
    ]


def _profile_role_indices(profile: MeshMorphProfile) -> tuple[int, ...]:
    return tuple(sorted({
        item.submesh_index
        for definition in profile.definitions
        for item in (*definition.vertices, *definition.garment_corrections)
    }))


def _merge_edit_results(results: Sequence[MeshEditResult]) -> MeshEditResult:
    if not results:
        raise ValueError("No native edit results were supplied.")
    changed: dict[int, set[int]] = {}
    for result in results:
        for index, vertices in result.changed_vertices_by_submesh:
            changed.setdefault(index, set()).update(vertices)
    return replace(
        results[-1],
        affected_submesh_indices=tuple(sorted({index for result in results for index in result.affected_submesh_indices})),
        changed_vertices_by_submesh=tuple((index, tuple(sorted(vertices))) for index, vertices in sorted(changed.items())),
        native_preview_vertex_update_groups=tuple(group for result in results for group in result.native_preview_vertex_update_groups),
        native_preview_triangle_groups=tuple(group for result in results for group in result.native_preview_triangle_groups),
        submesh_counts=next((result.submesh_counts for result in reversed(results) if result.submesh_counts), ()),
        diagnostics=tuple(dict.fromkeys(item for result in results for item in result.diagnostics)),
    )


def _settings_payload(settings: MeshRefitGarmentSettings, *, include_mask: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "garment_submesh_indices": [settings.submesh_index],
        "enabled": settings.enabled,
        "intensity_percent": settings.intensity_percent,
        "mode": settings.mode,
        "clearance_percent": settings.clearance_percent,
        "tightness_percent": settings.tightness_percent,
        "tightness_initialized": settings.tightness_initialized,
    }
    if include_mask:
        payload["vertex_masks"] = [] if settings.vertex_mask is None else [{
            "submesh_index": settings.submesh_index,
            "vertex_indices": [index for index, _weight in settings.vertex_mask],
            "weights": [weight for _index, weight in settings.vertex_mask],
        }]
    return payload


def _refit_settings_batch_payload(
    settings: Sequence[MeshRefitGarmentSettings], *, include_masks: bool = True, include_islands: bool = False,
) -> dict[str, object]:
    """Keep each Part's settings while the resident fitter recomposes once."""
    rows: list[dict[str, object]] = []
    for item in settings:
        row: dict[str, object] = {
            "submesh_index": item.submesh_index,
            "enabled": item.enabled,
            "intensity_percent": item.intensity_percent,
            "mode": item.mode,
            "clearance_percent": item.clearance_percent,
            "tightness_percent": item.tightness_percent,
            "tightness_initialized": item.tightness_initialized,
        }
        if include_masks:
            row["vertex_mask"] = None if item.vertex_mask is None else {
                "vertex_indices": [index for index, _weight in item.vertex_mask],
                "weights": [weight for _index, weight in item.vertex_mask],
            }
        if include_islands or item.island_settings:
            row["island_settings"] = [
                {"face_indices": list(island.face_indices), **{
                    key: getattr(island, key) for key in
                    ("enabled", "intensity_percent", "mode", "clearance_percent", "tightness_percent", "tightness_initialized")
                }} for island in item.island_settings
            ]
        rows.append(row)
    return {
        "garment_submesh_indices": [item.submesh_index for item in settings],
        "garment_settings": rows,
    }


def _refit_masks_from_report(refit: Mapping[str, object]) -> dict[int, tuple[tuple[int, float], ...]]:
    result = {}
    for row in tuple(refit.get("vertex_masks") or ()):
        if not isinstance(row, Mapping):
            raise RuntimeError("Resident refit state returned an invalid vertex mask.")
        part = _strict_indices((row.get("submesh_index"),), label="Refit mask part")[0]
        if part in result:
            raise RuntimeError("Resident refit state returned duplicate vertex masks.")
        indices = tuple(row.get("vertex_indices") or ())
        _strict_indices(indices, label="Refit mask vertices", nonempty=False)
        weights = tuple(float(value) for value in tuple(row.get("weights") or ()))
        if len(indices) != len(weights) or any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in weights):
            raise RuntimeError("Resident refit state returned invalid mask weights.")
        result[part] = tuple(zip(indices, weights))
    return result


def _updated_vertex_mask(settings: MeshRefitGarmentSettings, count: int, selected: Sequence[int], weight: float):
    # An absent mask means one everywhere; a present sparse mask means zero
    # outside its rows. Preserve that difference when editing a selection.
    weights = dict(settings.vertex_mask) if settings.vertex_mask is not None else dict.fromkeys(range(count), 1.0)
    for index in selected:
        weights[index] = weight
    return tuple((index, value) for index, value in sorted(weights.items()) if value != 0.0)


def _merged_correction_fields(definition, changes, effective_masks):
    entries: dict[int, dict[int, tuple[float, float, float]]] = {}
    for field in definition.garment_corrections:
        entries[field.submesh_index] = dict(zip(field.vertex_indices, field.deltas))
    for field in changes:
        if field.submesh_index not in effective_masks:
            raise RuntimeError("Correction capture omitted effective garment influence.")
        mask = dict(effective_masks[field.submesh_index])
        target = entries.setdefault(field.submesh_index, {})
        for index, delta in zip(field.vertex_indices, field.deltas):
            influence = mask.get(index, 0.0)
            if influence == 0.0:
                raise ValueError("A protected garment vertex was edited. Cancel the correction or restore that vertex.")
            previous = target.get(index, (0.0, 0.0, 0.0))
            target[index] = tuple(previous[axis] + delta[axis] / influence for axis in range(3))
    fields = []
    for submesh_index, rows in sorted(entries.items()):
        nonzero = tuple((index, delta) for index, delta in sorted(rows.items()) if any(value != 0.0 for value in delta))
        if nonzero:
            fields.append(MeshMorphSparseField(
                definition_id=definition.definition_id,
                submesh_index=submesh_index,
                vertex_indices=tuple(index for index, _delta in nonzero),
                deltas=tuple(delta for _index, delta in nonzero),
            ))
    return tuple(fields)


class MeshMorphAuthoringMixin:
    """Service operations shared by the resident editor and both UI shells."""

    def _authoring_data_locked(self, session):
        from cdmw.services.mesh_service_morph import _MeshMorphSessionData
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        return data

    def _require_no_pending_morph_authoring(
        self, session, *, include_baseline: bool = False, allow_correction_comparison: bool = False,
    ):
        data = self._morph_sessions.get(session.session_id)
        self._require_no_pending_refit_shape_restore_locked(session)
        if data is None or getattr(data, "authoring_operation", False):
            return
        if not allow_correction_comparison and not getattr(data, "corrections_enabled", True):
            raise RuntimeError("Turn outfit corrections back on before editing or finishing.")
        if getattr(data, "correction_capture", None) is not None:
            raise RuntimeError("Save or Cancel the current garment correction before changing Morph & Refit.")
        if include_baseline and getattr(data, "authoring_baseline", None) is not None:
            raise RuntimeError("Save the captured slider or Discard its baseline before changing Morph & Refit.")

    def _morph_identity_mesh_locked(self, session, mesh: ParsedMesh, indices=None) -> ParsedMesh:
        """Normalize a proven authority-only promotion on an identity-only clone.

        Native exports may attach identity topology provenance to an unchanged
        vertex order. Preserve the loaded map's authority for persisted hashes
        only when that map itself is still identical. The working mesh keeps
        its authoritative native provenance, and a lost/reordered map is rejected.
        """
        seed = session.base_mesh
        parts = tuple(indices) if indices is not None else tuple(range(len(mesh.submeshes)))
        for index in parts:
            if index >= len(seed.submeshes):
                continue
            current, original = mesh.submeshes[index], seed.submeshes[index]
            current_authority = str(getattr(current, "source_vertex_map_authority", "") or "")
            seed_authority = str(getattr(original, "source_vertex_map_authority", "") or "")
            if current_authority != "topology" or seed_authority == "topology":
                continue
            provenance = getattr(current, "topology_provenance", None)
            if not isinstance(provenance, SubmeshTopologyProvenance):
                continue
            if validate_topology_provenance(
                provenance, output_vertex_count=len(current.vertices), output_face_count=len(current.faces),
            ):
                raise ValueError("Resident morph identity has invalid topology provenance.")
            if (
                provenance.original_vertex_count != len(original.vertices)
                or provenance.original_face_count != len(original.faces)
                or len(current.vertices) != len(original.vertices)
                or tuple(tuple(face) for face in current.faces) != tuple(tuple(face) for face in original.faces)
                or provenance.face_origins != tuple(range(len(original.faces)))
                or any(origin.parents != (vertex,) or origin.weights != (1.0,) for vertex, origin in enumerate(provenance.vertex_origins))
            ):
                continue
            if tuple(current.source_vertex_map) != tuple(original.source_vertex_map):
                raise ValueError("Resident morph export changed the loaded source vertex mapping; exact authored identity cannot be preserved.")
            current.source_vertex_map_authority = seed_authority
            # This is a geometry/identity snapshot, never an output mesh. Keeping
            # the promoted contract here would relabel it during history cloning.
            current.topology_provenance = None
        return mesh

    def _current_morph_identity_mesh_locked(self, session, indices=None, *, mesh=None):
        from cdmw.services.mesh_service_morph import _service_call
        mesh = mesh if mesh is not None else self._working_mesh_locked(session, clone=True)
        parts = tuple(indices) if indices is not None else tuple(range(len(mesh.submeshes)))
        needs_proof = False
        for index in parts:
            if index >= len(session.base_mesh.submeshes):
                continue
            current, seed = mesh.submeshes[index], session.base_mesh.submeshes[index]
            if (
                str(getattr(current, "source_vertex_map_authority", "") or "") == "topology"
                and str(getattr(seed, "source_vertex_map_authority", "") or "") != "topology"
                and not isinstance(getattr(current, "topology_provenance", None), SubmeshTopologyProvenance)
            ):
                if tuple(current.source_vertex_map) != tuple(seed.source_vertex_map):
                    raise ValueError("Resident morph snapshot changed the loaded source vertex mapping.")
                needs_proof = True
        if needs_proof:
            # A geometry history restore can omit Python's decoded provenance.
            # Ask the resident session for its proof before normalizing authority.
            self._ensure_native_morph_session_locked(session)
            if not _service_call("export_native_mesh_editor_session_to_mesh", mesh, session.session_id, timeout_seconds=15.0):
                raise RuntimeError("Resident source identity export failed after geometry history restore.")
        return self._morph_identity_mesh_locked(session, mesh, parts)

    def _native_neutral_mesh_locked(self, session, indices: Sequence[int]) -> ParsedMesh:
        from cdmw.services.mesh_service_morph import native_mesh_editor_session_command, _report_error
        mesh = self._current_morph_identity_mesh_locked(session, indices)
        parts = _strict_indices(indices, label="Neutral mesh parts", count=len(mesh.submeshes))
        self._ensure_native_morph_session_locked(session)
        report = native_mesh_editor_session_command(
            "morph_state", session.session_id,
            {"include_neutral_positions": True, "submesh_indices": list(parts)},
            timeout_seconds=15.0,
        )
        if not isinstance(report, Mapping) or str(report.get("status") or "").lower() != "ok":
            raise RuntimeError(_report_error(report, "Resident neutral mesh query failed."))
        rows = report.get("neutral_positions")
        if not isinstance(rows, (list, tuple)) or len(rows) != len(parts):
            raise RuntimeError("Resident neutral mesh query omitted requested parts.")
        seen = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise RuntimeError("Resident neutral mesh row is invalid.")
            index = _strict_indices((row.get("submesh_index"),), label="Neutral part", count=len(mesh.submeshes))[0]
            if index not in parts or index in seen:
                raise RuntimeError("Resident neutral mesh query returned a duplicate or unrequested part.")
            seen.add(index)
            count = len(mesh.submeshes[index].vertices)
            vertex_indices = tuple(row.get("vertex_indices") or ())
            if vertex_indices != tuple(range(count)):
                raise RuntimeError("Resident neutral mesh query did not return every vertex in order.")
            positions = tuple(tuple(float(value) for value in point) for point in tuple(row.get("positions") or ()))
            if len(positions) != count or any(len(point) != 3 or not all(math.isfinite(value) for value in point) for point in positions):
                raise RuntimeError("Resident neutral mesh query returned invalid coordinates.")
            mesh.submeshes[index].vertices = list(positions)
        return self._morph_identity_mesh_locked(session, mesh, parts)

    def _effective_refit_masks_locked(self, session, indices):
        from cdmw.services.mesh_service_morph import native_mesh_editor_session_command, _report_error
        targets = _strict_indices(indices, label="Correction garment parts", count=len(session.working_mesh.submeshes))
        self._ensure_native_morph_session_locked(session)
        report = native_mesh_editor_session_command(
            "morph_state", session.session_id,
            {"include_effective_vertex_masks": True, "submesh_indices": list(targets)},
            timeout_seconds=15.0,
        )
        if not isinstance(report, Mapping) or str(report.get("status") or "").lower() != "ok":
            raise RuntimeError(_report_error(report, "Resident effective garment influence query failed."))
        if "effective_vertex_masks" not in report:
            raise RuntimeError("Resident correction query omitted effective garment influence.")
        masks = _refit_masks_from_report({"vertex_masks": report["effective_vertex_masks"]})
        if set(masks) != set(targets):
            raise RuntimeError("Resident correction query omitted requested garment parts.")
        for index, rows in masks.items():
            if tuple(vertex for vertex, _weight in rows) != tuple(range(len(session.working_mesh.submeshes[index].vertices))):
                raise RuntimeError("Resident correction query omitted garment vertices.")
        return tuple(sorted(masks.items()))

    def _morph_authoring_transaction_locked(
        self, session, action: str, label: str, operation: Callable[[], MeshEditResult | None],
        *, include_profile_files: bool = False,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        """Retain geometry/runtime; file-writing operations opt into file history."""
        from cdmw.services.mesh_service_morph import mesh_morph_profile_lock
        with mesh_morph_profile_lock(self._profile_root()):
            history = self._capture_morph_profile_history_locked(
                session, action=action, label=label,
                include_profile_files=include_profile_files,
            )
            base_revision = session.revision
            data = self._authoring_data_locked(session)
            data.authoring_operation = True
            try:
                result = operation()
                session.morph_session_revision += 1
                data.authoring_operation = False
                state = self._refresh_cached_morph_metadata_locked(session)
                result = result if result is not None else self._result(session, action)
                self._publish_morph_profile_history_locked(session, history, base_revision=base_revision)
            except Exception:
                data.authoring_operation = False
                self._rollback_unpublished_morph_profile_history_locked(session, history)
                raise
            state = replace(state, edit_revision=session.revision)
            self._authoring_data_locked(session).state = state
            return replace(result, action=action, revision=session.revision), state

    def _bound_garment_settings_locked(self, session, indices: Sequence[object], *, selection=None):
        data = self._required_morph_data(session)
        state = self._refresh_cached_morph_metadata_locked(session)
        if not indices and selection is not None:
            mesh = self._working_mesh_locked(session, clone=False)
            indices = tuple(_selected_vertices(mesh, selection))
        targets = _strict_indices(indices, label="Bound garment parts", count=len(session.working_mesh.submeshes))
        bound = set(state.refit.garment_submesh_indices)
        if not set(targets).issubset(bound):
            raise ValueError("Every target garment must already be bound to the active driver.")
        settings = {item.submesh_index: item for item in state.refit.garment_settings}
        if any(index not in settings for index in targets):
            raise RuntimeError("Resident refit state omitted a bound garment's settings.")
        return data, targets, settings

    def capture_morph_baseline(self, session_id, submesh_indices=(), *, selection=None):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session)
            state = self._refresh_cached_morph_metadata_locked(session)
            if state.unbaked or any(value != 0.0 for _key, value in state.values):
                raise RuntimeError("Reset active slider values before capturing an authored baseline.")
            mesh = self._working_mesh_locked(session, clone=True)
            indices = _strict_indices(
                submesh_indices or tuple(_selected_vertices(mesh, selection if selection is not None else session.selection)),
                label="Authored body parts", count=len(mesh.submeshes),
            )
            if set(indices).intersection(state.refit.garment_submesh_indices):
                raise ValueError("An authored body baseline cannot contain bound garment parts.")
            mesh = self._current_morph_identity_mesh_locked(session, indices, mesh=mesh)
            mesh_morph_base_fingerprint(mesh, indices)

            def capture():
                self._authoring_data_locked(session).authoring_baseline = _MorphAuthoringBaseline(mesh, indices)
                return None

            return self._morph_authoring_transaction_locked(session, "morph_capture_baseline", "Capture Slider Baseline", capture)

    def cancel_morph_baseline(self, session_id):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session)
            if self._authoring_data_locked(session).authoring_baseline is None:
                raise RuntimeError("No authored baseline is pending.")

            def cancel():
                self._authoring_data_locked(session).authoring_baseline = None
                return None

            return self._morph_authoring_transaction_locked(session, "morph_cancel_baseline", "Discard Slider Baseline", cancel)

    def capture_authored_morph_definition(
        self, session_id, *, profile_id="", profile_name="", definition_id, label,
        category="Authored", min_percent=-100, max_percent=100, default_percent=0,
        target_mesh=None,
    ):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session)
            data = self._authoring_data_locked(session)
            baseline = data.authoring_baseline
            if baseline is None:
                raise RuntimeError("Capture the neutral body baseline before sculpting or importing a target.")
            state = self._refresh_cached_morph_metadata_locked(session)
            if state.unbaked or any(value != 0.0 for _key, value in state.values):
                raise RuntimeError("Authored target capture requires zero slider values.")
            if not float(min_percent) <= 0.0 <= 100.0 <= float(max_percent):
                raise ValueError("An authored slider range must include both zero and 100 percent.")
            target = target_mesh if target_mesh is not None else self._working_mesh_locked(session, clone=True)
            if not isinstance(target, ParsedMesh):
                raise TypeError("An authored target must be an identity-checked ParsedMesh.")
            if target_mesh is not None:
                target = _clone_authoring_mesh(target, "morph.authored_target_identity")
                target = self._morph_identity_mesh_locked(session, target, baseline.driver_submesh_indices)
            else:
                target = self._current_morph_identity_mesh_locked(session, baseline.driver_submesh_indices, mesh=target)
            definition = create_authored_morph_definition(
                baseline.mesh, target, definition_id=str(definition_id or "").strip(),
                label=str(label or "").strip(), category=str(category or "Authored"),
                submesh_indices=baseline.driver_submesh_indices,
                min_percent=float(min_percent), max_percent=float(max_percent), default_percent=float(default_percent),
            )
            profile_key = str(profile_id or (data.profile.profile_id if data.profile else "") or f"authored-{uuid4().hex}").strip()
            previous = data.known_profiles.get(profile_key)
            if previous is None and data.profile is not None and data.profile.profile_id == profile_key:
                previous = data.profile
            definitions = list(previous.definitions if previous else ())
            previous_definition = next((item for item in definitions if item.definition_id == definition.definition_id), None)
            roles = tuple(sorted(set(baseline.driver_submesh_indices).union(
                _profile_role_indices(previous) if previous is not None else ()
            )))
            neutral = self._native_neutral_mesh_locked(session, roles)
            for index in baseline.driver_submesh_indices:
                neutral.submeshes[index].vertices = list(baseline.mesh.submeshes[index].vertices)
            if previous_definition is not None and previous_definition.garment_corrections:
                validate_morph_definition_geometry(neutral, previous_definition)
                definition = replace(
                    definition,
                    garment_corrections=previous_definition.garment_corrections,
                    correction_topology_fingerprint=previous_definition.correction_topology_fingerprint,
                    correction_base_geometry_fingerprint=previous_definition.correction_base_geometry_fingerprint,
                )
            definitions = [definition if item.definition_id == definition.definition_id else item for item in definitions]
            if previous_definition is None:
                definitions.append(definition)
            for item in definitions:
                validate_morph_definition_geometry(neutral, item)
            profile = MeshMorphProfile(
                profile_id=profile_key,
                name=str(profile_name or (previous.name if previous else "") or "Authored Body Sliders"),
                topology_fingerprint=mesh_morph_driver_topology_fingerprint(neutral, definitions),
                definitions=tuple(definitions),
            )
            values = {item.definition_id: 100.0 if item.definition_id == definition.definition_id else 0.0 for item in definitions}

            def capture():
                result, _state = self._activate_morph_profile_locked(
                    session, profile, record_history=False, preserve_runtime=True,
                    neutral_positions=_neutral_rows(baseline.mesh, baseline.driver_submesh_indices),
                    values=values, base_mesh=neutral,
                )
                current = self._authoring_data_locked(session)
                current.authoring_baseline = None
                current.topology_mesh = neutral
                return result

            return self._morph_authoring_transaction_locked(session, "morph_capture_authored", f"Capture Slider {definition.label}", capture)

    def begin_morph_correction(self, session_id, definition_id, garment_submesh_indices=()):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            data, targets, _settings = self._bound_garment_settings_locked(
                session, garment_submesh_indices, selection=session.selection,
            )
            definition = next((item for item in data.profile.definitions if item.definition_id == str(definition_id)), None)
            if definition is None:
                raise ValueError("Choose a slider before beginning its garment correction.")
            if not definition.min_percent <= 100.0 <= definition.max_percent:
                raise ValueError("Garment correction authoring requires a slider with a 100 percent target.")
            # Cancel restores the geometry from before correction editing, including
            # accidental body edits and other garments driven by prior slider values.
            # Query every Part now so none retain a fitted preview as their zero base.
            parts = tuple(range(len(session.working_mesh.submeshes)))
            neutral = self._native_neutral_mesh_locked(session, parts)
            for item in data.profile.definitions:
                validate_morph_definition_geometry(neutral, item)
            from cdmw.services.mesh_service_morph_layers import capture_morph_layers
            return_values = tuple(data.state.values)
            return_layers = capture_morph_layers(data)
            return_preset_id = data.preset_id
            values = {item.definition_id: 100.0 if item.definition_id == definition.definition_id else 0.0 for item in data.profile.definitions}

            def begin():
                result, _state = self._activate_morph_profile_locked(
                    session, data.profile, record_history=False, preserve_runtime=True,
                    values=values, base_mesh=neutral,
                )
                preview = self._current_morph_identity_mesh_locked(session)
                effective_masks = self._effective_refit_masks_locked(session, targets)
                if not any(weight > 0.0 for _part, rows in effective_masks for _vertex, weight in rows):
                    raise RuntimeError("The chosen garments are disabled or fully protected from refitting.")
                self._authoring_data_locked(session).correction_capture = _MorphCorrectionCapture(
                    definition.definition_id, targets, preview, neutral, return_values, effective_masks,
                    return_layers, return_preset_id,
                )
                return result

            return self._morph_authoring_transaction_locked(session, "morph_begin_correction", f"Edit {definition.label} Garment Correction", begin)

    def save_morph_correction(self, session_id):
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            capture = data.correction_capture
            if capture is None:
                raise RuntimeError("Begin a garment correction before saving it.")
            _data, targets, settings = self._bound_garment_settings_locked(session, capture.garment_submesh_indices)
            definition = next((item for item in data.profile.definitions if item.definition_id == capture.definition_id), None)
            if definition is None:
                raise RuntimeError("The corrected slider is no longer available.")
            current = self._current_morph_identity_mesh_locked(session)
            others = tuple(index for index in range(len(current.submeshes)) if index not in targets)
            if len(current.submeshes) != len(capture.preview_mesh.submeshes):
                raise ValueError("Garment correction topology changed. Undo that topology edit before saving.")
            if others and mesh_morph_base_fingerprint(current, others) != mesh_morph_base_fingerprint(capture.preview_mesh, others):
                raise ValueError("Vertices outside the chosen garments changed. Undo those edits or Cancel this correction.")
            changes = build_morph_sparse_difference(
                capture.preview_mesh, current, definition_id=definition.definition_id, submesh_indices=targets,
            )
            if not changes:
                raise ValueError("No garment correction changes were found. Use Cancel to leave correction editing.")
            fields = _merged_correction_fields(definition, changes, dict(capture.effective_vertex_masks))
            corrected = with_morph_garment_corrections(definition, capture.neutral_mesh, fields)
            profile = replace(data.profile, definitions=tuple(corrected if item.definition_id == corrected.definition_id else item for item in data.profile.definitions))
            values = (dict(capture.return_values) if capture.return_layers[0] is not None else {
                item.definition_id: 100.0 if item.definition_id == corrected.definition_id else 0.0
                for item in profile.definitions
            })

            def save():
                result, _state = self._activate_morph_profile_locked(
                    session, profile, record_history=False, preserve_runtime=True,
                    neutral_positions=_neutral_rows(capture.neutral_mesh, targets),
                    values=values, base_mesh=capture.neutral_mesh,
                )
                current_data = self._authoring_data_locked(session)
                current_data.topology_mesh = capture.neutral_mesh
                current_data.correction_capture = None
                if capture.return_layers[0] is not None:
                    from cdmw.services.mesh_service_morph_layers import restore_morph_layers
                    restore_morph_layers(current_data, capture.return_layers)
                    current_data.preset_id = capture.return_preset_id
                return result

            return self._morph_authoring_transaction_locked(session, "morph_save_correction", f"Save {definition.label} Garment Correction", save)

    def cancel_morph_correction(self, session_id):
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            capture = data.correction_capture
            if capture is None:
                raise RuntimeError("No garment correction is pending.")
            current = self._current_morph_identity_mesh_locked(session)
            # Source identity and exact faces must still match before neutral rows
            # can be restored; matching vertex counts alone are insufficient.
            parts = tuple(range(len(capture.preview_mesh.submeshes)))
            validate_morph_target_identity(
                capture.preview_mesh, current, submesh_indices=parts,
            )

            def cancel():
                result, _state = self._activate_morph_profile_locked(
                    session, data.profile, record_history=False, preserve_runtime=True,
                    neutral_positions=_neutral_rows(capture.neutral_mesh, parts),
                    values=dict(capture.return_values), base_mesh=capture.neutral_mesh,
                )
                from cdmw.services.mesh_service_morph_layers import restore_morph_layers
                current_data = self._authoring_data_locked(session)
                current_data.correction_capture = None
                restore_morph_layers(current_data, capture.return_layers)
                current_data.preset_id = capture.return_preset_id
                return result

            return self._morph_authoring_transaction_locked(session, "morph_cancel_correction", "Cancel Garment Correction", cancel)

    def set_morph_corrections_enabled(self, session_id, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("Show outfit corrections must be a boolean.")
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(
                session, include_baseline=True, allow_correction_comparison=True,
            )
            data = self._required_morph_data(session)
            state = self._refresh_cached_morph_metadata_locked(session)
            if data.corrections_enabled == enabled:
                return self._result(session, "morph_set_corrections_enabled", status="noop"), state
            if not any(item.garment_corrections for item in data.profile.definitions):
                raise ValueError("This profile has no saved outfit corrections to compare.")
            neutral = self._native_neutral_mesh_locked(session, _profile_role_indices(data.profile))
            preset_id = data.preset_id

            def compare():
                self._authoring_data_locked(session).corrections_enabled = enabled
                result, _state = self._activate_morph_profile_locked(
                    session, data.profile, record_history=False, preserve_runtime=True,
                    values=dict(state.values), base_mesh=neutral, retain_layers=True,
                )
                self._authoring_data_locked(session).preset_id = preset_id
                return result

            return self._morph_authoring_transaction_locked(
                session, "morph_set_corrections_enabled",
                "Show Outfit Corrections" if enabled else "Compare Without Outfit Corrections", compare,
            )

    def reset_morph_correction(self, session_id, definition_id, garment_submesh_indices=()):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            data, targets, _settings = self._bound_garment_settings_locked(
                session, garment_submesh_indices, selection=session.selection,
            )
            definition = next((item for item in data.profile.definitions if item.definition_id == str(definition_id)), None)
            if definition is None:
                raise ValueError("Choose the slider whose selected outfit correction should be reset.")
            fields = tuple(field for field in definition.garment_corrections if field.submesh_index not in targets)
            if fields == definition.garment_corrections:
                return self._result(session, "morph_reset_correction", status="noop"), data.state
            neutral = self._native_neutral_mesh_locked(session, _profile_role_indices(data.profile))
            if fields:
                # Retained corrections must still belong to their recorded base.
                validate_morph_definition_geometry(neutral, definition)
            corrected = with_morph_garment_corrections(definition, neutral, fields)
            profile = replace(data.profile, definitions=tuple(
                corrected if item.definition_id == corrected.definition_id else item
                for item in data.profile.definitions
            ))
            values, preset_id = dict(data.state.values), data.preset_id

            def reset():
                result, _state = self._activate_morph_profile_locked(
                    session, profile, record_history=False, preserve_runtime=True,
                    values=values, base_mesh=neutral, retain_layers=True,
                )
                self._authoring_data_locked(session).preset_id = preset_id
                return result

            return self._morph_authoring_transaction_locked(
                session, "morph_reset_correction", f"Reset {definition.label} Selected Outfit Correction", reset,
            )

    def set_refit_vertex_influence(self, session_id, *, selection=None, weight=0.0, garment_submesh_indices=()):
        influence = float(weight)
        if not math.isfinite(influence) or not 0.0 <= influence <= 1.0:
            raise ValueError("Garment vertex influence must be between zero and one.")
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            mesh = self._working_mesh_locked(session, clone=False)
            selected = _selected_vertices(mesh, selection if selection is not None else session.selection)
            _data, targets, settings = self._bound_garment_settings_locked(session, garment_submesh_indices or tuple(selected))
            if set(selected) != set(targets):
                raise ValueError("Influence selection must contain vertices only from the chosen bound garments.")
            changed_settings = [
                replace(settings[index], vertex_mask=_updated_vertex_mask(settings[index], len(mesh.submeshes[index].vertices), selected[index], influence))
                for index in targets
            ]
            return self._configure_refit_settings_transaction_locked(session, changed_settings, "morph_set_influence", "Set Selected Garment Influence")

    def clear_refit_vertex_influence(self, session_id, garment_submesh_indices=(), *, selection=None):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            _data, targets, settings = self._bound_garment_settings_locked(
                session, garment_submesh_indices, selection=selection if selection is not None else session.selection,
            )
            return self._configure_refit_settings_transaction_locked(
                session, [replace(settings[index], vertex_mask=None) for index in targets],
                "morph_clear_influence", "Clear Garment Influence Masks",
            )

    def _configure_refit_settings_transaction_locked(self, session, settings, action, label):
        self._validate_authored_runtime_use_locked(session, "morph_configure_refit", {})
        def configure():
            report = self._run_morph_command_locked(
                session, "morph_configure_refit", _refit_settings_batch_payload(settings),
                history_label=label, record_history=False,
            )
            return self._morph_result_and_state_locked(session, action, report)[0]

        return self._morph_authoring_transaction_locked(session, action, label, configure)

    def set_refit_driver_region(self, session_id, garment_submesh_indices, *, selection=None):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            data, targets, _settings = self._bound_garment_settings_locked(session, garment_submesh_indices)
            if data.state.unbaked or any(value != 0.0 for _key, value in data.state.values):
                raise RuntimeError("Reset active slider values before changing a garment's driver region.")
            mesh = self._working_mesh_locked(session, clone=False)
            selected = _selected_vertices(mesh, selection if selection is not None else session.selection)
            if not set(selected).issubset(data.state.driver_submesh_indices):
                raise ValueError("Driver regions must select only the active body driver parts.")
            selected_sets = {index: set(vertices) for index, vertices in selected.items()}
            triangles = sum(
                all(vertex in vertices for vertex in face)
                for index, vertices in selected_sets.items() for face in mesh.submeshes[index].faces
            )
            if not triangles:
                raise ValueError("Select at least one complete body triangle for the driver region.")
            regions = tuple(MeshRefitDriverRegion(index, vertices) for index, vertices in selected.items())
            return self._refit_region_transaction_locked(session, targets, regions, "morph_set_driver_region", "Set Garment Driver Region")

    def clear_refit_driver_region(self, session_id, garment_submesh_indices):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            data, targets, _settings = self._bound_garment_settings_locked(session, garment_submesh_indices)
            if data.state.unbaked or any(value != 0.0 for _key, value in data.state.values):
                raise RuntimeError("Reset active slider values before clearing a garment's driver region.")
            return self._refit_region_transaction_locked(session, targets, (), "morph_clear_driver_region", "Clear Garment Driver Region")

    def _refit_region_transaction_locked(self, session, targets, regions, action, label):
        payload = {"garment_submesh_indices": list(targets), "preserve_existing": True}
        if regions:
            payload["driver_regions"] = [
                {"submesh_index": item.submesh_index, "vertex_indices": list(item.vertex_indices)} for item in regions
            ]

        def bind():
            report = self._run_morph_command_locked(session, "morph_bind", payload, history_label=label, record_history=False)
            return self._morph_result_and_state_locked(session, action, report)[0]

        return self._morph_authoring_transaction_locked(session, action, label, bind)

    def _validate_authored_runtime_use_locked(self, session, command, payload):
        """Prevent saved deltas being applied to a sculpted or replaced zero base."""
        data = self._morph_sessions.get(session.session_id)
        if data is None or getattr(data, "authoring_operation", False) or data.profile is None:
            return
        if command not in {"morph_change", "morph_apply_preset", "morph_configure_refit"}:
            return
        definitions = tuple(item for item in data.profile.definitions if item.source_kind == "authored" or item.garment_corrections)
        if not definitions:
            return
        roles = tuple(sorted({item.submesh_index for definition in definitions for item in (*definition.vertices, *definition.garment_corrections)}))
        neutral = self._native_neutral_mesh_locked(session, roles)
        for definition in definitions:
            validate_morph_definition_geometry(neutral, definition)
            if definition.garment_corrections:
                bound = set(data.state.refit.garment_submesh_indices if data.state else ())
                if not {item.submesh_index for item in definition.garment_corrections}.issubset(bound):
                    raise RuntimeError("Bind every garment referenced by this profile's corrections before using its sliders.")

    def _apply_morph_authoring_command_locked(self, session, action, params, selection):
        if action == "refit_restore_shape_preview":
            return self.preview_refit_shape_restore(session.session_id, params.get("path"),
                params.get("submesh_indices", ()), islands=params.get("islands", ()), stop_event=params.get("stop_event"))[0]
        if action == "refit_restore_shape_apply":
            return self.apply_refit_shape_restore(session.session_id)[0]
        if action == "refit_restore_shape_cancel":
            return self.cancel_refit_shape_restore(session.session_id)[0]
        values = {key: value for key, value in params.items() if key != "stop_event"}
        if action == "morph_set_corrections_enabled":
            return self.set_morph_corrections_enabled(session.session_id, values.get("enabled"))[0]
        if action == "morph_reset_correction":
            return self.reset_morph_correction(session.session_id, values.get("definition_id"), values.get("garment_submesh_indices", ()))[0]
        if action == "morph_save_setup":
            return self.save_refit_setup(session.session_id, values.get("name"))[0]
        if action == "morph_apply_setup":
            return self.apply_refit_setup(session.session_id, values.get("recipe_id"), values.get("garment_submesh_indices", ()))[0]
        if action == "morph_capture_baseline":
            return self.capture_morph_baseline(session.session_id, values.get("submesh_indices", ()), selection=selection)[0]
        if action == "morph_cancel_baseline":
            return self.cancel_morph_baseline(session.session_id)[0]
        if action == "morph_capture_authored":
            return self.capture_authored_morph_definition(session.session_id, **values)[0]
        if action == "morph_begin_correction":
            return self.begin_morph_correction(session.session_id, values.get("definition_id"), values.get("garment_submesh_indices", ()))[0]
        if action == "morph_save_correction":
            return self.save_morph_correction(session.session_id)[0]
        if action == "morph_cancel_correction":
            return self.cancel_morph_correction(session.session_id)[0]
        if action == "morph_set_influence":
            return self.set_refit_vertex_influence(session.session_id, selection=selection, **values)[0]
        if action == "morph_clear_influence":
            return self.clear_refit_vertex_influence(session.session_id, values.get("garment_submesh_indices", ()), selection=selection)[0]
        if action == "morph_set_driver_region":
            return self.set_refit_driver_region(session.session_id, values.get("garment_submesh_indices", ()), selection=selection)[0]
        if action == "morph_clear_driver_region":
            return self.clear_refit_driver_region(session.session_id, values.get("garment_submesh_indices", ()))[0]
        if action == "morph_import_recipe":
            return self.import_refit_recipe(session.session_id, values.get("path"), values.get("garment_submesh_indices", ()))[0]
        if action == "morph_export_recipe":
            self.export_refit_recipe(session.session_id, values.get("path"), values.get("name"))
            return self._result(session, action)
        return None
