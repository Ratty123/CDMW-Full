"""Generate anatomical body sliders only from resolved, source-owned skinning.

PAC skin values are palette slots. Each source PAC supplies its own hash table;
descriptor source_bone_palette values are LOD selectors, not that table.
Only a temporary domain view contains resolved skeleton indices.
"""

from __future__ import annotations

import copy
import math
import operator
from collections import Counter
from typing import Mapping
from uuid import uuid4

from cdmw.domain.mesh import MeshEditResult, MeshMorphState
from cdmw.domain.mesh.body_region_sliders import build_region_slider_profile
from cdmw.domain.mesh.body_regions import build_body_region_map
from cdmw.modding.mesh_parser import PAC_SKIN_WEIGHT_LAYOUT, resolve_pac_bone_palette
from cdmw.services.mesh_archive_refit import ArchiveRefitContext


def _state_value(state, key, default=None):
    return state.get(key, default) if isinstance(state, Mapping) else getattr(state, key, default)


def _body_indices(mesh, raw_indices):
    indices = []
    for raw in tuple(raw_indices or ()):
        if isinstance(raw, bool):
            raise ValueError("Assigned body Parts must use exact integer indices.")
        try:
            index = operator.index(raw)
        except TypeError as exc:
            raise ValueError("Assigned body Parts must use exact integer indices.") from exc
        if index < 0 or index >= len(mesh.submeshes) or index in indices:
            raise ValueError("The assigned body Part identities are no longer valid.")
        indices.append(index)
    if not indices:
        raise ValueError("Assign the body Parts before generating body controls.")
    return tuple(sorted(indices))


def _skeleton_identity(skeleton):
    return tuple(
        (
            bone.name_hash, bone.name, bone.parent_index,
            tuple(bone.bind_matrix), tuple(bone.position),
        )
        for bone in tuple(getattr(skeleton, "bones", ()) or ())
    )


def _source_groups(session, indices):
    """Return selected Part indices, captured source mesh, and source PAC bytes."""
    mesh = session.working_mesh
    context = getattr(session, "archive_refit_context", None)
    if context is None:
        source = getattr(session, "base_mesh", None)
        if source is None or any(index >= len(source.submeshes) for index in indices):
            raise ValueError("The assigned body has no captured source Part mapping. Reopen it through the archive workflow.")
        return ((indices, source, tuple(indices), bytes(getattr(session, "original_data", b"") or b"")),)
    if not isinstance(context, ArchiveRefitContext):
        raise ValueError("The loaded outfit has no verified archive Part ownership.")
    all_indices = [index for asset in context.assets for index in asset.part_indices]
    if sorted(all_indices) != list(range(len(mesh.submeshes))):
        raise ValueError("Archive body Part identities changed. Reopen the body and outfit.")
    groups = []
    for asset in context.assets:
        selected = tuple(index for index in asset.part_indices if index in indices)
        if not selected:
            continue
        if len(asset.part_indices) != len(asset.source.mesh.submeshes):
            raise ValueError("The archived body Part table no longer matches its captured source.")
        local_indices = tuple(asset.part_indices.index(index) for index in selected)
        groups.append((selected, asset.source.mesh, local_indices, bytes(asset.source.original_data or b"")))
    return tuple(groups)


def _resolved_body_inputs(session, state):
    mesh = session.working_mesh
    indices = _body_indices(mesh, _state_value(state, "driver_submesh_indices", ()))
    skeleton = getattr(session, "skeleton", None)
    bones = tuple(getattr(skeleton, "bones", ()) or ())
    if not bones:
        raise ValueError("The body needs its matching resolved skeleton before body controls can be generated.")
    if any(getattr(bone, "index", position) != position for position, bone in enumerate(bones)):
        raise ValueError("The resolved skeleton has no exact ordered bone identity.")
    groups = []
    counts = Counter(getattr(bone, "name_hash", 0) for bone in bones)
    for selected, source, local_indices, data in _source_groups(session, indices):
        if str(getattr(source, "format", "")).casefold() != "pac":
            raise ValueError("Body control generation currently needs source-owned PAC body Parts.")
        if not data:
            raise ValueError("The body PAC source bytes are unavailable, so its bone palette cannot be verified.")
        source_skeleton = getattr(source, "interchange_skeleton", None)
        if source_skeleton is not None and _skeleton_identity(source_skeleton) != _skeleton_identity(skeleton):
            raise ValueError("The archived body uses a different resolved skeleton from this edit session.")
        palette = tuple(resolve_pac_bone_palette(data, skeleton))
        if not palette:
            raise ValueError("The body PAC bone palette did not resolve against this skeleton. Influence slots cannot be guessed.")
        if any(
            isinstance(index, bool) or not isinstance(index, int)
            or not 0 <= index < len(bones)
            or counts[getattr(bones[index], "name_hash", 0)] != 1
            for index in palette
        ):
            raise ValueError("The body PAC palette does not identify unique resolved skeleton bones.")
        for index, source_index in zip(selected, local_indices, strict=True):
            part, original = mesh.submeshes[index], source.submeshes[source_index]
            if (str(getattr(original, "source_skin_weight_layout", "")) != PAC_SKIN_WEIGHT_LAYOUT
                    or str(getattr(part, "source_skin_weight_layout", "")) != PAC_SKIN_WEIGHT_LAYOUT):
                raise ValueError("The body Part has no supported decoded PAC skin layout.")
        groups.append((selected, source, local_indices, palette))
    return skeleton, indices, tuple(groups)


def _mapped_body_view(mesh, groups):
    """Validate source ownership and map skin slots without touching live Parts."""
    view = copy.copy(mesh)
    view.submeshes = list(mesh.submeshes)
    for selected, source, local_indices, palette in groups:
        for index, source_index in zip(selected, local_indices, strict=True):
            part, original = mesh.submeshes[index], source.submeshes[source_index]
            source_map = tuple(getattr(original, "source_vertex_map", ()) or ())
            if (
                len(part.vertices) != len(original.vertices)
                or tuple(tuple(face) for face in part.faces) != tuple(tuple(face) for face in original.faces)
                or len(source_map) != len(original.vertices)
                or tuple(getattr(part, "source_vertex_map", ()) or ()) != source_map
                or tuple(tuple(row) for row in part.bone_indices) != tuple(tuple(row) for row in original.bone_indices)
                or tuple(tuple(row) for row in part.bone_weights) != tuple(tuple(row) for row in original.bone_weights)
            ):
                raise ValueError("The body Part topology or source skin identity differs from its captured PAC.")
            if len(part.bone_indices) != len(part.vertices) or len(part.bone_weights) != len(part.vertices):
                raise ValueError("The body Part has incomplete decoded skin rows.")
            mapped, weights = [], []
            for raw_slots, raw_weights in zip(part.bone_indices, part.bone_weights, strict=True):
                if len(raw_slots) != len(raw_weights):
                    raise ValueError("The body Part has inconsistent decoded skin rows.")
                row, row_weights = [], []
                for raw_slot, raw_weight in zip(raw_slots, raw_weights, strict=True):
                    if isinstance(raw_slot, bool):
                        raise ValueError("The body skin contains an invalid palette slot.")
                    try:
                        slot, weight = operator.index(raw_slot), float(raw_weight)
                    except (TypeError, ValueError, OverflowError) as exc:
                        raise ValueError("The body skin contains an invalid palette slot or weight.") from exc
                    if not math.isfinite(weight) or weight < 0.0:
                        raise ValueError("The body skin contains an invalid weight.")
                    if weight == 0.0:
                        continue
                    if not 0 <= slot < len(palette):
                        raise ValueError("A weighted body influence falls outside its verified PAC palette.")
                    row.append(palette[slot])
                    row_weights.append(weight)
                mapped.append(tuple(row))
                weights.append(tuple(row_weights))
            resolved = copy.copy(part)
            resolved.bone_indices, resolved.bone_weights = mapped, weights
            view.submeshes[index] = resolved
    return view


class MeshBodyControlsMixin:
    """Expose the existing body-region generator through one reversible edit."""

    def _body_controls_availability_locked(self, session, raw_state) -> tuple[bool, str]:
        cached = getattr(self, "_morph_sessions", {}).get(session.session_id)
        if _state_value(raw_state, "authoring_baseline_ready", False) or getattr(cached, "authoring_baseline", None) is not None:
            return False, "Save or discard the captured slider before generating body controls."
        if _state_value(raw_state, "correction_definition_id", "") or getattr(cached, "correction_capture", None) is not None:
            return False, "Save or cancel the outfit correction before generating body controls."
        if _state_value(raw_state, "topology_blocked", False):
            return False, "Resolve the changed body topology before generating body controls."
        if _state_value(raw_state, "busy", False):
            return False, "Finish the active edit before generating body controls."
        if _state_value(raw_state, "unbaked", False):
            return False, "Reset or Bake the active sliders before generating body controls."
        try:
            for source in (raw_state, cached):
                for key in ("values", "manual_values", "macro_values"):
                    values = _state_value(source, key, ()) or ()
                    values = values.items() if isinstance(values, Mapping) else values
                    if any(float(value) != 0.0 for _name, value in values):
                        return False, "Reset or Bake the active sliders before generating body controls."
            _resolved_body_inputs(session, raw_state)
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            return False, str(exc)
        return True, ""

    def generate_body_morph_controls(self, session_id) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            self._require_baked_morph_definition_edit(session)
            state = self._refresh_cached_morph_metadata_locked(session)
            available, reason = self._body_controls_availability_locked(session, state)
            if not available:
                raise ValueError(reason)
            skeleton, indices, groups = _resolved_body_inputs(session, state)
            neutral = self._native_neutral_mesh_locked(session, indices)
            mapped = _mapped_body_view(neutral, groups)
            region_map = build_body_region_map(
                mapped, skeleton, submesh_indices=indices,
                bone_palette=None, primary_influence_only=False,
            )
            profile = build_region_slider_profile(
                neutral, region_map, profile_id=f"body_regions_{uuid4().hex}",
                name="Anatomical Body Controls",
            )
            if not profile.definitions:
                raise ValueError("The assigned body has no named anatomical regions with a usable bone axis.")
            diagnostics = tuple(region_map.diagnostics)

            def generate():
                data = self._authoring_data_locked(session)
                if data.profile is not None:
                    data.known_profiles[data.profile.profile_id] = data.profile
                    data.available_profile_ids = tuple(dict.fromkeys((
                        *data.available_profile_ids, data.profile.profile_id,
                    )))
                return self._activate_morph_profile_locked(
                    session, profile, diagnostics, record_history=False,
                    preserve_runtime=True, base_mesh=neutral,
                    values={definition.definition_id: 0.0 for definition in profile.definitions},
                )[0]

            return self._morph_authoring_transaction_locked(
                session, "morph_generate_body_controls", "Generate Anatomical Body Controls", generate,
            )
